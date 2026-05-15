"""
TUI Gateway Client - WebSocket client for connecting to the RabAi backend.

This provides the same function as OpenCLAW's GatewayChatClient,
connecting to the backend via WebSocket for remote operation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import websockets

from app.models.events import RabAiAgentEventEnvelope

logger = logging.getLogger(__name__)


@dataclass
class TuiEvent:
    """Event received from the gateway."""

    namespace: str
    event: str
    session_id: Optional[str] = None
    payload: Any = None


@dataclass
class SessionInfo:
    """Session information."""

    id: str
    title: str
    updated_at: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TuiGatewayClient:
    """
    WebSocket client for the TUI to connect to the RabAi backend.

    This mirrors OpenCLAW's GatewayChatClient functionality.
    """

    url: str
    token: str
    _ws: Optional[websockets.WebSocketClientProtocol] = None
    _reader_task: Optional[asyncio.Task] = None
    _pending_calls: dict[int, asyncio.Future] = field(default_factory=dict)
    _event_handlers: list[Callable[[TuiEvent], None]] = field(default_factory=list)
    _id_counter: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.open

    async def connect(self) -> None:
        """Connect to the gateway."""
        if self.is_connected:
            return

        headers = []
        url_with_token = f"{self.url}?access_token={self.token}"

        self._ws = await websockets.connect(url_with_token, extra_headers=headers)
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info(f"TUI connected to {self.url}")

    async def disconnect(self) -> None:
        """Disconnect from the gateway."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        # Reject all pending calls
        async with self._lock:
            for future in self._pending_calls.values():
                if not future.done():
                    future.set_exception(Exception("Disconnected"))
            self._pending_calls.clear()

    async def _read_loop(self) -> None:
        """Read messages from the WebSocket."""
        try:
            async for message in self._ws:  # type: ignore
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"TUI gateway read error: {e}")

    async def _handle_message(self, raw_message: str) -> None:
        """Handle incoming message."""
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from gateway: {raw_message[:100]}")
            return

        # Check if it's a response to a pending call
        if "id" in data and data["id"] in self._pending_calls:
            future = self._pending_calls.pop(data["id"])
            if "error" in data:
                future.set_exception(Exception(data["error"].get("message", "Unknown error")))
            else:
                future.set_result(data.get("result"))
            return

        # Check if it's an event notification
        if "method" in data and data.get("method") == "rabaiagent_event":
            params = data.get("params", {})
            event = TuiEvent(
                namespace=params.get("namespace", ""),
                event=params.get("event", ""),
                session_id=params.get("session_id"),
                payload=params.get("payload"),
            )
            for handler in self._event_handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request and wait for response."""
        if not self.is_connected:
            raise Exception("Not connected to gateway")

        async with self._lock:
            self._id_counter += 1
            request_id = self._id_counter

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()

        async with self._lock:
            self._pending_calls[request_id] = future

        try:
            await self._ws.send(json.dumps(request))  # type: ignore
            result = await asyncio.wait_for(future, timeout=60.0)
            return result
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending_calls.pop(request_id, None)
            raise Exception("Request timed out")

    def on_event(self, handler: Callable[[TuiEvent], None]) -> None:
        """Register an event handler."""
        self._event_handlers.append(handler)

    # ── Gateway Methods ──────────────────────────────────────────────

    async def execute(self, instruction: str, session_id: str) -> dict[str, Any]:
        """Execute an instruction in a session."""
        return await self._send_request("execute", {
            "instruction": instruction,
            "session_id": session_id,
        })

    async def cancel_run(self, run_id: str, session_id: Optional[str] = None) -> dict[str, Any]:
        """Cancel a running operation."""
        params = {"run_id": run_id}
        if session_id:
            params["session_id"] = session_id
        return await self._send_request("cancel_run", params)

    async def list_sessions(self) -> list[SessionInfo]:
        """List all sessions."""
        result = await self._send_request("list_sessions", {})
        sessions = []
        for s in result.get("sessions", []):
            sessions.append(SessionInfo(
                id=s.get("id", ""),
                title=s.get("title", "Untitled"),
                updated_at=s.get("updated_at", ""),
                input_tokens=s.get("input_tokens", 0),
                output_tokens=s.get("output_tokens", 0),
            ))
        return sessions

    async def create_session(self, title: Optional[str] = None) -> SessionInfo:
        """Create a new session."""
        params = {}
        if title:
            params["title"] = title
        result = await self._send_request("create_session", params)
        s = result.get("session", {})
        return SessionInfo(
            id=s.get("id", ""),
            title=s.get("title", "Untitled"),
            updated_at=s.get("updated_at", ""),
        )

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        await self._send_request("delete_session", {"session_id": session_id})

    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get messages for a session."""
        result = await self._send_request("get_session_messages", {
            "session_id": session_id,
            "limit": limit,
        })
        return result.get("messages", [])

    async def list_tasks(self) -> list[dict[str, Any]]:
        """List all tasks."""
        result = await self._send_request("list_tasks", {})
        return result.get("tasks", [])

    async def get_system_status(self) -> dict[str, Any]:
        """Get system status."""
        return await self._send_request("system.status", {})
