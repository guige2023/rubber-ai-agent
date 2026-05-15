"""
Agent Communication Protocol - Messages between agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .registry import get_registry

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Agent message types."""
    INVOKE = "invoke"           # Request agent to perform task
    RESPONSE = "response"       # Response to invoke
    EVENT = "event"             # Async event notification
    HEARTBEAT = "heartbeat"     # Heartbeat ping
    REGISTER = "register"        # Registration request
    UNREGISTER = "unregister"   # Unregistration request


@dataclass
class AgentMessage:
    """Message sent between agents."""
    id: str
    type: MessageType
    source: str                    # Sender agent name
    target: str                    # Recipient agent name (or "*" for broadcast)
    payload: dict[str, Any]
    correlation_id: Optional[str] = None  # For request/response matching
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 300         # Message TTL

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps({
            "id": self.id,
            "type": self.type.value,
            "source": self.source,
            "target": self.target,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        })

    @classmethod
    def from_json(cls, data: str) -> AgentMessage:
        """Deserialize from JSON."""
        d = json.loads(data)
        return cls(
            id=d["id"],
            type=MessageType(d["type"]),
            source=d["source"],
            target=d["target"],
            payload=d["payload"],
            correlation_id=d.get("correlation_id"),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            ttl_seconds=d.get("ttl_seconds", 300),
        )


class MessageRouter:
    """
    Routes messages between agents.

    Supports:
    - Direct point-to-point messages
    - Broadcast messages (target="*")
    - Pub/sub patterns via event topics
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._registry = get_registry()

    def subscribe(self, agent_name: str, queue: asyncio.Queue) -> None:
        """Subscribe an agent to receive messages."""
        self._queues[agent_name] = queue

    def unsubscribe(self, agent_name: str) -> None:
        """Unsubscribe an agent."""
        if agent_name in self._queues:
            del self._queues[agent_name]

    def register_handler(
        self,
        message_type: MessageType,
        handler: Callable[[AgentMessage], Any],
    ) -> None:
        """Register a handler for a message type."""
        key = message_type.value
        if key not in self._handlers:
            self._handlers[key] = []
        self._handlers[key].append(handler)

    async def send(self, message: AgentMessage) -> bool:
        """
        Send a message to target agent(s).

        Returns True if delivered.
        """
        try:
            # Direct message
            if message.target != "*":
                queue = self._queues.get(message.target)
                if queue:
                    await queue.put(message)
                    return True
                else:
                    logger.warning(f"No queue for agent: {message.target}")
                    return False

            # Broadcast
            delivered = 0
            for agent_name, queue in self._queues.items():
                if agent_name != message.source:  # Don't send to self
                    await queue.put(message)
                    delivered += 1

            logger.debug(f"Broadcast to {delivered} agents")
            return delivered > 0

        except Exception as e:
            logger.error(f"Message send error: {e}")
            return False

    async def invoke(
        self,
        source: str,
        target: str,
        payload: dict[str, Any],
        timeout: float = 30.0,
    ) -> Optional[dict[str, Any]]:
        """
        Invoke an agent and wait for response.

        Args:
            source: Calling agent name
            target: Target agent name
            payload: Request payload
            timeout: Response timeout in seconds

        Returns:
            Response payload or None on timeout
        """
        import uuid

        correlation_id = str(uuid.uuid4())
        response_queue: asyncio.Queue = asyncio.Queue()

        # Create request message
        request = AgentMessage(
            id=str(uuid.uuid4()),
            type=MessageType.INVOKE,
            source=source,
            target=target,
            payload=payload,
            correlation_id=correlation_id,
        )

        # Create temporary subscription for response
        self._queues[f"_response_{correlation_id}"] = response_queue

        try:
            # Send request
            await self.send(request)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(
                    response_queue.get(),
                    timeout=timeout,
                )
                return response.payload
            except asyncio.TimeoutError:
                logger.warning(f"Invoke timeout: {source} -> {target}")
                return None

        finally:
            # Cleanup temporary subscription
            self.unsubscribe(f"_response_{correlation_id}")

    async def broadcast_event(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Broadcast an event to all agents."""
        import uuid

        message = AgentMessage(
            id=str(uuid.uuid4()),
            type=MessageType.EVENT,
            source=source,
            target="*",
            payload={
                "event_type": event_type,
                **payload,
            },
        )
        await self.send(message)


class AgentProtocol:
    """
    Protocol handler for agent communication.

    Provides high-level operations:
    - call(): Invoke another agent
    - emit(): Emit an event
    - reply(): Send response to invoke
    """

    def __init__(self, agent_name: str, router: MessageRouter) -> None:
        self._agent_name = agent_name
        self._router = router
        self._inbox: asyncio.Queue = asyncio.Queue()

        # Subscribe to messages
        self._router.subscribe(agent_name, self._inbox)

    async def call(
        self,
        target: str,
        action: str,
        params: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Optional[dict[str, Any]]:
        """
        Call another agent and get response.

        Args:
            target: Agent name
            action: Action to invoke
            params: Action parameters
            timeout: Response timeout

        Returns:
            Response or None
        """
        return await self._router.invoke(
            source=self._agent_name,
            target=target,
            payload={
                "action": action,
                "params": params or {},
            },
            timeout=timeout,
        )

    async def emit(
        self,
        event_type: str,
        **kwargs: Any,
    ) -> None:
        """
        Emit an event to all agents.
        """
        await self._router.broadcast_event(
            source=self._agent_name,
            event_type=event_type,
            payload=kwargs,
        )

    async def reply(
        self,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Send response to an invoke.

        Args:
            correlation_id: Correlation ID from request
            payload: Response payload
        """
        import uuid

        message = AgentMessage(
            id=str(uuid.uuid4()),
            type=MessageType.RESPONSE,
            source=self._agent_name,
            target=f"_response_{correlation_id}",
            payload=payload,
            correlation_id=correlation_id,
        )
        await self._router.send(message)

    async def receive(self) -> Optional[AgentMessage]:
        """
        Receive next message from inbox.

        Returns None if no message available.
        """
        try:
            return self._inbox.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def process_messages(self) -> None:
        """
        Process incoming messages continuously.

        Should be run as a background task.
        """
        while True:
            try:
                message = await self._inbox.get()
                await self._handle_message(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Message processing error: {e}")

    async def _handle_message(self, message: AgentMessage) -> None:
        """Handle incoming message."""
        if message.type == MessageType.INVOKE:
            logger.info(f"{self._agent_name} received invoke: {message.payload}")
            # Subclass should override to handle invokes

        elif message.type == MessageType.EVENT:
            logger.debug(f"{self._agent_name} received event: {message.payload}")

        elif message.type == MessageType.HEARTBEAT:
            await self.reply(message.correlation_id, {"status": "ok"})


# Global router instance
_router: Optional[MessageRouter] = None


def get_router() -> MessageRouter:
    """Get the global message router."""
    global _router
    if _router is None:
        _router = MessageRouter()
    return _router
