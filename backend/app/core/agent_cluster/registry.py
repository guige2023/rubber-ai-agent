"""
Agent Registry - Register and discover agents in the cluster.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .base import BaseAgent

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent lifecycle status."""
    REGISTERED = "registered"
    INITIALIZING = "initializing"
    RUNNING = "running"
    IDLE = "idle"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class AgentMetadata:
    """Metadata for a registered agent."""
    name: str
    description: str
    version: str = "1.0.0"
    status: AgentStatus = AgentStatus.REGISTERED
    heartbeat_interval: str = "5m"  # e.g., "5m", "1h", "30s"
    heartbeat_tasks: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    last_heartbeat: Optional[datetime] = None
    last_active: Optional[datetime] = None
    error_count: int = 0
    total_invocations: int = 0


class AgentRegistry:
    """
    Registry for managing agent registration and discovery.

    Agents register themselves with metadata, and other components
    can discover them through the registry.
    """

    def __init__(self) -> None:
        self._agents: dict[str, tuple[BaseAgent, AgentMetadata]] = {}
        self._lock = asyncio.Lock()
        self._status_callbacks: list[callable] = []

    def register(
        self,
        agent: BaseAgent,
        metadata: AgentMetadata,
    ) -> None:
        """Register an agent with its metadata."""
        if metadata.name in self._agents:
            logger.warning(f"Agent {metadata.name} already registered, replacing")

        self._agents[metadata.name] = (agent, metadata)
        logger.info(f"Registered agent: {metadata.name} ({metadata.description})")

    def unregister(self, name: str) -> bool:
        """Unregister an agent by name."""
        if name in self._agents:
            del self._agents[name]
            logger.info(f"Unregistered agent: {name}")
            return True
        return False

    def get(self, name: str) -> Optional[tuple[BaseAgent, AgentMetadata]]:
        """Get an agent and its metadata by name."""
        return self._agents.get(name)

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Get an agent by name."""
        pair = self._agents.get(name)
        return pair[0] if pair else None

    def get_metadata(self, name: str) -> Optional[AgentMetadata]:
        """Get agent metadata by name."""
        pair = self._agents.get(name)
        return pair[1] if pair else None

    def list_agents(self) -> list[AgentMetadata]:
        """List all registered agent metadata."""
        return [meta for _, meta in self._agents.values()]

    def list_by_capability(self, capability: str) -> list[AgentMetadata]:
        """Find agents with a specific capability."""
        return [
            meta
            for _, meta in self._agents.values()
            if capability in meta.capabilities
        ]

    async def update_status(
        self,
        name: str,
        status: AgentStatus,
        error_count: Optional[int] = None,
    ) -> None:
        """Update agent status and notify callbacks."""
        old_status = None
        async with self._lock:
            if name not in self._agents:
                logger.debug(f"Agent {name} not registered yet, skipping status update")
                return

            _, metadata = self._agents[name]
            old_status = metadata.status
            metadata.status = status

            if error_count is not None:
                metadata.error_count = error_count

            if status in (AgentStatus.RUNNING, AgentStatus.IDLE):
                metadata.last_active = datetime.utcnow()

            if old_status != status:
                logger.info(f"Agent {name} status: {old_status.value} -> {status.value}")

        # Notify callbacks outside the lock to avoid deadlock
        if old_status is not None and old_status != status:
            await self._notify_status_change(name, old_status, status)

    async def update_heartbeat(self, name: str) -> None:
        """Update last heartbeat timestamp."""
        if name in self._agents:
            _, metadata = self._agents[name]
            metadata.last_heartbeat = datetime.utcnow()

    async def increment_invocations(self, name: str) -> None:
        """Increment invocation counter."""
        if name in self._agents:
            _, metadata = self._agents[name]
            metadata.total_invocations += 1
            metadata.last_active = datetime.utcnow()

    def on_status_change(self, callback: callable) -> None:
        """Register a status change callback."""
        self._status_callbacks.append(callback)

    async def _notify_status_change(
        self,
        name: str,
        old_status: AgentStatus,
        new_status: AgentStatus,
    ) -> None:
        """Notify all registered callbacks of status change."""
        for callback in self._status_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(name, old_status, new_status)
                else:
                    callback(name, old_status, new_status)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")


# Global registry instance
_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
