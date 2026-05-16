"""
Unanswered Sessions Checker - detects user messages without agent replies.

Converted from check-unanswered.sh:
- Scans all agent session files
- Checks if the last message is a user message (no reply)
- Default: only checks sessions active in the last 24 hours
- Supports JSON output

Integration: called by Curator (scheduled) and Heartbeat (periodic).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.core.notification import NotificationManager

DEFAULT_OPENCLAW_DIR = Path.home() / ".openclaw"
DEFAULT_MAX_AGE_HOURS = 24


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


@dataclass(frozen=True)
class UnansweredSession:
    """A session with an unanswered user message."""
    agent_id: str
    session_name: str
    session_key: str  # agent:{agent_id}:{session_name}
    timestamp: str
    content_preview: str


@dataclass
class UnansweredCheckerConfig:
    """Configuration for unanswered session checker."""
    openclaw_dir: Path = DEFAULT_OPENCLAW_DIR
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS
    include_old: bool = False
    verbose: bool = False


@dataclass
class UnansweredCheckerResult:
    """Result of unanswered session check."""
    count: int
    sessions: tuple[UnansweredSession, ...]
    all_ok: bool  # True if no unanswered sessions


class UnansweredChecker:
    """
    Scan sessions for unreplied user messages.

    Reads session JSON files and checks if the last message
    is from the user (indicating no agent reply yet).
    """

    def __init__(self, config: Optional[UnansweredCheckerConfig] = None) -> None:
        self.config = config or UnansweredCheckerConfig()

    def set_notification_manager(self, nm: "NotificationManager") -> None:
        """Inject NotificationManager for proactive alerting."""
        self._notification_manager: "NotificationManager" = nm

    async def check(self) -> UnansweredCheckerResult:
        """
        Scan all agent sessions for unanswered messages.

        Returns:
            UnansweredCheckerResult with list of unanswered sessions.
        """
        agents_dir = self.config.openclaw_dir / "agents"
        if not agents_dir.exists():
            return UnansweredCheckerResult(count=0, sessions=(), all_ok=True)

        now_ts = datetime.now(timezone.utc).timestamp()
        max_age_seconds = self.config.max_age_hours * 3600
        unanswered: list[UnansweredSession] = []

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue

            agent_id = agent_dir.name
            sessions_dir = agent_dir / "sessions"
            if not sessions_dir.exists():
                continue

            for session_file in sessions_dir.glob("*.json"):
                try:
                    # Skip .deleted and .lock files
                    if session_file.suffix in (".deleted", ".lock"):
                        continue

                    # Check file age
                    if not self.config.include_old:
                        mtime = session_file.stat().st_mtime
                        age_seconds = now_ts - mtime
                        if age_seconds > max_age_seconds:
                            continue

                    # Read last line (JSON per line format)
                    lines = session_file.read_text().strip().split("\n")
                    if not lines:
                        continue
                    last_line = lines[-1]

                    # Parse JSON
                    try:
                        data = json.loads(last_line)
                    except json.JSONDecodeError:
                        continue

                    # Get role
                    msg = data.get("message", {})
                    role = msg.get("role", "")
                    if role != "user":
                        continue

                    # This session has no agent reply
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # Structured content - extract text
                        content_preview = " ".join(
                            c.get("text", "")[:100]
                            for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        )[:100]
                    elif isinstance(content, str):
                        content_preview = content[:100]
                    else:
                        content_preview = ""

                    # Get timestamp
                    ts = msg.get("timestamp")
                    if not ts:
                        # Fall back to file mtime
                        ts = datetime.fromtimestamp(
                            session_file.stat().st_mtime, tz=timezone.utc
                        ).strftime("%Y-%m-%d %H:%M")

                    session_name = session_file.stem
                    session_key = f"agent:{agent_id}:{session_name}"

                    unanswered.append(UnansweredSession(
                        agent_id=agent_id,
                        session_name=session_name,
                        session_key=session_key,
                        timestamp=ts,
                        content_preview=content_preview,
                    ))

                except Exception as e:
                    logger.debug(f"Error checking session {session_file}: {e}")

        result = UnansweredCheckerResult(
            count=len(unanswered),
            sessions=tuple(unanswered),
            all_ok=len(unanswered) == 0,
        )

        logger.info(
            f"[UnansweredChecker] Found {len(unanswered)} unanswered sessions"
        )

        # Dispatch notification if there are unanswered sessions
        if not result.all_ok and hasattr(self, "_notification_manager"):
            from app.core.notification.events import NotificationEvent, NotificationSeverity
            session_list = "\n".join(
                f"• {s.session_key}: {s.content_preview[:50]}"
                for s in result.sessions[:10]
            )
            if result.count > 10:
                session_list += f"\n... 还有 {result.count - 10} 条"
            notification = NotificationEvent(
                severity=NotificationSeverity.WARNING,
                source="unanswered",
                title="有未回复的用户消息",
                body=f"检测到 {result.count} 条未回复的用户消息：\n{session_list}",
            )
            await self._notification_manager.dispatch(notification)

        return result

    def format_text(self, result: UnansweredCheckerResult) -> str:
        """Format result as human-readable text."""
        if result.all_ok:
            return "No unanswered messages"

        lines = [f"Found {result.count} unanswered session(s):\n"]
        for sess in result.sessions:
            lines.append(f"Session: {sess.session_key}")
            lines.append(f"Time: {sess.timestamp}")
            if self.config.verbose and sess.content_preview:
                lines.append(f"Preview: {sess.content_preview[:80]}")
            lines.append("")
        return "\n".join(lines)

    def format_json(self, result: UnansweredCheckerResult) -> str:
        """Format result as JSON string."""
        sessions_data = [
            {
                "session_key": s.session_key,
                "timestamp": s.timestamp,
                "preview": s.content_preview[:100] if s.content_preview else "",
            }
            for s in result.sessions
        ]
        return json.dumps({
            "unanswered": sessions_data,
            "count": result.count,
        }, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------

async def check_unanswered_sessions(
    openclaw_dir: Optional[Path] = None,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    include_old: bool = False,
    verbose: bool = False,
    output_format: OutputFormat = OutputFormat.JSON,
) -> UnansweredCheckerResult | str:
    """
    Check for unanswered user messages across all sessions.

    Args:
        openclaw_dir: Path to OpenCLAW directory (default: ~/.openclaw)
        max_age_hours: Only check sessions active in this window (default 24h)
        include_old: Include sessions older than max_age_hours
        verbose: Include message content previews
        output_format: TEXT or JSON output

    Returns:
        UnansweredCheckerResult or formatted string
    """
    config = UnansweredCheckerConfig(
        openclaw_dir=openclaw_dir or DEFAULT_OPENCLAW_DIR,
        max_age_hours=max_age_hours,
        include_old=include_old,
        verbose=verbose,
    )
    checker = UnansweredChecker(config)
    result = await checker.check()

    if output_format == OutputFormat.JSON:
        return checker.format_json(result)
    return result
