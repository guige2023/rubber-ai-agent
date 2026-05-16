"""
P1-MON-2: Activity Log Persistent Storage

Tracks agent operations (tool calls, message exchanges, task events) in a
SQLite table for historical querying and error tracing.

Based on Paperclip's activity-log.ts design.

Usage:
    from app.core.monitoring import activity_log

    await activity_log.log(
        action="tool_call",
        agent_id="agent_1",
        details={"tool": "web_search", "query": "..."},
    )

    # Query logs
    logs = await activity_log.query(limit=50, action="tool_call")
"""

from __future__ import annotations

import asyncio
import logging
import shortuuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlmodel import Field, JSON, SQLModel

logger = logging.getLogger(__name__)


# ── Database Model ─────────────────────────────────────────────────────────

class ActivityLogModel(SQLModel, table=True):
    __tablename__ = "activity_logs"

    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # Who
    actor_type: str = Field(default="agent")  # "agent" | "user" | "system"
    actor_id: str = Field(default="default")
    # What
    action: str = Field(index=True)  # "tool_call" | "message_sent" | "task_created" | ...
    entity_type: Optional[str] = Field(default=None)  # "session" | "task" | "skill"
    entity_id: Optional[str] = Field(default=None, index=True)
    # Context
    agent_id: Optional[str] = Field(default=None)
    run_id: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    # Details
    details: dict[str, Any] = Field(default_factory=dict, sa_column=JSON)
    # Result
    success: bool = Field(default=True)
    error_message: Optional[str] = Field(default=None)


# ── Schema ─────────────────────────────────────────────────────────────────

class ActionType(str, Enum):
    # Session events
    SESSION_CREATED = "session_created"
    SESSION_DELETED = "session_deleted"
    SESSION_UPDATED = "session_updated"
    # Message events
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_TOOL_CALL = "message_tool_call"
    MESSAGE_TOOL_RESULT = "message_tool_result"
    # Task events
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    # Skill events
    SKILL_CREATED = "skill_created"
    SKILL_UPDATED = "skill_updated"
    SKILL_INVOKED = "skill_invoked"
    # Evolution events
    EVOLUTION_SIGNAL = "evolution_signal"
    EVOLUTION_APPLIED = "evolution_applied"
    # System events
    HEALTH_CHECK = "health_check"
    GATEWAY_RESTART = "gateway_restart"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


@dataclass
class ActivityEntry:
    """Structured input for activity logging."""
    action: str
    actor_type: str = "agent"
    actor_id: str = "default"
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None


# ── Service ────────────────────────────────────────────────────────────────

class ActivityLogService:
    """
    Async service for writing and querying activity logs.

    Uses a bounded queue to batch writes and avoid blocking the caller.
    """

    _instance: "ActivityLogService | None" = None

    @classmethod
    def get_instance(cls) -> "ActivityLogService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, max_queue_size: int = 200, batch_size: int = 20):
        self._queue: asyncio.Queue[ActivityEntry] = asyncio.Queue(maxsize=max_queue_size)
        self._batch_size = batch_size
        self._worker_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("ActivityLogService started")

    async def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        # Drain remaining items
        await self._flush()
        logger.info("ActivityLogService stopped")

    async def log(self, entry: ActivityEntry) -> None:
        """Enqueue an activity entry for async persistence."""
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            logger.warning("Activity log queue full, dropping entry")
            # Still log the most recent one
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(entry)
            except Exception:
                pass

    # ── Convenience helpers ────────────────────────────────────────────────

    async def log_session_created(self, session_id: str, title: str = "") -> None:
        await self.log(ActivityEntry(
            action=ActionType.SESSION_CREATED.value,
            entity_type="session",
            entity_id=session_id,
            session_id=session_id,
            details={"title": title},
        ))

    async def log_tool_call(
        self,
        tool_name: str,
        session_id: str,
        run_id: str,
        agent_id: str = "default",
        args: Optional[dict] = None,
    ) -> None:
        await self.log(ActivityEntry(
            action=ActionType.TOOL_CALL.value,
            actor_type="agent",
            actor_id=agent_id,
            entity_type="tool",
            entity_id=tool_name,
            agent_id=agent_id,
            run_id=run_id,
            session_id=session_id,
            details={"tool": tool_name, "args": args or {}},
        ))

    async def log_tool_result(
        self,
        tool_name: str,
        session_id: str,
        run_id: str,
        success: bool,
        error_message: Optional[str] = None,
        result_summary: Optional[str] = None,
    ) -> None:
        await self.log(ActivityEntry(
            action=ActionType.TOOL_RESULT.value if success else ActionType.TOOL_ERROR.value,
            entity_type="tool",
            entity_id=tool_name,
            run_id=run_id,
            session_id=session_id,
            details={"tool": tool_name, "summary": result_summary},
            success=success,
            error_message=error_message,
        ))

    async def log_task_completed(
        self,
        task_id: str,
        session_id: str,
        duration_seconds: Optional[float] = None,
    ) -> None:
        await self.log(ActivityEntry(
            action=ActionType.TASK_COMPLETED.value,
            entity_type="task",
            entity_id=task_id,
            session_id=session_id,
            details={"duration_s": duration_seconds},
        ))

    async def log_evolution_signal(
        self,
        signal_type: str,
        confidence: float,
        session_id: str,
    ) -> None:
        await self.log(ActivityEntry(
            action=ActionType.EVOLUTION_SIGNAL.value,
            entity_type="evolution",
            session_id=session_id,
            details={"signal_type": signal_type, "confidence": confidence},
        ))

    # ── Query ────────────────────────────────────────────────────────────

    async def query(
        self,
        action: Optional[str] = None,
        session_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityLogModel]:
        """Query activity logs from the database."""
        from sqlmodel import select

        from app.core.db import get_session

        with get_session() as db:
            stmt = select(ActivityLogModel)

            if action:
                stmt = stmt.where(ActivityLogModel.action == action)
            if session_id:
                stmt = stmt.where(ActivityLogModel.session_id == session_id)
            if entity_id:
                stmt = stmt.where(ActivityLogModel.entity_id == entity_id)
            if run_id:
                stmt = stmt.where(ActivityLogModel.run_id == run_id)

            stmt = stmt.order_by(ActivityLogModel.timestamp.desc())
            stmt = stmt.offset(offset).limit(limit)

            return list(db.exec(stmt).all())

    # ── Internal worker ──────────────────────────────────────────────────

    async def _worker(self) -> None:
        """Background worker that batches inserts."""
        while self._running:
            try:
                batch: list[ActivityEntry] = []
                # Wait for first item
                entry = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                batch.append(entry)

                # Drain up to batch_size - 1 more
                while len(batch) < self._batch_size:
                    try:
                        entry = self._queue.get_nowait()
                        batch.append(entry)
                    except asyncio.QueueEmpty:
                        break

                await self._flush_batch(batch)

            except asyncio.TimeoutError:
                # No activity for 2s — flush whatever we have
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"ActivityLog worker error: {e}")

    async def _flush_batch(self, entries: list[ActivityEntry]) -> None:
        """Write a batch of entries to the DB."""
        from app.core.db import get_session

        if not entries:
            return

        try:
            with get_session() as db:
                for entry in entries:
                    record = ActivityLogModel(
                        timestamp=datetime.now(timezone.utc),
                        actor_type=entry.actor_type,
                        actor_id=entry.actor_id,
                        action=entry.action,
                        entity_type=entry.entity_type,
                        entity_id=entry.entity_id,
                        agent_id=entry.agent_id,
                        run_id=entry.run_id,
                        session_id=entry.session_id,
                        details=entry.details,
                        success=entry.success,
                        error_message=entry.error_message,
                    )
                    db.add(record)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to flush activity log batch: {e}")

    async def _flush(self) -> None:
        """Drain the queue and flush to DB."""
        entries = []
        while not self._queue.empty():
            try:
                entries.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if entries:
            await self._flush_batch(entries)


# ── Global singleton ───────────────────────────────────────────────────────

activity_log = ActivityLogService.get_instance()
