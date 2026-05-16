"""
P1-EVOL-2: FailureLearningEngine

Tracks failure patterns across agent runs and surfaces learned
avoidances so future similar situations are handled proactively.

Based on Hermes-style "learn from mistakes, never repeat" principle.

Usage:
    engine = FailureLearningEngine()
    await engine.record_failure(
        session_id="sess_123",
        tool_name="web_search",
        error="rate limit exceeded",
        context={"query": "..."},
    )
    avoidances = engine.get_avoidances()
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Field, JSON, SQLModel

logger = logging.getLogger(__name__)


# ── Database Model ─────────────────────────────────────────────────────────

class FailureRecordModel(SQLModel, table=True):
    __tablename__ = "failure_records"

    id: str = Field(primary_key=True)
    timestamp: datetime = Field(index=True)
    tool_name: str = Field(index=True)
    error_type: str = Field(index=True)  # e.g. "rate_limit", "auth", "timeout"
    error_message: str
    session_id: Optional[str] = Field(default=None, index=True)
    run_id: Optional[str] = Field(default=None)
    context: dict = Field(default_factory=dict, sa_column=JSON)
    frequency: int = Field(default=1)  # How many times this pattern occurred
    last_seen: datetime = Field(index=True)
    # Avoidance: set once we've learned how to handle this
    avoidance_note: Optional[str] = Field(default=None)
    is_resolved: bool = Field(default=False)


# ── Patterns ──────────────────────────────────────────────────────────────

# Canonical error type patterns (matched in order)
_ERROR_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("rate_limit", re.compile(r"rate.?limit|429|too.?many.?requests|backoff", re.I)),
    ("auth", re.compile(r"auth|401|403|unauthorized|invalid.?token|permission.?denied", re.I)),
    ("timeout", re.compile(r"timeout|timed.?out|504|gateway.?timeout|connection.?reset", re.I)),
    ("not_found", re.compile(r"404|not.?found|does.?not.?exist|no.?such", re.I)),
    ("network", re.compile(r"network|dns|connection.?refused|ECONNREFUSED|ssl", re.I)),
    ("validation", re.compile(r"validation|invalid|malformed|400|bad.?request", re.I)),
    ("server_error", re.compile(r"500|502|503|internal.?error|server.?error", re.I)),
    ("quota", re.compile(r"quota|limit.?exceeded|insufficient|credit|balance", re.I)),
    ("rate_limit", re.compile(r"retry|after|retry.?after", re.I)),
]


@dataclass
class FailurePattern:
    """A recurring failure pattern with learned avoidance."""
    error_type: str
    tool_name: Optional[str]
    count: int
    last_seen: datetime
    avoidance_note: Optional[str] = None
    is_resolved: bool = False


# ── Service ────────────────────────────────────────────────────────────────

class FailureLearningEngine:
    """
    Records, clusters, and learns from agent tool failures.

    Key methods:
    - record_failure(): Log a failure event
    - get_avoidances(): Get all learned avoidances
    - get_pattern(): Get the dominant pattern for a tool
    - check_would_retry(): Should we retry based on past failures?
    """

    _instance: "FailureLearningEngine | None" = None

    @classmethod
    def get_instance(cls) -> "FailureLearningEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        self._cache: dict[str, FailurePattern] = {}
        self._cache_loaded = False

    # ── Public API ───────────────────────────────────────────────────────

    async def record_failure(
        self,
        tool_name: str,
        error_message: str,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        context: Optional[dict] = None,
        avoidance_note: Optional[str] = None,
    ) -> None:
        """
        Record a failure event and update pattern statistics.

        Args:
            tool_name: Name of the tool that failed
            error_message: Raw error message
            session_id: Session in which the failure occurred
            run_id: Run ID
            context: Additional context (query, params, etc.)
            avoidance_note: If known, the workaround for this failure
        """
        error_type = self._classify_error(error_message)

        # Check if similar failure already recorded (same type + tool, last 24h)
        existing = await self._find_similar(
            error_type=error_type,
            tool_name=tool_name,
            within_hours=24,
        )

        now = datetime.now(timezone.utc)

        if existing:
            # Update frequency
            existing.frequency += 1
            existing.last_seen = now
            if avoidance_note and not existing.avoidance_note:
                existing.avoidance_note = avoidance_note
            await self._update_record(existing)
        else:
            # Create new record
            record = FailureRecordModel(
                id=f"fail_{tool_name}_{int(now.timestamp())}",
                timestamp=now,
                tool_name=tool_name,
                error_type=error_type,
                error_message=error_message[:500],
                session_id=session_id,
                run_id=run_id,
                context=context or {},
                frequency=1,
                last_seen=now,
                avoidance_note=avoidance_note,
            )
            await self._insert_record(record)

        # Invalidate cache
        self._cache_loaded = False
        logger.info(
            f"[FailureLearning] Recorded failure: tool={tool_name} "
            f"type={error_type} freq={existing.frequency if existing else 1}"
        )

    async def record_success_after_retry(
        self,
        tool_name: str,
        error_type: str,
        retry_note: str,
    ) -> None:
        """
        Record that we figured out how to handle a failure.

        Call this after a retry succeeded with a workaround.
        """
        existing = await self._find_similar(
            error_type=error_type,
            tool_name=tool_name,
            within_hours=168,  # Within 7 days
        )
        if existing:
            existing.avoidance_note = retry_note
            existing.is_resolved = True
            await self._update_record(existing)
            logger.info(f"[FailureLearning] Avoidance learned: {tool_name}/{error_type}: {retry_note}")

    def get_avoidances(self) -> list[FailurePattern]:
        """
        Get all learned avoidances (failures with known workarounds).
        Returns cached results.
        """
        self._ensure_cache_loaded()
        return [p for p in self._cache.values() if p.avoidance_note]

    def get_pattern_for_tool(self, tool_name: str) -> Optional[FailurePattern]:
        """Get the most frequent failure pattern for a tool."""
        self._ensure_cache_loaded()
        patterns = [
            p for p in self._cache.values()
            if p.tool_name == tool_name and not p.is_resolved
        ]
        if not patterns:
            return None
        return max(patterns, key=lambda p: p.frequency)

    def should_skip_retry(self, tool_name: str, error_type: str) -> bool:
        """
        Based on past failures, should we skip retry for this tool/error combo?

        Returns True if we've seen this exact pattern > 5 times without resolution.
        """
        pattern = self.get_pattern_for_tool(tool_name)
        if pattern and pattern.error_type == error_type:
            return pattern.frequency >= 5 and not pattern.avoidance_note
        return False

    def get_tool_warning(self, tool_name: str) -> Optional[str]:
        """
        Get a warning message for a tool based on failure history.
        Used to pre-warn the agent before attempting risky operations.
        """
        pattern = self.get_pattern_for_tool(tool_name)
        if pattern and pattern.frequency >= 3:
            msg = f"[FailureLearning] {tool_name} has failed {pattern.frequency}x "
            msg += f"(last: {pattern.last_seen.strftime('%Y-%m-%d')})"
            if pattern.avoidance_note:
                msg += f" — workaround known: {pattern.avoidance_note}"
            else:
                msg += " — no known workaround yet"
            return msg
        return None

    # ── Internal DB helpers ──────────────────────────────────────────────

    def _classify_error(self, error_message: str) -> str:
        """Classify an error message into a canonical error type."""
        for name, pattern in _ERROR_TYPE_PATTERNS:
            if pattern.search(error_message):
                return name
        return "unknown"

    async def _find_similar(
        self,
        error_type: str,
        tool_name: str,
        within_hours: int,
    ) -> Optional[FailureRecordModel]:
        """Find a recent similar failure record."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
        from sqlmodel import select
        from app.core.db import get_session

        with get_session() as db:
            stmt = select(FailureRecordModel).where(
                FailureRecordModel.error_type == error_type,
                FailureRecordModel.tool_name == tool_name,
                FailureRecordModel.last_seen >= cutoff,
            ).order_by(FailureRecordModel.frequency.desc()).limit(1)

            result = db.exec(stmt).first()
            return result

    async def _insert_record(self, record: FailureRecordModel) -> None:
        from app.core.db import get_session
        with get_session() as db:
            db.add(record)
            db.commit()

    async def _update_record(self, record: FailureRecordModel) -> None:
        from app.core.db import get_session
        with get_session() as db:
            existing = db.get(FailureRecordModel, record.id)
            if existing:
                existing.frequency = record.frequency
                existing.last_seen = record.last_seen
                if record.avoidance_note:
                    existing.avoidance_note = record.avoidance_note
                existing.is_resolved = record.is_resolved
                db.commit()

    def _ensure_cache_loaded(self) -> None:
        """Load pattern cache from DB (once per instance)."""
        if self._cache_loaded:
            return
        self._cache_loaded = True

        import shortuuid
        from sqlmodel import select
        from app.core.db import get_session

        try:
            with get_session() as db:
                stmt = (
                    select(FailureRecordModel)
                    .where(FailureRecordModel.last_seen >= datetime.now(timezone.utc) - timedelta(days=30))
                    .order_by(FailureRecordModel.last_seen.desc())
                )
                records = db.exec(stmt).all()

            # Cluster by tool + error_type, keep most frequent per cluster
            clusters: dict[tuple, FailureRecordModel] = {}
            for r in records:
                key = (r.tool_name, r.error_type)
                if key not in clusters or r.frequency > clusters[key].frequency:
                    clusters[key] = r

            for record in clusters.values():
                self._cache[record.id] = FailurePattern(
                    error_type=record.error_type,
                    tool_name=record.tool_name,
                    count=record.frequency,
                    last_seen=record.last_seen,
                    avoidance_note=record.avoidance_note,
                    is_resolved=record.is_resolved,
                )
        except Exception as e:
            logger.warning(f"Failed to load failure cache: {e}")


# ── Integration hook ───────────────────────────────────────────────────────

async def on_tool_failure(
    tool_name: str,
    error_message: str,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    context: Optional[dict] = None,
) -> None:
    """
    Hook to call in tool manager when a tool execution fails.
    Wired into ToolManager or ToolActivityPayload processing.
    """
    engine = FailureLearningEngine.get_instance()
    await engine.record_failure(
        tool_name=tool_name,
        error_message=error_message,
        session_id=session_id,
        run_id=run_id,
        context=context,
    )
