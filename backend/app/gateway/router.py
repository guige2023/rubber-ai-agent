"""
Gateway Router - Routes messages between platforms and the agent.
"""

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import uuid

from .session import SessionContext, PlatformIdentity
from .registry import get_registry, PlatformAdapter

logger = logging.getLogger(__name__)

# SQLite persistence for gateway sessions
GATEWAY_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS gateway_sessions (
    session_key TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    thread_id TEXT,
    bot_id TEXT,
    created_at TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    pending_content TEXT,
    metadata TEXT
)
"""

GATEWAY_PENDING_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS gateway_pending_runs (
    id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_key) REFERENCES gateway_sessions(session_key)
)
"""


class GatewaySessionStore:
    """SQLite-backed session store for gateway sessions with recovery support."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(GATEWAY_SESSIONS_TABLE)
            conn.execute(GATEWAY_PENDING_RUNS_TABLE)
            conn.commit()
        logger.info(f"Gateway session store initialized at {self.db_path}")

    def save_session(self, session_key: str, session: dict) -> None:
        """Save or update a session."""
        identity = session.get("identity")
        if identity is None:
            return

        pending_content = session.get("pending_content")

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO gateway_sessions
                (session_key, id, platform, user_id, chat_id, thread_id, bot_id,
                 created_at, last_activity, message_count, pending_content, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_key,
                session.get("id"),
                session.get("platform"),
                identity.user_id if hasattr(identity, "user_id") else identity.get("user_id", ""),
                identity.chat_id if hasattr(identity, "chat_id") else identity.get("chat_id", ""),
                identity.thread_id if hasattr(identity, "thread_id") else identity.get("thread_id"),
                identity.bot_id if hasattr(identity, "bot_id") else identity.get("bot_id"),
                session.get("created_at").isoformat() if isinstance(session.get("created_at"), datetime) else session.get("created_at"),
                session.get("last_activity").isoformat() if isinstance(session.get("last_activity"), datetime) else session.get("last_activity"),
                session.get("message_count", 0),
                json.dumps(pending_content) if pending_content else None,
                json.dumps(session.get("metadata", {})),
            ))
            conn.commit()

    def load_all_sessions(self) -> list[tuple[str, dict]]:
        """Load all sessions from database for recovery."""
        sessions = []
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM gateway_sessions")
            for row in cursor.fetchall():
                row_dict = dict(row)

                # Reconstruct identity
                identity = PlatformIdentity(
                    platform=row_dict["platform"],
                    user_id=row_dict["user_id"],
                    chat_id=row_dict["chat_id"],
                    thread_id=row_dict["thread_id"],
                    bot_id=row_dict["bot_id"],
                )

                # Parse timestamps
                created_at = datetime.fromisoformat(row_dict["created_at"])
                last_activity = datetime.fromisoformat(row_dict["last_activity"])

                session = {
                    "id": row_dict["id"],
                    "platform": row_dict["platform"],
                    "identity": identity,
                    "created_at": created_at,
                    "last_activity": last_activity,
                    "message_count": row_dict["message_count"],
                    "pending_content": json.loads(row_dict["pending_content"]) if row_dict["pending_content"] else None,
                    "metadata": json.loads(row_dict["metadata"]) if row_dict["metadata"] else {},
                }
                sessions.append((row_dict["session_key"], session))
        return sessions

    def delete_session(self, session_key: str) -> None:
        """Delete a session."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM gateway_pending_runs WHERE session_key = ?", (session_key,))
            conn.execute("DELETE FROM gateway_sessions WHERE session_key = ?", (session_key,))
            conn.commit()

    def save_pending_run(self, run_id: str, session_key: str, content: str, metadata: dict = None) -> None:
        """Save a pending run for later resumption."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO gateway_pending_runs
                (id, session_key, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (
                run_id,
                session_key,
                content,
                datetime.utcnow().isoformat(),
                json.dumps(metadata or {}),
            ))
            conn.commit()

    def get_pending_runs(self, session_key: str) -> list[dict]:
        """Get all pending runs for a session."""
        runs = []
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM gateway_pending_runs WHERE session_key = ? ORDER BY created_at",
                (session_key,)
            )
            for row in cursor.fetchall():
                runs.append({
                    "id": row["id"],
                    "session_key": row["session_key"],
                    "content": row["content"],
                    "created_at": datetime.fromisoformat(row["created_at"]),
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                })
        return runs

    def resolve_pending_run(self, run_id: str) -> None:
        """Remove a pending run after it's been processed."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM gateway_pending_runs WHERE id = ?", (run_id,))
            conn.commit()

    def get_all_pending_runs(self) -> list[dict]:
        """Get all pending runs across all sessions."""
        runs = []
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM gateway_pending_runs ORDER BY created_at")
            for row in cursor.fetchall():
                runs.append({
                    "id": row["id"],
                    "session_key": row["session_key"],
                    "content": row["content"],
                    "created_at": datetime.fromisoformat(row["created_at"]),
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                })
        return runs


@dataclass
class AgentResponse:
    """Response from the agent for a given session."""

    session_key: str
    content: str
    metadata: dict[str, Any] = None
    use_card: bool = False
    card_data: Optional[dict] = None


class GatewayRouter:
    """
    Central router that manages sessions and routes messages.

    The router:
    1. Receives messages from platform adapters
    2. Creates/retrieves session context
    3. Forwards to the agent for processing
    4. Routes the agent's response back to the correct platform
    5. Persists sessions to SQLite for recovery on restart
    6. Tracks pending runs for resume mechanism
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._registry = get_registry()
        self._sessions: dict[str, dict] = {}  # session_key -> session state
        self._agent_handler: Optional[Callable[[SessionContext], Awaitable[AgentResponse]]] = None
        self._lock = asyncio.Lock()

        # Initialize session store for SQLite persistence
        if db_path is None:
            from app.core.config import get_settings
            db_path = get_settings().user_dir / "gateway_sessions.db"
        self._session_store = GatewaySessionStore(db_path)
        self._pending_run_callbacks: list[Callable[[str, str, dict], Awaitable[None]]] = []  # (session_key, content, metadata)

    def set_agent_handler(
        self, handler: Callable[[SessionContext], Awaitable[AgentResponse]]
    ) -> None:
        """
        Set the handler that processes messages through the agent.

        The handler receives a SessionContext and returns an AgentResponse.
        """
        self._agent_handler = handler

    def register_pending_run_callback(self, callback: Callable[[str, str, dict], Awaitable[None]]) -> None:
        """
        Register a callback to be called when pending runs are resumed.

        Args:
            callback: async function(session_key, content, metadata)
        """
        self._pending_run_callbacks.append(callback)

    async def recover_sessions(self) -> list[str]:
        """
        Recover sessions from SQLite storage on startup.

        Returns:
            List of recovered session keys
        """
        recovered = []
        sessions = self._session_store.load_all_sessions()

        async with self._lock:
            for session_key, session in sessions:
                self._sessions[session_key] = session
                recovered.append(session_key)
                logger.info(f"Recovered session: {session_key}")

        if recovered:
            logger.info(f"Recovered {len(recovered)} sessions from SQLite")

        # Resume pending runs
        await self._resume_pending_runs()

        return recovered

    async def _resume_pending_runs(self) -> None:
        """Resume any pending runs that were interrupted."""
        pending_runs = self._session_store.get_all_pending_runs()

        for run in pending_runs:
            session_key = run["session_key"]
            content = run["content"]
            metadata = run["metadata"]
            run_id = run["id"]

            logger.info(f"Resuming pending run {run_id} for session {session_key}")

            # Notify callbacks about the pending run
            for callback in self._pending_run_callbacks:
                try:
                    await callback(session_key, content, metadata)
                except Exception as e:
                    logger.error(f"Error in pending run callback: {e}")

            # Remove from pending after processing
            self._session_store.resolve_pending_run(run_id)

    async def route_incoming(
        self,
        platform: str,
        event: dict,
        identity: PlatformIdentity,
    ) -> Optional[AgentResponse]:
        """
        Route an incoming message from a platform to the agent.

        Args:
            platform: Platform name (feishu, websocket, etc.)
            event: Raw platform event
            identity: Platform identity of the sender

        Returns:
            AgentResponse to be sent back to the platform
        """
        session_key = identity.session_key()

        # Create or retrieve session
        async with self._lock:
            if session_key not in self._sessions:
                self._sessions[session_key] = {
                    "id": str(uuid.uuid4()),
                    "platform": platform,
                    "identity": identity,
                    "created_at": datetime.utcnow(),
                    "last_activity": datetime.utcnow(),
                    "message_count": 0,
                }
                logger.info(f"Created new session: {session_key}")
            else:
                self._sessions[session_key]["last_activity"] = datetime.utcnow()

            session = self._sessions[session_key]

        # Persist session to SQLite
        try:
            self._session_store.save_session(session_key, session)
        except Exception as e:
            logger.error(f"Failed to persist session {session_key}: {e}")

        # Create session context
        session_ctx = SessionContext(
            id=session["id"],
            platform=platform,
            identity=identity,
            raw_event=event,
            metadata={"session_key": session_key},
        )

        # Extract content from event if not already set
        if not session_ctx.content and isinstance(event, dict):
            session_ctx.content = event.get("content", event.get("text", ""))

        # Increment message count
        session["message_count"] += 1

        # Process through agent
        if self._agent_handler:
            run_id = str(uuid.uuid4())
            try:
                response = await self._agent_handler(session_ctx)
                return response
            except Exception as e:
                logger.error(f"Agent handler error for {session_key}: {e}")
                # Save pending run for resume
                if session_ctx.content:
                    try:
                        self._session_store.save_pending_run(
                            run_id=run_id,
                            session_key=session_key,
                            content=session_ctx.content,
                            metadata={"error": str(e), "session_id": session["id"]},
                        )
                    except Exception as save_err:
                        logger.error(f"Failed to save pending run: {save_err}")
                return AgentResponse(
                    session_key=session_key,
                    content=f"Error processing request: {str(e)}",
                )
        else:
            logger.warning(f"No agent handler configured")
            return AgentResponse(
                session_key=session_key,
                content="Agent not configured",
            )

    async def route_response(self, response: AgentResponse) -> bool:
        """
        Route an agent response back to the appropriate platform.

        Args:
            response: AgentResponse to send

        Returns:
            True if sent successfully
        """
        session_key = response.session_key

        # Get session
        async with self._lock:
            session = self._sessions.get(session_key)
            if not session:
                logger.error(f"Session not found: {session_key}")
                return False

        platform = session["platform"]
        identity = session["identity"]
        adapter = self._registry.get(platform)

        if not adapter:
            logger.error(f"Platform adapter not found: {platform}")
            return False

        try:
            if response.use_card and response.card_data:
                message_id = await adapter.send_card(
                    chat_id=identity.chat_id,
                    card=response.card_data,
                )
            else:
                message_id = await adapter.send_message(
                    chat_id=identity.chat_id,
                    content=response.content,
                )

            if message_id:
                logger.debug(f"Sent response to {session_key}")
                return True
            else:
                logger.error(f"Failed to send response to {session_key}")
                return False

        except Exception as e:
            logger.error(f"Error routing response: {e}")
            return False

    async def get_session(self, session_key: str) -> Optional[dict]:
        """Get session info by key."""
        return self._sessions.get(session_key)

    async def list_sessions(self) -> list[dict]:
        """List all active sessions."""
        return list(self._sessions.values())

    async def close_session(self, session_key: str) -> bool:
        """Close and remove a session."""
        async with self._lock:
            if session_key in self._sessions:
                del self._sessions[session_key]
                logger.info(f"Closed session: {session_key}")
                # Remove from SQLite
                try:
                    self._session_store.delete_session(session_key)
                except Exception as e:
                    logger.error(f"Failed to delete session from SQLite: {e}")
                return True
            return False

    async def cleanup_stale_sessions(self, max_age_seconds: int = 3600) -> int:
        """
        Remove sessions with no activity beyond max_age_seconds.

        Returns:
            Number of sessions removed
        """
        now = datetime.utcnow()
        to_remove = []

        async with self._lock:
            for key, session in self._sessions.items():
                last_activity = session["last_activity"]
                age = (now - last_activity).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(key)

            for key in to_remove:
                del self._sessions[key]
                # Also delete from SQLite to prevent recovery on restart
                self._session_store.delete_session(key)

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} stale sessions")

        return len(to_remove)


# Global router instance
_global_router: Optional[GatewayRouter] = None


def get_router() -> GatewayRouter:
    """Get the global gateway router."""
    global _global_router
    if _global_router is None:
        _global_router = GatewayRouter()
    return _global_router
