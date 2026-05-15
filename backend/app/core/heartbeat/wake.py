"""
Heartbeat Wake - Request heartbeat execution from various sources.

Features:
- Priority queue with coalescing (like OpenCLAW's REASON_PRIORITY)
- Coalescing within 250ms window
- Priority levels: RETRY > INTERVAL > DEFAULT > ACTION
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional
import hashlib

logger = logging.getLogger(__name__)

# Default coalescing window (250ms like OpenCLAW)
DEFAULT_COALESCE_MS = 250


class HeartbeatWakeSource(str, Enum):
    """Sources that can trigger a heartbeat."""

    INTERVAL = "interval"  # Scheduled interval trigger
    CRON = "cron"  # Cron job triggered
    HOOK = "hook"  # Event hook triggered
    ACP_SPAWN = "acp-spawn"  # Subagent completion
    EXEC_EVENT = "exec-event"  # Command completion
    API = "api"  # External API request
    MANUAL = "manual"  # Manual trigger
    IMMEDIATE = "immediate"  # Immediate trigger
    RETRY = "retry"  # Retry trigger


class HeartbeatWakeIntent(str, Enum):
    """Intent of the heartbeat wake."""

    SCHEDULED = "scheduled"  # Interval-based scheduled
    EVENT = "event"  # Event-driven
    IMMEDIATE = "immediate"  # Immediate request
    MANUAL = "manual"  # Manual request


# Priority levels matching OpenCLAW's REASON_PRIORITY
REASON_PRIORITY = {
    "retry": 0,
    "interval": 1,
    "scheduled": 1,  # Alias for interval
    "default": 2,
    "event": 2,
    "action": 3,
    "immediate": 3,
    "manual": 3,
}


@dataclass
class HeartbeatWakeRequest:
    """A request to trigger a heartbeat."""

    source: HeartbeatWakeSource
    intent: str  # Human-readable reason
    reason: str  # Detailed reason
    coalesce_ms: int = DEFAULT_COALESCE_MS  # Coalesce similar requests within this window
    created_at: datetime = field(default_factory=datetime.utcnow)
    priority: int = 2  # Default priority
    agent_id: Optional[str] = None
    session_key: Optional[str] = None


@dataclass
class PendingWakeReason:
    """A pending wake in the queue with priority."""

    source: HeartbeatWakeSource
    intent: str
    reason: str
    priority: int
    requested_at: datetime
    agent_id: Optional[str] = None
    session_key: Optional[str] = None


# Global wake handler and queue
_wake_handler: Optional[Callable[[HeartbeatWakeRequest], None]] = None
_wake_queue: asyncio.Queue = asyncio.Queue()
_pending_wakes: dict[str, PendingWakeReason] = {}
_scheduled = False
_running = False
_timer: Optional[asyncio.Task] = None


def _resolve_wake_priority(source: HeartbeatWakeSource, intent: str) -> int:
    """
    Resolve priority for a wake request.

    Priority levels:
    - 0 (RETRY): Highest - retry requests
    - 1 (INTERVAL): Scheduled/interval requests
    - 2 (DEFAULT): Event-driven requests
    - 3 (ACTION): Manual/immediate requests
    """
    # Manual or immediate always gets highest priority (action)
    if intent in ("manual", "immediate"):
        return REASON_PRIORITY["action"]

    # Retry gets highest base priority
    if source == HeartbeatWakeSource.RETRY or intent == "retry":
        return REASON_PRIORITY["retry"]

    # Interval/scheduled
    if intent == "scheduled" or source == HeartbeatWakeSource.INTERVAL:
        return REASON_PRIORITY["interval"]

    return REASON_PRIORITY["default"]


def _get_wake_target_key(agent_id: Optional[str], session_key: Optional[str]) -> str:
    """Get the key for wake coalescing by target."""
    return f"{agent_id or ''}::{session_key or ''}"


def _queue_pending_wake_reason(
    source: HeartbeatWakeSource,
    intent: str,
    reason: str,
    agent_id: Optional[str] = None,
    session_key: Optional[str] = None,
) -> None:
    """Queue a pending wake with priority coalescing."""
    global _pending_wakes

    requested_at = datetime.utcnow()
    priority = _resolve_wake_priority(source, intent)
    target_key = _get_wake_target_key(agent_id, session_key)

    next_wake = PendingWakeReason(
        source=source,
        intent=intent,
        reason=reason,
        priority=priority,
        requested_at=requested_at,
        agent_id=agent_id,
        session_key=session_key,
    )

    previous = _pending_wakes.get(target_key)
    if previous is None:
        _pending_wakes[target_key] = next_wake
        return

    # Merge heartbeats if present
    merged = next_wake

    # Keep higher priority wake
    if next_wake.priority > previous.priority:
        _pending_wakes[target_key] = merged
        return

    # Same priority: keep the earlier one
    if next_wake.priority == previous.priority and next_wake.requested_at >= previous.requested_at:
        _pending_wakes[target_key] = merged


async def _execute_scheduled_wakes() -> None:
    """Execute all pending wakes from the queue."""
    global _pending_wakes, _running, _scheduled

    if not _pending_wakes:
        return

    if _running:
        _scheduled = True
        return

    active = _wake_handler
    if not active:
        _pending_wakes.clear()
        return

    _running = True
    pending_batch = list(_pending_wakes.values())
    _pending_wakes.clear()

    try:
        for pending in pending_batch:
            request = HeartbeatWakeRequest(
                source=pending.source,
                intent=pending.intent,
                reason=pending.reason,
                priority=pending.priority,
                agent_id=pending.agent_id,
                session_key=pending.session_key,
            )
            try:
                active(request)
            except Exception as e:
                logger.error(f"Error in heartbeat wake handler: {e}")
    finally:
        _running = False
        if _pending_wakes:
            _scheduled = True
            asyncio.create_task(_delayed_schedule(DEFAULT_COALESCE_MS))


async def _delayed_schedule(delay_ms: int) -> None:
    """Schedule execution after a delay."""
    await asyncio.sleep(delay_ms / 1000)
    await _execute_scheduled_wakes()


def _schedule(coalesce_ms: int) -> None:
    """Schedule wake execution."""
    global _scheduled

    if _scheduled:
        return

    _scheduled = True
    asyncio.create_task(_delayed_schedule(coalesce_ms))


def set_heartbeat_wake_handler(handler: Callable[[HeartbeatWakeRequest], None]) -> None:
    """Set the handler that processes heartbeat wake requests."""
    global _wake_handler, _pending_wakes

    _wake_handler = handler

    # Clear any pending wakes when handler is set
    if _pending_wakes and handler:
        _schedule(DEFAULT_COALESCE_MS)


async def request_heartbeat(
    source: HeartbeatWakeSource,
    intent: str,
    reason: str,
    coalesce_ms: int = DEFAULT_COALESCE_MS,
    agent_id: Optional[str] = None,
    session_key: Optional[str] = None,
) -> bool:
    """
    Request a heartbeat to be executed with priority coalescing.

    Args:
        source: What triggered this request
        intent: Short description of the heartbeat task
        reason: Detailed reason for this heartbeat
        coalesce_ms: Coalesce similar requests within this window (default 250ms)
        agent_id: Optional agent ID for targeted wakes
        session_key: Optional session key for targeted wakes

    Returns:
        True if the request was accepted, False if coalesced
    """
    global _wake_handler, _pending_wakes

    # Queue the wake with priority coalescing
    _queue_pending_wake_reason(source, intent, reason, agent_id, session_key)

    # Schedule execution
    _schedule(coalesce_ms)

    # If no handler yet, return True (queued)
    if _wake_handler is None:
        logger.warning("No heartbeat wake handler set")
        return True

    return True


def clear_coalesce_cache() -> None:
    """Clear the pending wakes cache. Called after heartbeat execution."""
    global _pending_wakes
    _pending_wakes.clear()


def has_pending_wakes() -> bool:
    """Check if there are pending wakes."""
    return len(_pending_wakes) > 0 or _scheduled


def get_device_id_hash() -> str:
    """
    Get a hash of device-specific ID for phase jittering.

    This prevents thundering herd when multiple instances start at once.
    """
    import os

    # Use machine ID / hostname combination
    try:
        import socket

        host = socket.gethostname()
        # Use a hash of hostname for phase calculation
        hash_val = hashlib.md5(host.encode()).hexdigest()[:8]
        return hash_val
    except Exception:
        return "default"


def calculate_phase_jitter(device_id_hash: str, interval_ms: int, phase_max_ms: int = 60000) -> int:
    """
    Calculate jitter offset based on device ID using SHA256.

    This ensures different instances don't all fire at the same time.
    Uses SHA256 like OpenCLAW for consistent jitter calculation.
    """
    hash_bytes = hashlib.sha256(f"{device_id_hash}:{interval_ms}".encode()).digest()
    hash_int = int.from_bytes(hash_bytes[:4], "big")
    jitter = hash_int % phase_max_ms
    return jitter
