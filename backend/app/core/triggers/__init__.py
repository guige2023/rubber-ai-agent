"""
Triggers package - various trigger implementations.
"""
from .webhook_handler import WebhookTrigger, WebhookConfig

__all__ = ["WebhookTrigger", "WebhookConfig"]
