"""Notification channel interface."""

from app.core.notification.channels.base import NotificationChannel
from app.core.notification.channels.feishu import FeishuNotifier
from app.core.notification.channels.email import EmailNotifier
from app.core.notification.channels.system import SystemNotifier

__all__ = [
    "NotificationChannel",
    "FeishuNotifier",
    "EmailNotifier",
    "SystemNotifier",
]
