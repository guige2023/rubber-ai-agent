"""Abstract notification channel interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from app.core.notification.events import NotificationEvent

logger = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """Base class for notification channels."""

    name: str

    @abstractmethod
    async def send(self, event: NotificationEvent) -> bool:
        """
        Send a notification event through this channel.

        Returns True if sent successfully, False otherwise.
        """
        ...

    async def send_critical(self, event: NotificationEvent) -> bool:
        """Send a CRITICAL notification — override for emergency channels."""
        return await self.send(event)

    async def send_warning(self, event: NotificationEvent) -> bool:
        """Send a WARNING notification — override if channel should filter these."""
        return await self.send(event)

    async def send_info(self, event: NotificationEvent) -> bool:
        """Send an INFO notification — override if channel should filter these."""
        return await self.send(event)

    def _log_result(self, event: NotificationEvent, success: bool, error: str | None = None) -> None:
        status = "OK" if success else f"FAIL ({error})"
        logger.info(f"[{self.name}] {status} | {event.severity.value} | {event.title}")
