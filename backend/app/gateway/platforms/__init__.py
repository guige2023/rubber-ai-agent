"""
Platform Adapters - Implementations for specific messaging platforms.
"""

from .base import BasePlatformAdapter, ChannelHealthMonitor, ChannelHealthStatus
from .feishu import FeishuAdapter
from .telegram import TelegramAdapter

__all__ = [
    "BasePlatformAdapter",
    "ChannelHealthMonitor",
    "ChannelHealthStatus",
    "FeishuAdapter",
    "TelegramAdapter",
]
