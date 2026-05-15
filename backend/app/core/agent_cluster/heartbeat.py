"""
Heartbeat Manager - Manages independent heartbeats for each agent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .registry import AgentRegistry, get_registry

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatConfig:
    """Configuration for an agent's heartbeat."""
    agent_name: str
    interval: str = "5m"  # e.g., "30s", "5m", "1h"
    tasks: list[str] = field(default_factory=list)
    enabled: bool = True
    cooldown_seconds: int = 30
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None


class HeartbeatManager:
    """
    Manages heartbeats for all registered agents.

    Each agent can have independent heartbeat configuration.
    Heartbeats are staggered to prevent thundering herd.
    """

    def __init__(self, registry: Optional[AgentRegistry] = None) -> None:
        self._registry = registry or get_registry()
        self._configs: dict[str, HeartbeatConfig] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._lock = asyncio.Lock()
        self._cooldowns: dict[str, datetime] = {}

    def configure(self, config: HeartbeatConfig) -> None:
        """Configure heartbeat for an agent."""
        self._configs[config.agent_name] = config
        logger.info(f"Configured heartbeat for {config.agent_name}: interval={config.interval}")

    def get_config(self, agent_name: str) -> Optional[HeartbeatConfig]:
        """Get heartbeat config for an agent."""
        return self._configs.get(agent_name)

    def disable(self, agent_name: str) -> None:
        """Disable heartbeat for an agent."""
        if agent_name in self._configs:
            self._configs[agent_name].enabled = False
            logger.info(f"Disabled heartbeat for {agent_name}")

    def enable(self, agent_name: str) -> None:
        """Enable heartbeat for an agent."""
        if agent_name in self._configs:
            self._configs[agent_name].enabled = True
            logger.info(f"Enabled heartbeat for {agent_name}")

    async def start(self) -> None:
        """Start the heartbeat manager."""
        self._running = True

        # Start heartbeat tasks for all configured agents
        for agent_name, config in self._configs.items():
            if config.enabled:
                self._tasks[agent_name] = asyncio.create_task(
                    self._heartbeat_loop(agent_name)
                )

        logger.info(f"HeartbeatManager started with {len(self._tasks)} agents")

    async def stop(self) -> None:
        """Stop the heartbeat manager."""
        self._running = False

        for task in self._tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()
        logger.info("HeartbeatManager stopped")

    async def trigger(
        self,
        agent_name: str,
        callback: Callable,
    ) -> bool:
        """
        Trigger immediate heartbeat for an agent.

        Args:
            agent_name: Agent to trigger
            callback: Async function to call

        Returns:
            True if triggered, False if in cooldown
        """
        # Check cooldown
        if agent_name in self._cooldowns:
            last_run = self._cooldowns[agent_name]
            config = self._configs.get(agent_name)
            if config:
                cooldown_seconds = config.cooldown_seconds
                elapsed = (datetime.utcnow() - last_run).total_seconds()
                if elapsed < cooldown_seconds:
                    logger.debug(
                        f"Heartbeat for {agent_name} in cooldown: "
                        f"{cooldown_seconds - elapsed:.1f}s remaining"
                    )
                    return False

        # Execute heartbeat
        try:
            await callback()
            self._cooldowns[agent_name] = datetime.utcnow()
            return True
        except Exception as e:
            logger.error(f"Heartbeat trigger failed for {agent_name}: {e}")
            return False

    async def _heartbeat_loop(self, agent_name: str) -> None:
        """Internal heartbeat loop for an agent."""
        config = self._configs.get(agent_name)
        if not config:
            return

        interval_seconds = self._parse_interval(config.interval)

        while self._running and config.enabled:
            try:
                # Stagger initial delay to prevent thundering herd
                if config.last_run is None:
                    await asyncio.sleep(interval_seconds * 0.1 * hash(agent_name) % 10)

                # Check if in cooldown
                if agent_name in self._cooldowns:
                    elapsed = (datetime.utcnow() - self._cooldowns[agent_name]).total_seconds()
                    if elapsed < config.cooldown_seconds:
                        await asyncio.sleep(config.cooldown_seconds - elapsed)

                config.last_run = datetime.utcnow()

                # Get agent and run heartbeat
                result = self._registry.get(agent_name)
                if result:
                    agent, _ = result
                    await agent.heartbeat()

                # Calculate next run
                config.next_run = datetime.utcnow()
                await asyncio.sleep(interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error for {agent_name}: {e}")
                await asyncio.sleep(interval_seconds)

    @staticmethod
    def _parse_interval(interval: str) -> int:
        """Parse interval string to seconds."""
        interval = interval.strip().lower()

        if interval.endswith("s"):
            return int(interval[:-1])
        elif interval.endswith("m"):
            return int(interval[:-1]) * 60
        elif interval.endswith("h"):
            return int(interval[:-1]) * 3600
        elif interval.endswith("d"):
            return int(interval[:-1]) * 86400
        else:
            try:
                return int(interval)
            except ValueError:
                return 300  # default 5 minutes


# Default heartbeat configurations for standard agents
DEFAULT_HEARTBEAT_CONFIGS = {
    "master": HeartbeatConfig(
        agent_name="master",
        interval="1m",
        tasks=["check_cluster_health", "balance_load"],
    ),
    "coder": HeartbeatConfig(
        agent_name="coder",
        interval="5m",
        tasks=["check_code_quality", "scan_dependencies"],
    ),
    "reviewer": HeartbeatConfig(
        agent_name="reviewer",
        interval="10m",
        tasks=["review_pending_changes"],
    ),
    "memory": HeartbeatConfig(
        agent_name="memory",
        interval="15m",
        tasks=["consolidate_memories", "cleanup_old_memories"],
    ),
    "scheduler": HeartbeatConfig(
        agent_name="scheduler",
        interval="1m",
        tasks=["check_scheduled_tasks", "trigger_due_tasks"],
    ),
    "monitor": HeartbeatConfig(
        agent_name="monitor",
        interval="30s",
        tasks=["check_system_health", "report_metrics"],
    ),
    "security": HeartbeatConfig(
        agent_name="security",
        interval="5m",
        tasks=["scan_vulnerabilities", "check_access_logs"],
    ),
}
