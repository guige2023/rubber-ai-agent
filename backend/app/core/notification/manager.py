"""NotificationManager - central dispatcher for all notification channels."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core.notification.events import NotificationEvent, NotificationSeverity
from app.core.notification.channels.base import NotificationChannel
from app.core.notification.channels.feishu import FeishuNotifier
from app.core.notification.channels.email import EmailNotifier

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


class NotificationManager:
    """
    Central notification dispatcher.

    Routes NotificationEvents to the appropriate channels (Feishu, Email, etc.)
    based on severity and configuration. Handles deduplication and quiet hours.
    """

    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        self.config = config or NotificationConfig()
        self._channels: list[NotificationChannel] = []
        self._dedupe: dict[_DedupeKey, float] = {}
        self._dedupe_ttl_seconds = 300  # 5 minutes

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

        Args:
            event: The notification event to send.
        """
        if not self._should_deliver(event):
            logger.debug(f"[NotificationManager] Dropping notification: {event.title} ({event.severity.value})")
            return

        if self._is_dupe(event):
            logger.debug(f"[NotificationManager] Dedupe: {event.title}")
            return

        logger.info(f"[NotificationManager] Dispatching: [{event.severity.value}] {event.title}")

        # Send to all channels in parallel
        tasks = []
        for channel in self._channels:
            if event.severity == NotificationSeverity.CRITICAL:
                tasks.append(channel.send_critical(event))
            elif event.severity == NotificationSeverity.WARNING:
                tasks.append(channel.send_warning(event))
            else:
                tasks.append(channel.send_info(event))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for channel, result in zip(self._channels, results):
                if isinstance(result, Exception):
                    logger.warning(f"[{channel.name}] Exception: {result}")

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
            "quiet_hours": f"{self.config.quiet_start}:00-{self.config.quiet_end}:00 UTC+8",
        }
