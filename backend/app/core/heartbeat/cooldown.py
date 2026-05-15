"""
Heartbeat Cooldown - Prevents heartbeat spam and ensures proper spacing.

Features 3-layer rate limiting:
1. Minimum interval floor (prevents rapid back-to-back runs)
2. Flood guard (detects feedback loops)
3. Consecutive run limit (prevents runaway heartbeats)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Default values matching OpenCLAW
DEFAULT_MIN_INTERVAL_MS = 30_000  # 30 seconds floor
DEFAULT_FLOOD_WINDOW_MS = 60_000  # 60 second window
DEFAULT_FLOOD_THRESHOLD = 5  # 5 runs per window triggers flood guard


@dataclass
class CooldownConfig:
    """Configuration for cooldown behavior."""

    min_interval_ms: int = DEFAULT_MIN_INTERVAL_MS  # Minimum 30 seconds between heartbeats
    max_consecutive: int = 3  # Max consecutive heartbeats before forced cooldown
    stale_threshold_ms: int = 60000  # Consider heartbeat stale after 60 seconds
    # Flood guard settings
    flood_window_ms: int = DEFAULT_FLOOD_WINDOW_MS  # Window for flood detection
    flood_threshold: int = DEFAULT_FLOOD_THRESHOLD  # Max runs per window before deferral
    # Enable/disable flood guard
    flood_guard_enabled: bool = True


class CooldownManager:
    """
    Manages heartbeat cooldown to prevent spam.

    Implements 3-layer rate limiting:
    1. Minimum interval floor - prevents rapid back-to-back runs
    2. Flood guard - detects and prevents feedback loops
    3. Consecutive run limit - prevents runaway heartbeats

    Tracks:
    - Last heartbeat time
    - Consecutive heartbeat count
    - Whether we're in a forced cooldown period
    - Recent run timestamps for flood detection
    """

    def __init__(self, config: Optional[CooldownConfig] = None):
        self.config = config or CooldownConfig()
        self._last_heartbeat: Optional[datetime] = None
        self._consecutive_count: int = 0
        self._cooldown_until: Optional[datetime] = None
        self._lock = asyncio.Lock()
        # Flood guard: recent run timestamps (bounded buffer)
        self._recent_runs: list[int] = field(default_factory=list)

    def _check_flood_guard(self, now_ms: int) -> tuple[bool, str]:
        """
        Check flood guard layer.

        Returns:
            (should_defer, reason)
        """
        if not self.config.flood_guard_enabled:
            return False, ""

        flood_window = self.config.flood_window_ms
        flood_threshold = self.config.flood_threshold

        if len(self._recent_runs) < flood_threshold:
            return False, ""

        window_start = now_ms - flood_window
        in_window = 0
        for ts in reversed(self._recent_runs):
            if ts < window_start:
                break
            in_window += 1

        if in_window >= flood_threshold:
            logger.warning(
                f"Flood guard triggered: {in_window} runs in {flood_window}ms "
                f"(threshold: {flood_threshold})"
            )
            return True, "flood"

        return False, ""

    async def should_defer(self) -> tuple[bool, str]:
        """
        Check if heartbeat should be deferred using 3-layer rate limiting.

        Returns:
            (should_defer, reason)
        """
        async with self._lock:
            now = datetime.utcnow()
            now_ms = int(now.timestamp() * 1000)

            # Layer 1: Check if in cooldown period
            if self._cooldown_until and now < self._cooldown_until:
                remaining = (self._cooldown_until - now).total_seconds()
                return True, f"In cooldown for {remaining:.0f}s"

            # Layer 2: Flood guard (before min_interval to catch feedback loops early)
            should_defer, reason = self._check_flood_guard(now_ms)
            if should_defer:
                return True, reason

            # Layer 3: Minimum interval floor (30s default)
            if self._last_heartbeat:
                elapsed_ms = (now - self._last_heartbeat).total_seconds() * 1000
                if elapsed_ms < self.config.min_interval_ms:
                    remaining_s = (self.config.min_interval_ms - elapsed_ms) / 1000
                    return True, f"Min interval not reached ({remaining_s:.0f}s remaining)"

            # Check if previous heartbeat is stale
            if self._last_heartbeat:
                stale_ms = (now - self._last_heartbeat).total_seconds() * 1000
                if stale_ms > self.config.stale_threshold_ms:
                    # Reset consecutive count if stale
                    self._consecutive_count = 0

            # Layer 4: Consecutive run limit
            if self._consecutive_count >= self.config.max_consecutive:
                return True, f"Max consecutive ({self.config.max_consecutive}) reached"

            return False, ""

    async def should_defer_for_wake(
        self,
        now_ms: int,
        last_run_started_at_ms: Optional[int] = None,
    ) -> tuple[bool, str]:
        """
        Check if a wake request should be deferred.

        This is similar to should_defer but designed for wake requests
        and includes the flood guard check.

        Args:
            now_ms: Current time in milliseconds
            last_run_started_at_ms: When the last run started

        Returns:
            (should_defer, reason)
        """
        async with self._lock:
            # Flood guard always applies to wakes
            should_defer, reason = self._check_flood_guard(now_ms)
            if should_defer:
                return True, reason

            # Min interval floor
            if self._last_heartbeat:
                elapsed_ms = now_ms - int(self._last_heartbeat.timestamp() * 1000)
                if elapsed_ms < self.config.min_interval_ms:
                    remaining_s = (self.config.min_interval_ms - elapsed_ms) / 1000
                    return True, f"Min interval not reached ({remaining_s:.0f}s remaining)"

            # Check last run started time for min spacing
            if last_run_started_at_ms is not None:
                min_spacing = self.config.min_interval_ms
                if now_ms - last_run_started_at_ms < min_spacing:
                    return True, "min-spacing"

            return False, ""

    async def record_heartbeat(self, triggered: bool = True) -> None:
        """
        Record that a heartbeat was executed.

        Args:
            triggered: Whether the heartbeat actually triggered work
        """
        async with self._lock:
            now = datetime.utcnow()
            self._last_heartbeat = now

            # Record in flood guard buffer
            now_ms = int(now.timestamp() * 1000)
            self._recent_runs.append(now_ms)

            # Trim buffer to flood_threshold + 1 entries
            max_size = self.config.flood_threshold + 1
            while len(self._recent_runs) > max_size:
                self._recent_runs.pop(0)

            if triggered:
                self._consecutive_count += 1
            else:
                # Reset count if heartbeat was skipped
                self._consecutive_count = 0

    async def enter_cooldown(self, duration_seconds: int) -> None:
        """
        Enter a forced cooldown period.

        Args:
            duration_seconds: How long to cooldown
        """
        async with self._lock:
            self._cooldown_until = datetime.utcnow() + timedelta(seconds=duration_seconds)
            logger.info(f"Entering heartbeat cooldown for {duration_seconds}s")

    async def reset(self) -> None:
        """Reset all cooldown state."""
        async with self._lock:
            self._last_heartbeat = None
            self._consecutive_count = 0
            self._cooldown_until = None
            self._recent_runs.clear()

    def get_status(self) -> dict:
        """Get current cooldown status."""
        now = datetime.utcnow()
        return {
            "last_heartbeat": self._last_heartbeat.isoformat() if self._last_heartbeat else None,
            "consecutive_count": self._consecutive_count,
            "in_cooldown": self._cooldown_until is not None and now < self._cooldown_until,
            "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
            "flood_guard": {
                "enabled": self.config.flood_guard_enabled,
                "recent_runs_count": len(self._recent_runs),
                "window_ms": self.config.flood_window_ms,
                "threshold": self.config.flood_threshold,
            },
            "min_interval_ms": self.config.min_interval_ms,
        }
