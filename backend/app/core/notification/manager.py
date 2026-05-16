"""NotificationManager - central dispatcher for all notification channels."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional

from app.core.notification.events import NotificationEvent, NotificationSeverity
from app.core.notification.channels.base import NotificationChannel
from app.core.notification.channels.feishu import FeishuNotifier
from app.core.notification.channels.email import EmailNotifier
from app.core.notification.channels.system import SystemNotifier

logger = logging.getLogger(__name__)

# Quiet hours: no notifications below CRITICAL during this time (UTC+8)
_QUIET_START = 23  # 23:00
_QUIET_END = 8    # 08:00


def _in_quiet_hours() -> bool:
    """Check if current time is in quiet hours (UTC+8)."""
    now_utc8 = datetime.now(timezone.utc).astimezone()
    hour = now_utc8.hour
    if _QUIET_START <= 24 and _QUIET_END == 0:
        return hour >= _QUIET_START or hour < _QUIET_END
    if _QUIET_START < _QUIET_END:
        return _QUIET_START <= hour < _QUIET_END
    # e.g. 23:00 to 08:00 (crosses midnight)
    return hour >= _QUIET_START or hour < _QUIET_END


class NotificationPriority(IntEnum):
    """Notification delivery priority (lower = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class NotificationConfig:
    """Global notification configuration."""
    enabled: bool = True
    feishu_enabled: bool = True
    email_enabled: bool = False
    email_api_key: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    feishu_open_id: str = "ou_bd6d23d82e92c82ecf712192c22eedab"
    critical_threshold: int = 1
    warning_threshold: int = 3
    quiet_hours: tuple[int, int] = (_QUIET_START, _QUIET_END)
    # Retry config
    max_retries: int = 3
    retry_base_delay: float = 2.0  # seconds (exponential backoff)
    # System notification
    system_enabled: bool = True

    @property
    def quiet_start(self) -> int:
        return self.quiet_hours[0]

    @property
    def quiet_end(self) -> int:
        return self.quiet_hours[1]


@dataclass
class _DedupeKey:
    """Deduplication key for notifications."""
    source: str
    title: str

    def __hash__(self) -> int:
        return hash((self.source, self.title))


@dataclass
class _RetryEntry:
    """Retry state for a notification event."""
    event: NotificationEvent
    channel: NotificationChannel
    attempt: int = 0
    last_error: Optional[str] = None


class NotificationManager:
    """
    Central notification dispatcher.

    Routes NotificationEvents to the appropriate channels (Feishu, Email, System, etc.)
    based on severity and configuration. Handles deduplication, quiet hours,
    priority queuing, and automatic retry with exponential backoff.
    """

    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        self.config = config or NotificationConfig()
        self._channels: list[NotificationChannel] = []
        self._dedupe: dict[_DedupeKey, float] = {}
        self._dedupe_ttl_seconds = 300  # 5 minutes

        # Priority queue: sorted list of pending events
        self._queue: list[tuple[NotificationPriority, NotificationEvent]] = []
        self._queue_lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._retry_entries: dict[str, _RetryEntry] = {}
        self._retry_lock = asyncio.Lock()

        self._setup_channels()

    def _setup_channels(self) -> None:
        """Initialize enabled notification channels."""
        if self.config.feishu_enabled:
            feishu = FeishuNotifier(
                recipient_open_id=self.config.feishu_open_id,
                enabled=self.config.feishu_enabled,
            )
            self._channels.append(feishu)
            logger.info("[NotificationManager] Feishu channel enabled")

        if self.config.email_enabled and self.config.email_api_key:
            email = EmailNotifier(
                api_key=self.config.email_api_key,
                from_email=self.config.email_from,
                to_email=self.config.email_to,
                enabled=True,
            )
            self._channels.append(email)
            logger.info("[NotificationManager] Email channel enabled")

        if self.config.system_enabled:
            system = SystemNotifier(enabled=True)
            self._channels.append(system)
            logger.info("[NotificationManager] System channel enabled")

    def _start_worker(self) -> None:
        """Start the background queue worker if not already running."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._queue_worker())

    def _priority_of(self, event: NotificationEvent) -> NotificationPriority:
        """Map severity to delivery priority."""
        mapping = {
            NotificationSeverity.CRITICAL: NotificationPriority.CRITICAL,
            NotificationSeverity.WARNING: NotificationPriority.HIGH,
            NotificationSeverity.INFO: NotificationPriority.NORMAL,
        }
        return mapping.get(event.severity, NotificationPriority.NORMAL)

    def _is_dupe(self, event: NotificationEvent) -> bool:
        """Check if event is a duplicate (within dedupe window)."""
        now = datetime.now(timezone.utc).timestamp()
        key = _DedupeKey(source=event.source, title=event.title)

        if key in self._dedupe:
            age = now - self._dedupe[key]
            if age < self._dedupe_ttl_seconds:
                return True

        self._dedupe[key] = now
        # Clean old entries
        self._dedupe = {k: v for k, v in self._dedupe.items() if now - v < self._dedupe_ttl_seconds}
        return False

    def _should_deliver(self, event: NotificationEvent) -> bool:
        """Check if event should be delivered based on quiet hours and thresholds."""
        if not self.config.enabled:
            return False

        if event.severity == NotificationSeverity.CRITICAL:
            return True

        # Warning and Info: skip during quiet hours
        if _in_quiet_hours():
            logger.debug(f"[NotificationManager] Skipping {event.severity.value} notification during quiet hours")
            return False

        return True

    async def dispatch(self, event: NotificationEvent) -> None:
        """
        Dispatch a notification event to all appropriate channels.

        Queues the event for delivery, then returns immediately.
        Actual delivery happens in the background worker.

        Args:
            event: The notification event to send.
        """
        if not self._should_deliver(event):
            logger.debug(f"[NotificationManager] Dropping notification: {event.title} ({event.severity.value})")
            return

        if self._is_dupe(event):
            logger.debug(f"[NotificationManager] Dedupe: {event.title}")
            return

        priority = self._priority_of(event)
        logger.info(f"[NotificationManager] Enqueuing: [{event.severity.value}] {event.title} (priority={priority.name})")

        async with self._queue_lock:
            # Insert in priority order
            self._queue.append((priority, event))
            self._queue.sort(key=lambda x: x[0])  # Lower priority value = higher priority
            self._start_worker()

    async def _queue_worker(self) -> None:
        """Background worker that drains the priority queue."""
        while True:
            async with self._queue_lock:
                if not self._queue:
                    self._worker_task = None
                    break
                _priority, event = self._queue.pop(0)

            await self._deliver_to_all_channels(event)

            # Small delay between batches to avoid hammering
            await asyncio.sleep(0.1)

    async def _deliver_to_all_channels(self, event: NotificationEvent) -> None:
        """Send event to all channels, with retry on failure."""
        tasks = []
        for channel in self._channels:
            if event.severity == NotificationSeverity.CRITICAL:
                tasks.append(self._send_with_retry(channel, event, NotificationSeverity.CRITICAL))
            elif event.severity == NotificationSeverity.WARNING:
                tasks.append(self._send_with_retry(channel, event, NotificationSeverity.WARNING))
            else:
                tasks.append(self._send_with_retry(channel, event, NotificationSeverity.INFO))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for channel, result in zip(self._channels, results):
                if isinstance(result, Exception):
                    logger.warning(f"[{channel.name}] Exception: {result}")

    async def _send_with_retry(
        self,
        channel: NotificationChannel,
        event: NotificationEvent,
        severity: NotificationSeverity,
    ) -> bool:
        """Send to a channel with exponential backoff retry."""
        # Select the right method
        if severity == NotificationSeverity.CRITICAL:
            send_fn = channel.send_critical
        elif severity == NotificationSeverity.WARNING:
            send_fn = channel.send_warning
        else:
            send_fn = channel.send_info

        retry_key = f"{channel.name}:{event.source}:{event.title}"

        for attempt in range(self.config.max_retries + 1):
            try:
                success = await send_fn(event)
                if success:
                    if attempt > 0:
                        logger.info(f"[{channel.name}] Retry {attempt} succeeded for: {event.title}")
                    return True
                if attempt < self.config.max_retries:
                    delay = self.config.retry_base_delay * (2 ** attempt)
                    logger.debug(f"[{channel.name}] Attempt {attempt + 1} failed, retrying in {delay:.1f}s: {event.title}")
                    await asyncio.sleep(delay)
            except Exception as e:
                if attempt < self.config.max_retries:
                    delay = self.config.retry_base_delay * (2 ** attempt)
                    logger.warning(f"[{channel.name}] Error on attempt {attempt + 1}: {e}, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"[{channel.name}] All {self.config.max_retries + 1} attempts failed for: {event.title}: {e}")

        # All retries exhausted — record for monitoring
        async with self._retry_lock:
            self._retry_entries[retry_key] = _RetryEntry(
                event=event,
                channel=channel,
                attempt=self.config.max_retries,
                last_error="max retries exceeded",
            )
        return False

    async def dispatch_batch(self, events: list[NotificationEvent]) -> None:
        """Dispatch multiple notification events."""
        for event in events:
            await self.dispatch(event)

    def get_status(self) -> dict:
        """Get notification manager status."""
        return {
            "enabled": self.config.enabled,
            "channels": [ch.name for ch in self._channels],
            "feishu_enabled": self.config.feishu_enabled,
            "email_enabled": self.config.email_enabled,
            "system_enabled": self.config.system_enabled,
            "quiet_hours": f"{self.config.quiet_start}:00-{self.config.quiet_end}:00 UTC+8",
            "queue_depth": len(self._queue),
            "worker_running": self._worker_task is not None and not self._worker_task.done(),
            "max_retries": self.config.max_retries,
            "retry_base_delay_s": self.config.retry_base_delay,
        }

    def get_failed_notifications(self) -> list[dict]:
        """Get list of notifications that failed after all retries (sync snapshot)."""
        # Sync snapshot of retry entries (avoids needing async context)
        entries = list(self._retry_entries.values())
        return [
            {
                "channel": entry.channel.name,
                "source": entry.event.source,
                "title": entry.event.title,
                "severity": entry.event.severity.value,
                "attempt": entry.attempt,
                "last_error": entry.last_error,
            }
            for entry in entries
        ]
