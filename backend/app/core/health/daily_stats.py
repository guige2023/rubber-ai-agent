"""
Daily Stats - message volume statistics for OpenCLAW.

Converted from daily-stats.sh:
- Message counts (received/enqueued/completed/failed)
- Hourly message distribution
- Per-agent message distribution
- Error analysis (provider/timeout/lock/tool)
- Gateway status (restarts, Feishu connections)
- Response time estimation
- Recent errors

Integration: called by Curator (scheduled) for periodic reporting.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_OPENCLAW_DIR = Path.home() / ".openclaw"


@dataclass
class DailyStatsConfig:
    """Configuration for daily stats."""
    openclaw_dir: Path = DEFAULT_OPENCLAW_DIR
    date: Optional[str] = None  # YYYY-MM-DD, defaults to today


@dataclass
class MessageStats:
    """Message processing statistics."""
    received: int
    enqueued: int
    completed: int
    errors: int
    success_rate: float  # 0.0 to 100.0


@dataclass
class HourlyDistribution:
    """Message count per hour."""
    hour: int  # 0-23
    count: int


@dataclass
class AgentStats:
    """Per-agent message counts."""
    agent: str
    count: int


@dataclass
class ErrorStats:
    """Error breakdown."""
    provider_errors: int
    timeout_errors: int
    lock_errors: int
    tool_errors: int


@dataclass
class GatewayStats:
    """Gateway operational stats."""
    restarts: int
    feishu_connects: int


@dataclass
class ResponseStats:
    """Response timing estimates."""
    typing_started: int
    typing_removed: int  # completed


@dataclass
class DailyStats:
    """
    Complete daily statistics for OpenCLAW.

    Collected from gateway log files.
    """
    date: str
    messages: MessageStats
    hourly: tuple[HourlyDistribution, ...]
    agents: tuple[AgentStats, ...]
    errors: ErrorStats
    gateway: GatewayStats
    response: ResponseStats
    recent_errors: tuple[str, ...]
    total_issues: int


class DailyStatsCollector:
    """
    Collect daily message and error statistics from OpenCLAW logs.

    Reads the gateway log and per-day tool log to produce
    comprehensive activity statistics.
    """

    def __init__(self, config: Optional[DailyStatsConfig] = None) -> None:
        self.config = config or DailyStatsConfig()
        if self.config.date is None:
            self.config.date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def collect(self) -> DailyStats:
        """
        Collect statistics for the configured date.

        Returns:
            DailyStats with all collected metrics.
        """
        date = self.config.date
        gateway_log = self.config.openclaw_dir / "logs" / "gateway.log"
        tool_log = self.config.openclaw_dir.parent / ".openclaw" / "logs" / f"openclaw-{date}.log"

        # Try both locations for tool log
        if not tool_log.exists():
            tool_log = self.config.openclaw_dir / "logs" / f"openclaw-{date}.log"
        if not tool_log.exists():
            tool_log = Path(f"/tmp/openclaw/openclaw-{date}.log")

        gateway_lines: list[str] = []
        tool_lines: list[str] = []

        if gateway_log.exists():
            gateway_lines = self._filter_by_date(gateway_log.read_text(), date)
        if tool_log.exists():
            tool_lines = tool_log.read_text().split("\n")

        # Collect all stats
        messages = self._collect_message_stats(gateway_lines)
        hourly = self._collect_hourly_distribution(gateway_lines)
        agents = self._collect_agent_stats(gateway_lines)
        errors = self._collect_error_stats(tool_lines)
        gateway = self._collect_gateway_stats(gateway_lines)
        response = self._collect_response_stats(gateway_lines)
        recent = self._collect_recent_errors(tool_lines)

        total_issues = (
            messages.errors
            + errors.provider_errors
            + errors.lock_errors
        )

        return DailyStats(
            date=date,
            messages=messages,
            hourly=tuple(hourly),
            agents=tuple(agents),
            errors=errors,
            gateway=gateway,
            response=response,
            recent_errors=tuple(recent),
            total_issues=total_issues,
        )

    # ------------------------------------------------------------------
    # Message statistics
    # ------------------------------------------------------------------

    def _collect_message_stats(self, lines: list[str]) -> MessageStats:
        """Collect message counts from log lines."""
        received = self._count_lines(lines, "received message")
        enqueued = self._count_lines(lines, "lane enqueue")
        completed = self._count_lines(lines, "lane task done")
        errors = self._count_lines(lines, "lane task error")

        success_rate = 0.0
        if enqueued > 0:
            success_rate = round(completed * 100.0 / enqueued, 1)

        return MessageStats(
            received=received,
            enqueued=enqueued,
            completed=completed,
            errors=errors,
            success_rate=success_rate,
        )

    # ------------------------------------------------------------------
    # Hourly distribution
    # ------------------------------------------------------------------

    def _collect_hourly_distribution(self, lines: list[str]) -> list[HourlyDistribution]:
        """Build hourly message count distribution."""
        hourly_counts: dict[int, int] = {h: 0 for h in range(24)}

        for line in lines:
            if "received message" not in line:
                continue
            # Extract hour from timestamp like "2026-01-15T14:30:00"
            match = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2}):", line)
            if match:
                try:
                    hour = int(match.group(2))
                    hourly_counts[hour] += 1
                except ValueError:
                    pass

        return [
            HourlyDistribution(hour=h, count=c)
            for h, c in sorted(hourly_counts.items())
            if c > 0
        ]

    # ------------------------------------------------------------------
    # Agent statistics
    # ------------------------------------------------------------------

    def _collect_agent_stats(self, lines: list[str]) -> list[AgentStats]:
        """Collect per-agent message counts."""
        agent_counts: dict[str, int] = {}

        for line in lines:
            if "received message" not in line:
                continue
            # Match feishu[agent_name] pattern
            match = re.search(r"feishu\[(\w+)\]", line)
            if match:
                agent = match.group(1)
                agent_counts[agent] = agent_counts.get(agent, 0) + 1

        return [
            AgentStats(agent=name, count=count)
            for name, count in sorted(agent_counts.items(), key=lambda x: -x[1])
        ]

    # ------------------------------------------------------------------
    # Error statistics
    # ------------------------------------------------------------------

    def _collect_error_stats(self, lines: list[str]) -> ErrorStats:
        """Collect error counts from tool log."""
        provider = self._count_lines(lines, "FailoverError") + self._count_lines(
            lines, "All models failed"
        )
        timeout = self._count_lines(lines, "timed out")
        lock = self._count_lines(lines, "session file locked")
        tool = self._count_lines(lines, "[tools]") + self._count_lines(lines, "failed")

        return ErrorStats(
            provider_errors=provider,
            timeout_errors=timeout,
            lock_errors=lock,
            tool_errors=tool,
        )

    # ------------------------------------------------------------------
    # Gateway statistics
    # ------------------------------------------------------------------

    def _collect_gateway_stats(self, lines: list[str]) -> GatewayStats:
        """Collect gateway operational stats."""
        restarts = self._count_lines(lines, "Gateway started")
        ws_connects = self._count_lines(lines, "WebSocket client started")

        return GatewayStats(
            restarts=restarts,
            feishu_connects=ws_connects,
        )

    # ------------------------------------------------------------------
    # Response statistics
    # ------------------------------------------------------------------

    def _collect_response_stats(self, lines: list[str]) -> ResponseStats:
        """Collect typing indicator counts as response time proxy."""
        started = self._count_lines(lines, "added typing")
        removed = self._count_lines(lines, "removed typing")

        return ResponseStats(
            typing_started=started,
            typing_removed=removed,
        )

    # ------------------------------------------------------------------
    # Recent errors
    # ------------------------------------------------------------------

    def _collect_recent_errors(self, lines: list[str]) -> list[str]:
        """Collect the 3 most recent error lines."""
        errors: list[str] = []
        for line in lines:
            if "ERROR" in line or ("error" in line and "failed" in line):
                # Extract timestamp
                ts_match = re.search(r"T(\d{2}:\d{2}:\d{2})", line)
                if ts_match:
                    errors.append(f"{ts_match.group(1)} - {line[:100]}")
                if len(errors) >= 3:
                    break
        return errors

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_lines(lines: list[str], pattern: str) -> int:
        """Count lines matching a pattern."""
        return sum(1 for line in lines if pattern in line)

    @staticmethod
    def _filter_by_date(text: str, date: str) -> list[str]:
        """Filter log lines for a specific date."""
        return [line for line in text.split("\n") if line.startswith(date)]

    def format_text(self, stats: DailyStats) -> str:
        """Format stats as human-readable text."""
        lines = [
            f"OpenCLAW Daily Stats - {stats.date}",
            "",
            "--- Message Stats ---",
            f"  Received: {stats.messages.received}",
            f"  Enqueued: {stats.messages.enqueued}",
            f"  Completed: {stats.messages.completed}",
            f"  Failed: {stats.messages.errors}",
            f"  Success Rate: {stats.messages.success_rate}%",
            "",
            "--- Hourly Distribution ---",
        ]

        for h in stats.hourly:
            bar = "█" * min(h.count, 20)
            lines.append(f"  {h.hour:02d}:00  {bar} {h.count}")

        if stats.agents:
            lines.extend(["", "--- Agent Activity ---"])
            for a in stats.agents:
                lines.append(f"  {a.agent}: {a.count} messages")

        lines.extend([
            "",
            "--- Errors ---",
            f"  Provider Errors: {stats.errors.provider_errors}",
            f"  Timeout Errors: {stats.errors.timeout_errors}",
            f"  Lock Errors: {stats.errors.lock_errors}",
            f"  Tool Errors: {stats.errors.tool_errors}",
            "",
            "--- Gateway Status ---",
            f"  Restarts: {stats.gateway.restarts}",
            f"  Feishu Connections: {stats.gateway.feishu_connects}",
            "",
            "--- Summary ---",
        ])

        if stats.total_issues == 0:
            lines.append("  All systems normal, no major errors")
        else:
            lines.append(f"  {stats.total_issues} issue(s) to review")

        return "\n".join(lines)


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------

async def get_daily_stats(
    date: Optional[str] = None,
    openclaw_dir: Optional[Path] = None,
    output_format: str = "text",  # "text" or "json"
) -> DailyStats | str:
    """
    Get daily statistics for OpenCLAW.

    Args:
        date: Date string YYYY-MM-DD (default: today)
        openclaw_dir: Path to OpenCLAW directory (default: ~/.openclaw)
        output_format: "text" or "json"

    Returns:
        DailyStats object or formatted string
    """
    import json

    config = DailyStatsConfig(
        openclaw_dir=openclaw_dir or DEFAULT_OPENCLAW_DIR,
        date=date,
    )
    collector = DailyStatsCollector(config)
    stats = await collector.collect()

    if output_format == "json":
        return json.dumps({
            "date": stats.date,
            "messages": {
                "received": stats.messages.received,
                "enqueued": stats.messages.enqueued,
                "completed": stats.messages.completed,
                "errors": stats.messages.errors,
                "success_rate": stats.messages.success_rate,
            },
            "hourly": [{"hour": h.hour, "count": h.count} for h in stats.hourly],
            "agents": [{"agent": a.agent, "count": a.count} for a in stats.agents],
            "errors": {
                "provider_errors": stats.errors.provider_errors,
                "timeout_errors": stats.errors.timeout_errors,
                "lock_errors": stats.errors.lock_errors,
                "tool_errors": stats.errors.tool_errors,
            },
            "gateway": {
                "restarts": stats.gateway.restarts,
                "feishu_connects": stats.gateway.feishu_connects,
            },
            "response": {
                "typing_started": stats.response.typing_started,
                "typing_removed": stats.response.typing_removed,
            },
            "recent_errors": list(stats.recent_errors),
            "total_issues": stats.total_issues,
        }, ensure_ascii=False, indent=2)

    return collector.format_text(stats)
