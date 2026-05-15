"""
Heartbeat Runner - Orchestrates periodic heartbeat execution.
"""

import asyncio
import logging
import signal
import traceback
from datetime import datetime
from typing import Callable, Optional, Awaitable

from .scheduler import HeartbeatScheduler, HeartbeatConfig
from .cooldown import CooldownManager, CooldownConfig
from .wake import (
    HeartbeatWakeSource,
    HeartbeatWakeRequest,
    set_heartbeat_wake_handler,
    clear_coalesce_cache,
)

logger = logging.getLogger(__name__)

# Health check task names (these run directly, not via LLM handler)
HEALTH_CHECK_TASKS = frozenset([
    "gateway-health",
    "unanswered-check",
    "missed-crons-check",
    "daily-stats",
])


# Default heartbeat tasks that run on each heartbeat
DEFAULT_HEARTBEAT_TASKS = [
    {
        "name": "memory-review",
        "interval": "1h",
        "prompt": "回顾最近的对话，提取用户偏好和任何新的事实到记忆中",
    },
    {
        "name": "skill-check",
        "interval": "30m",
        "prompt": "检查是否有需要创建或更新的 Skill",
    },
    {
        "name": "gateway-health",
        "interval": "5m",
        "prompt": "检查 Gateway 健康状态（进程、锁文件、连接）",
        "health_check": True,
    },
    {
        "name": "unanswered-check",
        "interval": "15m",
        "prompt": "扫描未回复的用户消息",
        "health_check": True,
    },
    {
        "name": "missed-crons-check",
        "interval": "1h",
        "prompt": "检查关键 Cron 任务是否执行",
        "health_check": True,
    },
    {
        "name": "daily-stats",
        "interval": "6h",
        "prompt": "生成每日统计报告（消息量、错误率、Gateway状态）",
        "health_check": True,
    },
]


class HeartbeatRunner:
    """
    Orchestrates periodic heartbeat execution.

    The heartbeat is a periodic main-session turn that batches
    multiple maintenance tasks. Inspired by OpenCLAW's heartbeat system.

    Features:
    - Configurable interval with jitter to prevent thundering herd
    - Active hours support (e.g., only run during business hours)
    - Cooldown to prevent heartbeat spam
    - Multiple wake sources (interval, cron, hooks, etc.)
    """

    def __init__(
        self,
        config: Optional[HeartbeatConfig] = None,
        cooldown_config: Optional[CooldownConfig] = None,
        tasks: Optional[list[dict]] = None,
    ):
        self.config = config or HeartbeatConfig()
        self.tasks = tasks or DEFAULT_HEARTBEAT_TASKS

        self._scheduler = HeartbeatScheduler(self.config)
        self._cooldown = CooldownManager(cooldown_config or CooldownConfig())
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._next_due_ms: int = 0
        self._heartbeat_handler: Optional[Callable[[list[dict]], Awaitable[None]]] = None
        self._lock = asyncio.Lock()

    def set_heartbeat_handler(self, handler: Callable[[list[dict]], Awaitable[None]]) -> None:
        """
        Set the handler that executes heartbeat tasks.

        The handler receives the list of tasks to run.
        """
        self._heartbeat_handler = handler

    async def start(self) -> None:
        """Start the heartbeat runner."""
        if self._running:
            logger.warning("HeartbeatRunner already running")
            return

        self._running = True
        self._next_due_ms = self._scheduler.calculate_next(
            int(datetime.utcnow().timestamp() * 1000)
        )

        # Set up wake handler
        set_heartbeat_wake_handler(self._handle_wake_request)

        # Start the runner loop
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"HeartbeatRunner started: interval={self.config.interval_ms}ms, "
            f"phase={self._scheduler._schedule.phase_ms}ms"
        )

    async def stop(self) -> None:
        """Stop the heartbeat runner."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("HeartbeatRunner stopped")

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}\n{traceback.format_exc()}")

            # Wait a bit before next check
            await asyncio.sleep(10)  # Check every 10 seconds

    async def _tick(self) -> None:
        """Check and execute heartbeat if due."""
        now_ms = int(datetime.utcnow().timestamp() * 1000)

        # Check if past due
        if now_ms < self._next_due_ms:
            logger.debug(f"Heartbeat not yet due: now={now_ms}, due={self._next_due_ms}")
            return

        # Check cooldown
        should_defer, reason = await self._cooldown.should_defer()
        if should_defer:
            logger.debug(f"Heartbeat deferred: {reason}")
            return

        # Check if within active hours
        if not self._scheduler.is_active_at(now_ms):
            logger.debug("Heartbeat deferred: outside active hours")
            # Schedule for next active period
            self._next_due_ms = self._scheduler.calculate_next(now_ms, self._next_due_ms)
            return

        # Execute heartbeat
        await self._execute_heartbeat()

        # Record and calculate next
        await self._cooldown.record_heartbeat(triggered=True)
        self._next_due_ms = self._scheduler.calculate_next(now_ms, self._next_due_ms)

        # Clear coalesce cache
        clear_coalesce_cache()

    async def _execute_heartbeat(self) -> None:
        """Execute the heartbeat tasks."""
        logger.info(f"Heartbeat executing at {datetime.utcnow().isoformat()}")

        # Execute health check tasks directly (not via LLM)
        await self._run_health_checks()

        # Execute LLM-based tasks via handler
        llm_tasks = [t for t in self.tasks if t.get("name") not in HEALTH_CHECK_TASKS]
        if self._heartbeat_handler:
            try:
                await self._heartbeat_handler(llm_tasks)
            except Exception as e:
                logger.error(f"Error executing heartbeat tasks: {e}\n{traceback.format_exc()}")
        else:
            logger.debug("No heartbeat handler set, skipping")

    async def _run_health_checks(self) -> None:
        """
        Run health check tasks that don't need LLM processing.

        These run on every heartbeat but respect their configured intervals
        via the tick rate limiter in _tick().
        """
        try:
            from app.core.health import (
                check_gateway_health,
                check_unanswered_sessions,
                check_missed_crons,
                get_daily_stats,
            )

            for task in self.tasks:
                if task.get("name") not in HEALTH_CHECK_TASKS:
                    continue

                task_name = task["name"]
                try:
                    if task_name == "gateway-health":
                        result = await check_gateway_health()
                        if not result.all_ok:
                            logger.warning(
                                f"Gateway health check issues: "
                                f"{result.issues_detected} detected, "
                                f"{result.issues_fixed} fixed"
                            )
                    elif task_name == "unanswered-check":
                        result = await check_unanswered_sessions()
                        if not result.all_ok:
                            logger.warning(
                                f"Unanswered sessions detected: {result.count}"
                            )
                    elif task_name == "missed-crons-check":
                        result = await check_missed_crons()
                        if not result.all_ok:
                            logger.warning(
                                f"Missed cron jobs: {result.missed_count}"
                            )
                    elif task_name == "daily-stats":
                        stats = await get_daily_stats()
                        logger.info(
                            f"Daily stats: {stats.get('total_messages', 0)} messages, "
                            f"{stats.get('total_errors', 0)} errors"
                        )
                except Exception as e:
                    logger.warning(f"Health check '{task_name}' failed: {e}\n{traceback.format_exc()}")
        except Exception as e:
            logger.debug(f"Health check module unavailable: {e}\n{traceback.format_exc()}")

    def _handle_wake_request(self, request: HeartbeatWakeRequest) -> None:
        """Handle an incoming wake request."""
        logger.info(f"Heartbeat wake requested: {request.source.value} - {request.intent}")

        # Schedule immediate execution by setting next_due_ms to now
        now_ms = int(datetime.utcnow().timestamp() * 1000)

        # Check cooldown first
        # Note: This is sync but we're in the handler which is called from async context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._execute_wake(request))
        except Exception as e:
            logger.error(f"Error scheduling wake: {e}")

    async def _execute_wake(self, request: HeartbeatWakeRequest) -> None:
        """Execute a wake-triggered heartbeat."""
        should_defer, _ = await self._cooldown.should_defer()
        if should_defer:
            logger.debug("Wake deferred due to cooldown")
            return

        logger.info(f"Wake heartbeat executing: {request.intent}")
        await self._execute_heartbeat()
        await self._cooldown.record_heartbeat(triggered=True)

    async def trigger_now(self, source: HeartbeatWakeSource = HeartbeatWakeSource.API) -> bool:
        """
        Trigger an immediate heartbeat.

        Args:
            source: What triggered this request

        Returns:
            True if triggered, False if deferred
        """
        should_defer, reason = await self._cooldown.should_defer()
        if should_defer:
            logger.info(f"Immediate heartbeat deferred: {reason}")
            return False

        await self._execute_heartbeat()
        await self._cooldown.record_heartbeat(triggered=True)
        return True

    def get_status(self) -> dict:
        """Get current heartbeat runner status."""
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        return {
            "running": self._running,
            "scheduler": self._scheduler.get_status(),
            "cooldown": self._cooldown.get_status(),
            "next_due_ms": self._next_due_ms,
            "next_due_in_seconds": max(0, (self._next_due_ms - now_ms) / 1000),
            "tasks_count": len(self.tasks),
        }
