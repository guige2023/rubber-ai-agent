"""
Heartbeat Scheduler - Calculates when the next heartbeat is due.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum seek horizon for active hours (7 days)
MAX_SEEK_HORIZON_MS = 7 * 24 * 60 * 60 * 1000
# Maximum iterations to prevent pathological sub-minute intervals
MAX_SEEK_ITERATIONS = 10080  # 7 days at 1-minute steps


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat behavior."""

    interval_ms: int = 30 * 60 * 1000  # Default 30 minutes
    active_hours_start: Optional[int] = None  # Hour of day to start (0-23)
    active_hours_end: Optional[int] = None  # Hour of day to end (0-23)
    phase_ms: int = 0  # Phase offset for jitter
    jitter_max_ms: int = 60000  # Max jitter to add
    # Active hours timezone (default: UTC)
    active_hours_tz: Optional[str] = None


@dataclass
class HeartbeatSchedule:
    """Current heartbeat schedule state."""

    next_due_ms: int = 0  # Milliseconds from epoch
    interval_ms: int = 30 * 60 * 1000
    phase_ms: int = 0
    is_active: bool = True


def resolve_next_heartbeat_due_ms(
    now_ms: int,
    interval_ms: int,
    phase_ms: int,
    prev_next_ms: int = 0,
) -> int:
    """
    Calculate when the next heartbeat is due.

    Args:
        now_ms: Current time in milliseconds
        interval_ms: Interval between heartbeats
        phase_ms: Phase offset (from jitter)
        prev_next_ms: Previous scheduled time

    Returns:
        Next heartbeat time in milliseconds
    """
    if prev_next_ms == 0:
        # First time, start from now + phase
        return now_ms + phase_ms

    # Find the next interval boundary after now
    elapsed = now_ms - prev_next_ms
    if elapsed >= 0:
        # We're past the scheduled time, calculate next
        intervals = elapsed // interval_ms
        next_next = prev_next_ms + (intervals + 1) * interval_ms
        return next_next
    else:
        # We're before the scheduled time
        return prev_next_ms


def seek_next_active_phase_due_ms(
    start_ms: int,
    interval_ms: int,
    phase_ms: int,
    active_hours: tuple[int, int] | None = None,
) -> int:
    """
    Find the next heartbeat time within active hours.

    Args:
        start_ms: Start time in milliseconds
        interval_ms: Heartbeat interval
        phase_ms: Phase offset
        active_hours: Tuple of (start_hour, end_hour) in 0-23, or None for 24/7

    Returns:
        Next active phase time in milliseconds
    """
    if active_hours is None:
        return start_ms + phase_ms

    start_hour, end_hour = active_hours

    # Convert to datetime for easier manipulation
    start_dt = datetime.fromtimestamp(start_ms / 1000)
    current_hour = start_dt.hour

    # Check if current hour is within active hours
    if start_hour <= end_hour:
        # Normal range (e.g., 9-17)
        is_active = start_hour <= current_hour < end_hour
    else:
        # Overnight range (e.g., 22-6)
        is_active = current_hour >= start_hour or current_hour < end_hour

    if is_active:
        return start_ms + phase_ms

    # Need to wait until active hours
    # Calculate seconds until next active hour
    if current_hour < start_hour:
        hours_until = start_hour - current_hour
    else:
        hours_until = 24 - current_hour + start_hour

    wait_ms = (hours_until * 3600 + start_dt.minute * 60 + start_dt.second) * 1000
    return start_ms + wait_ms + phase_ms


def calculate_phase_offset(device_id_hash: str, interval_ms: int, jitter_max_ms: int = 60000) -> int:
    """
    Calculate phase offset for jitter based on device ID using SHA256.

    This prevents thundering herd when multiple instances start together.
    Uses SHA256 like OpenCLAW for consistent hash-based jitter calculation.
    """
    hash_bytes = hashlib.sha256(f"{device_id_hash}:{interval_ms}".encode()).digest()
    hash_int = int.from_bytes(hash_bytes[:4], "big")
    jitter = hash_int % jitter_max_ms
    return jitter


def is_within_active_hours(
    now_ms: int,
    active_hours: tuple[int, int] | None,
    tz: str = "UTC",
) -> bool:
    """
    Check if the given timestamp falls within active hours.

    Args:
        now_ms: Current time in milliseconds
        active_hours: Tuple of (start_hour, end_hour) in 0-23, or None for 24/7
        tz: Timezone for hour calculation (default UTC)

    Returns:
        True if within active hours, False otherwise
    """
    if active_hours is None:
        return True

    start_hour, end_hour = active_hours

    # Get current hour in the specified timezone
    dt = datetime.fromtimestamp(now_ms / 1000)
    if tz != "UTC":
        # Use timezone-aware datetime if tz is specified
        import zoneinfo

        try:
            tzinfo = zoneinfo.ZoneInfo(tz)
            dt = datetime.fromtimestamp(now_ms / 1000, tz=tzinfo)
        except Exception:
            pass  # Fall back to local time

    current_hour = dt.hour

    if start_hour <= end_hour:
        # Normal range (e.g., 9-17)
        return start_hour <= current_hour < end_hour
    else:
        # Overnight range (e.g., 22-6)
        return current_hour >= start_hour or current_hour < end_hour


def seek_next_active_phase_due_ms_v2(
    start_ms: int,
    interval_ms: int,
    phase_ms: int,
    active_hours: tuple[int, int] | None = None,
    tz: str = "UTC",
) -> int:
    """
    Seek forward through phase-aligned slots until one falls within active hours.

    Falls back to the raw next slot when no active_hours is provided or no
    in-window slot is found within the seek horizon.

    Args:
        start_ms: Start time in milliseconds
        interval_ms: Heartbeat interval
        phase_ms: Phase offset
        active_hours: Tuple of (start_hour, end_hour) in 0-23, or None for 24/7
        tz: Timezone for active hours calculation

    Returns:
        Next active phase time in milliseconds
    """
    if active_hours is None:
        return start_ms + phase_ms

    horizon_ms = start_ms + MAX_SEEK_HORIZON_MS
    candidate_ms = start_ms
    iterations = 0

    while candidate_ms <= horizon_ms and iterations < MAX_SEEK_ITERATIONS:
        if is_within_active_hours(candidate_ms, active_hours, tz):
            return candidate_ms
        candidate_ms += interval_ms
        iterations += 1

    # No in-window slot found; fall back so the runtime guard can gate it
    return start_ms


def compute_next_heartbeat_phase_due_ms(
    now_ms: int,
    interval_ms: int,
    phase_ms: int,
) -> int:
    """
    Compute the next heartbeat time based on phase alignment.

    Args:
        now_ms: Current time in milliseconds
        interval_ms: Heartbeat interval
        phase_ms: Phase offset

    Returns:
        Next heartbeat time in milliseconds
    """
    interval_ms = max(1, interval_ms)
    phase_ms = phase_ms % interval_ms
    cycle_position_ms = now_ms % interval_ms
    delta_ms = (phase_ms - cycle_position_ms) % interval_ms
    if delta_ms == 0:
        delta_ms = interval_ms
    return now_ms + delta_ms


class HeartbeatScheduler:
    """
    Schedules heartbeat execution times.

    Handles:
    - Interval-based scheduling
    - Active hours restrictions
    - Phase jitter to prevent thundering herd
    """

    def __init__(self, config: Optional[HeartbeatConfig] = None):
        self.config = config or HeartbeatConfig()
        self._schedule = HeartbeatSchedule(
            interval_ms=self.config.interval_ms,
            phase_ms=self.config.phase_ms,
        )
        self._device_id_hash = self._get_device_id_hash()

    def _get_device_id_hash(self) -> str:
        """Get device-specific hash for phase calculation."""
        import os
        import socket

        try:
            host = socket.gethostname()
            pid = os.getpid()
            return f"{host}:{pid}"
        except Exception:
            return "default"

    def calculate_next(self, now_ms: int, prev_next_ms: int = 0) -> int:
        """
        Calculate the next heartbeat time.

        Args:
            now_ms: Current time in milliseconds
            prev_next_ms: Previous scheduled time (0 if first)

        Returns:
            Next heartbeat time in milliseconds
        """
        interval_ms = self.config.interval_ms

        # Calculate phase offset on first run using SHA256-based jitter
        if prev_next_ms == 0 and self.config.phase_ms == 0:
            self._schedule.phase_ms = calculate_phase_offset(
                self._device_id_hash, interval_ms, self.config.jitter_max_ms
            )

        # Determine base next time
        active_hours = (
            (self.config.active_hours_start, self.config.active_hours_end)
            if self.config.active_hours_start is not None
            else None
        )

        if active_hours:
            base_next = seek_next_active_phase_due_ms_v2(
                now_ms,
                interval_ms,
                self._schedule.phase_ms,
                active_hours,
                self.config.active_hours_tz or "UTC",
            )
        else:
            # Use phase-aligned calculation
            base_next = compute_next_heartbeat_phase_due_ms(
                now_ms, interval_ms, self._schedule.phase_ms
            )

        self._schedule.next_due_ms = base_next
        return base_next

    def is_active_at(self, timestamp_ms: int) -> bool:
        """Check if a timestamp is within active hours."""
        if self.config.active_hours_start is None:
            return True

        active_hours = (self.config.active_hours_start, self.config.active_hours_end)
        return is_within_active_hours(
            timestamp_ms, active_hours, self.config.active_hours_tz or "UTC"
        )

    def is_within_active_hours(self, now_ms: Optional[int] = None) -> bool:
        """
        Check if current time (or given timestamp) is within active hours.

        Args:
            now_ms: Optional timestamp in milliseconds (defaults to now)

        Returns:
            True if within active hours, False otherwise
        """
        if self.config.active_hours_start is None:
            return True

        if now_ms is None:
            now_ms = int(datetime.utcnow().timestamp() * 1000)

        return is_within_active_hours(
            now_ms,
            (self.config.active_hours_start, self.config.active_hours_end),
            self.config.active_hours_tz or "UTC",
        )

    def get_status(self) -> dict:
        """Get current scheduler status."""
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        return {
            "interval_ms": self.config.interval_ms,
            "phase_ms": self._schedule.phase_ms,
            "next_due_ms": self._schedule.next_due_ms,
            "active_hours": (
                (self.config.active_hours_start, self.config.active_hours_end)
                if self.config.active_hours_start is not None
                else None
            ),
            "active_hours_tz": self.config.active_hours_tz or "UTC",
            "is_within_active_hours": self.is_within_active_hours(now_ms),
        }
