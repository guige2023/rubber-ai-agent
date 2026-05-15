"""
Platform Registry - Registers and discovers platform adapters.
"""

from abc import ABC, abstractmethod
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PlatformAdapter(ABC):
    """
    Base class for all platform adapters.

    Each platform (Feishu, Discord, etc.) implements this interface
    to send and receive messages through the Gateway.
    """

    name: str = "base"
    supports_streaming: bool = False

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection to the platform."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the platform."""
        pass

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """
        Send a message to a chat.

        Args:
            chat_id: Platform-specific chat/channel ID
            content: Message content
            msg_type: Message type (text, image, card, etc.)
            **kwargs: Platform-specific options

        Returns:
            Platform's message ID if successful, None otherwise.
        """
        pass

    @abstractmethod
    async def send_card(
        self,
        chat_id: str,
        card: dict,
        **kwargs,
    ) -> Optional[str]:
        """
        Send an interactive card message.

        Args:
            chat_id: Platform-specific chat/channel ID
            card: Card definition dict
            **kwargs: Platform-specific options

        Returns:
            Platform's message ID if successful, None otherwise.
        """
        pass

    async def format_for_platform(self, content: str, **kwargs) -> str:
        """
        Format content for this platform.

        Override to apply platform-specific formatting (length limits, etc.)
        """
        # Default: return as-is
        return content

    async def on_message(self, event: dict) -> Optional[dict]:
        """
        Handle an incoming platform event.

        Override to transform platform-specific event format to SessionContext.

        Returns:
            SessionContext-compatible dict or None to skip.
        """
        return event


class PlatformRegistry:
    """
    Global registry of platform adapters.

    Usage:
        registry = PlatformRegistry()
        registry.register(FeishuAdapter())
        adapter = registry.get("feishu")
    """

    def __init__(self):
        self._adapters: dict[str, PlatformAdapter] = {}
        self._connected: set[str] = set()

    def register(self, adapter: PlatformAdapter) -> None:
        """Register a platform adapter."""
        if adapter.name in self._adapters:
            logger.warning(f"Platform '{adapter.name}' already registered, overwriting")
        self._adapters[adapter.name] = adapter
        logger.info(f"Registered platform adapter: {adapter.name}")

    def unregister(self, name: str) -> None:
        """Unregister a platform adapter."""
        if name in self._adapters:
            del self._adapters[name]
            self._connected.discard(name)
            logger.info(f"Unregistered platform adapter: {name}")

    def get(self, name: str) -> Optional[PlatformAdapter]:
        """Get a platform adapter by name."""
        return self._adapters.get(name)

    def get_connected(self) -> list[str]:
        """Get list of connected platform names."""
        return list(self._connected)

    def list_platforms(self) -> list[str]:
        """List all registered platform names."""
        return list(self._adapters.keys())

    async def connect_all(self) -> None:
        """Connect all registered adapters."""
        for name, adapter in self._adapters.items():
            try:
                await adapter.connect()
                self._connected.add(name)
                logger.info(f"Connected platform: {name}")
            except Exception as e:
                logger.error(f"Failed to connect platform '{name}': {e}")

    async def disconnect_all(self) -> None:
        """Disconnect all connected adapters."""
        for name in list(self._connected):
            adapter = self._adapters.get(name)
            if adapter:
                try:
                    await adapter.disconnect()
                    logger.info(f"Disconnected platform: {name}")
                except Exception as e:
                    logger.error(f"Error disconnecting platform '{name}': {e}")
        self._connected.clear()


# Global registry instance
_global_registry: Optional[PlatformRegistry] = None


def get_registry() -> PlatformRegistry:
    """Get the global platform registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = PlatformRegistry()
    return _global_registry


def register_platform(adapter: PlatformAdapter) -> None:
    """Register a platform adapter to the global registry."""
    get_registry().register(adapter)


def get_platform(name: str) -> Optional[PlatformAdapter]:
    """Get a platform adapter from the global registry."""
    return get_registry().get(name)
