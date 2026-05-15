"""
Gateway Module - Multi-platform message routing layer.

Provides unified session management and message routing for multiple
messaging platforms (Feishu, WebSocket, etc.).
"""

from .session import SessionContext, PlatformIdentity
from .router import GatewayRouter, get_router
from .registry import PlatformRegistry, PlatformAdapter, get_registry

__all__ = [
    "SessionContext",
    "PlatformIdentity",
    "GatewayRouter",
    "get_router",
    "get_registry",
    "PlatformRegistry",
    "PlatformAdapter",
]
