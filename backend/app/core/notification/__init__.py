"""Notification system for proactive user alerts."""

from app.core.notification.events import NotificationEvent, NotificationSeverity
from app.core.notification.manager import NotificationManager
from app.core.notification.channels import NotificationChannel

__all__ = [
    "NotificationEvent",
    "NotificationSeverity",
    "NotificationManager",
    "NotificationChannel",
]
