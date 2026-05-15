"""
Base Platform Adapter - Abstract base for all platform implementations.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
import asyncio
import logging
import time

from ..registry import PlatformAdapter
from ..session import SessionContext, PlatformIdentity

logger = logging.getLogger(__name__)

# Default health monitor constants
DEFAULT_STALE_EVENT_THRESHOLD_MS = 30 * 60 * 1000  # 30 minutes
DEFAULT_CHECK_INTERVAL_MS = 5 * 60 * 1000  # 5 minutes
DEFAULT_MONITOR_STARTUP_GRACE_MS = 60 * 1000  # 1 minute
DEFAULT_CHANNEL_CONNECT_GRACE_MS = 120 * 1000  # 2 minutes
DEFAULT_COOLDOWN_CYCLES = 2
DEFAULT_MAX_RESTARTS_PER_HOUR = 10
ONE_HOUR_MS = 60 * 60 * 1000


@dataclass
class ChannelHealthStatus:
    """Health status snapshot for a channel."""
    running: bool = False
    connected: bool = False
    enabled: bool = True
    configured: bool = True
    restart_pending: bool = False
    busy: bool = False
    active_runs: int = 0
    last_run_activity_at: Optional[float] = None
    last_event_at: Optional[float] = None
    last_connected_at: Optional[float] = None
    last_transport_activity_at: Optional[float] = None
    last_start_at: Optional[float] = None
    reconnect_attempts: int = 0


class ChannelHealthMonitor:
    """
    Monitor channel health and auto-restart unhealthy channels.

    Tracks last_event_at timestamp and detects stale channels
    that haven't received any transport activity beyond the threshold.
    """

    def __init__(
        self,
        get_channel_status: Callable[[], dict[str, ChannelHealthStatus]],
        restart_channel: Callable[[str], Awaitable[None]],
        check_interval_ms: int = DEFAULT_CHECK_INTERVAL_MS,
        stale_event_threshold_ms: int = DEFAULT_STALE_EVENT_THRESHOLD_MS,
        monitor_startup_grace_ms: int = DEFAULT_MONITOR_STARTUP_GRACE_MS,
        channel_connect_grace_ms: int = DEFAULT_CHANNEL_CONNECT_GRACE_MS,
        cooldown_cycles: int = DEFAULT_COOLDOWN_CYCLES,
        max_restarts_per_hour: int = DEFAULT_MAX_RESTARTS_PER_HOUR,
    ):
        """
        Initialize the health monitor.

        Args:
            get_channel_status: Callable that returns a dict of channel_id -> ChannelHealthStatus
            restart_channel: Callable that restarts a channel by channel_id
            check_interval_ms: How often to check channel health
            stale_event_threshold_ms: How long without transport activity before considered stale
            monitor_startup_grace_ms: Grace period at monitor start before checks begin
            channel_connect_grace_ms: Grace period after channel connect before health checks apply
            cooldown_cycles: Number of check cycles to wait between restarts
            max_restarts_per_hour: Maximum restarts allowed per hour per channel
        """
        self._get_channel_status = get_channel_status
        self._restart_channel = restart_channel
        self._check_interval_ms = check_interval_ms
        self._stale_event_threshold_ms = stale_event_threshold_ms
        self._monitor_startup_grace_ms = monitor_startup_grace_ms
        self._channel_connect_grace_ms = channel_connect_grace_ms
        self._cooldown_cycles = cooldown_cycles
        self._max_restarts_per_hour = max_restarts_per_hour

        self._cooldown_ms = cooldown_cycles * check_interval_ms
        self._restart_records: dict[str, dict] = {}
        self._started_at: float = time.time() * 1000
        self._stopped: bool = False
        self._check_in_flight: bool = False
        self._timer: Optional[asyncio.Task] = None

    def _prune_old_restarts(self, record: dict, now: float) -> None:
        """Remove restart records older than one hour."""
        record["restarts_this_hour"] = [
            r for r in record["restarts_this_hour"] if now - r["at"] < ONE_HOUR_MS
        ]

    def _is_healthy(self, status: ChannelHealthStatus, now: float) -> tuple[bool, str]:
        """
        Evaluate channel health.

        Returns:
            Tuple of (is_healthy, reason)
        """
        # Unmanaged channels are considered healthy
        if not status.enabled or not status.configured:
            return True, "unmanaged"

        # Not running is unhealthy
        if not status.running:
            return False, "not-running"

        # Busy is healthy if recently active
        if status.busy or status.active_runs > 0:
            last_run = status.last_run_activity_at
            if last_run is not None:
                run_age = now - last_run
                if run_age < 25 * 60 * 1000:  # 25 minutes
                    return True, "busy"
                return False, "stuck"

        # Startup grace period
        if status.last_start_at is not None:
            up_duration = now - status.last_start_at
            if up_duration < self._channel_connect_grace_ms:
                return True, "startup-connect-grace"

        # Disconnected is unhealthy
        if not status.connected:
            return False, "disconnected"

        # Check for stale socket (no transport activity)
        if status.connected and status.last_transport_activity_at is not None:
            if status.last_start_at is not None and status.last_transport_activity_at < status.last_start_at:
                # Transport activity predates current lifecycle
                lifecycle_gap = now - status.last_start_at
                if lifecycle_gap <= self._stale_event_threshold_ms:
                    return True, "healthy"
                return False, "stale-socket"

            event_age = now - status.last_transport_activity_at
            if event_age > self._stale_event_threshold_ms:
                return False, "stale-socket"

        return True, "healthy"

    def _resolve_restart_reason(self, status: ChannelHealthStatus, reason: str) -> str:
        """Resolve the restart reason based on health evaluation."""
        if reason == "stale-socket":
            return "stale-socket"
        if reason == "not-running":
            if status.reconnect_attempts >= 10:
                return "gave-up"
            return "stopped"
        if reason == "disconnected":
            return "disconnected"
        return "stuck"

    async def _run_check(self) -> None:
        """Run a single health check cycle."""
        if self._stopped or self._check_in_flight:
            return

        self._check_in_flight = True
        try:
            now = time.time() * 1000

            # Check startup grace period
            if now - self._started_at < self._monitor_startup_grace_ms:
                return

            channel_statuses = self._get_channel_status()

            for channel_id, status in channel_statuses.items():
                if not isinstance(status, ChannelHealthStatus):
                    continue

                healthy, reason = self._is_healthy(status, now)
                if healthy:
                    continue

                # Check cooldown
                record = self._restart_records.get(channel_id, {
                    "last_restart_at": 0,
                    "restarts_this_hour": [],
                })

                if now - record["last_restart_at"] <= self._cooldown_ms:
                    continue

                self._prune_old_restarts(record, now)

                # Check restart limit
                if len(record["restarts_this_hour"]) >= self._max_restarts_per_hour:
                    logger.warning(
                        f"[{channel_id}] health-monitor: hit {self._max_restarts_per_hour} "
                        "restarts/hour limit, skipping"
                    )
                    continue

                restart_reason = self._resolve_restart_reason(status, reason)
                logger.info(
                    f"[{channel_id}] health-monitor: restarting (reason: {restart_reason})"
                )

                record["last_restart_at"] = now
                record["restarts_this_hour"].append({"at": now})
                self._restart_records[channel_id] = record

                try:
                    if status.running:
                        # Signal channel to stop (non-manual restart)
                        status.restart_pending = True
                    await self._restart_channel(channel_id)
                except Exception as err:
                    logger.error(
                        f"[{channel_id}] health-monitor: restart failed: {err}"
                    )

        except Exception as err:
            logger.error(f"health-monitor: check failed: {err}")
        finally:
            self._check_in_flight = False

    async def _run_loop(self) -> None:
        """Main health check loop."""
        while not self._stopped:
            await asyncio.sleep(self._check_interval_ms / 1000)
            if not self._stopped:
                await self._run_check()

    async def start(self) -> "ChannelHealthMonitor":
        """Start the health monitor."""
        self._timer = asyncio.create_task(self._run_loop())
        logger.info(
            f"health-monitor: started (interval: {self._check_interval_ms / 1000}s, "
            f"startup-grace: {self._monitor_startup_grace_ms / 1000}s, "
            f"channel-connect-grace: {self._channel_connect_grace_ms / 1000}s)"
        )
        return self

    def stop(self) -> None:
        """Stop the health monitor."""
        self._stopped = True
        if self._timer and not self._timer.done():
            self._timer.cancel()
        logger.info("health-monitor: stopped")


class BasePlatformAdapter(PlatformAdapter):
    """
    Base class with common functionality for platform adapters.

    Provides default implementations for common operations and
    defines the interface that all platform adapters must implement.
    """

    name: str = "base"
    supports_streaming: bool = False

    def __init__(self):
        self._connected: bool = False
        self._message_handler: Optional[Callable[[SessionContext], Awaitable[None]]] = None
        self._last_event_at: Optional[float] = None
        self._last_transport_activity_at: Optional[float] = None
        self._last_connected_at: Optional[float] = None
        self._last_start_at: Optional[float] = None
        self._running: bool = False
        self._busy: bool = False
        self._active_runs: int = 0
        self._restart_pending: bool = False
        self._reconnect_attempts: int = 0

    @property
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self._connected

    @property
    def last_event_at(self) -> Optional[float]:
        """Get the timestamp of the last event received."""
        return self._last_event_at

    def _record_event(self) -> None:
        """Record that an event was received (updates last_event_at and transport activity)."""
        now = time.time() * 1000
        self._last_event_at = now
        self._last_transport_activity_at = now

    def _record_connect(self) -> None:
        """Record a connection event."""
        now = time.time() * 1000
        self._last_connected_at = now
        self._last_transport_activity_at = now

    def get_health_status(self) -> ChannelHealthStatus:
        """
        Get the current health status of this channel.

        Returns a ChannelHealthStatus snapshot for the health monitor.
        """
        return ChannelHealthStatus(
            running=self._running,
            connected=self._connected,
            enabled=True,
            configured=True,
            restart_pending=self._restart_pending,
            busy=self._busy,
            active_runs=self._active_runs,
            last_run_activity_at=self._last_event_at,
            last_event_at=self._last_event_at,
            last_connected_at=self._last_connected_at,
            last_transport_activity_at=self._last_transport_activity_at,
            last_start_at=self._last_start_at,
            reconnect_attempts=self._reconnect_attempts,
        )

    async def connect(self) -> None:
        """Connect to the platform. Override in subclass."""
        self._running = True
        self._last_start_at = time.time() * 1000
        self._connected = True
        self._record_connect()
        logger.info(f"{self.name}: Connected")

    async def disconnect(self) -> None:
        """Disconnect from the platform. Override in subclass."""
        self._running = False
        self._connected = False
        logger.info(f"{self.name}: Disconnected")

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """Send a message. Must be implemented by subclass."""
        pass

    @abstractmethod
    async def send_card(
        self,
        chat_id: str,
        card: dict,
        **kwargs,
    ) -> Optional[str]:
        """Send an interactive card. Must be implemented by subclass."""
        pass

    async def format_for_platform(self, content: str, **kwargs) -> str:
        """Format content for this platform. Override for platform-specific formatting."""
        # Default: apply length limits
        max_length = kwargs.get("max_length", 4000)
        if len(content) > max_length:
            content = content[: max_length - 3] + "..."
        return content

    def set_message_handler(self, handler: Callable[[SessionContext], Awaitable[None]]) -> None:
        """
        Set the handler for incoming messages.

        The handler will be called for each message received from this platform.
        """
        self._message_handler = handler

    async def _handle_incoming(self, session_context: SessionContext) -> None:
        """Internal handler that routes incoming messages to the registered handler."""
        self._record_event()
        if self._message_handler:
            try:
                await self._message_handler(session_context)
            except Exception as e:
                logger.error(f"{self.name}: Error in message handler: {e}")
        else:
            logger.warning(f"{self.name}: No message handler set")

    def _build_identity(self, event: dict) -> PlatformIdentity:
        """
        Build PlatformIdentity from a platform event.

        Override in subclass to extract correct fields.
        """
        return PlatformIdentity(
            platform=self.name,
            user_id=event.get("user_id", "unknown"),
            chat_id=event.get("chat_id", "unknown"),
        )

    async def validate_event(self, event: dict) -> bool:
        """
        Validate an incoming event.

        Override to add platform-specific validation.
        """
        return True
