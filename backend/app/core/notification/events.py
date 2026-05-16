"""Notification event definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal


class NotificationSeverity(str, Enum):
    """Notification severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class NotificationEvent:
    """A single notification event to be dispatched."""
    severity: NotificationSeverity
    source: str  # e.g. "health_checker", "unanswered", "missed_crons"
    title: str
    body: str
    actions: tuple[str, ...] = field(default_factory=tuple)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_text(self) -> str:
        """Render as plain text message."""
        lines = [f"【{self.severity.value.upper()}】{self.title}", "", self.body]
        if self.actions:
            lines.append("")
            lines.append("可执行操作：")
            for action in self.actions:
                lines.append(f"  • {action}")
        return "\n".join(lines)

    def to_feishu_card(self) -> dict:
        """Render as Feishu interactive card payload."""
        color_map = {
            NotificationSeverity.CRITICAL: "red",
            NotificationSeverity.WARNING: "yellow",
            NotificationSeverity.INFO: "grey",
        }
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"【{self.severity.value.upper()}】{self.title}",
                    },
                    "template": color_map.get(self.severity, "grey"),
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": self.body,
                    },
                    *(
                        [
                            {"tag": "hr"},
                            {
                                "tag": "markdown",
                                "content": "**可执行操作：**\n" + "\n".join(
                                    f"• {a}" for a in self.actions
                                ),
                            },
                        ]
                        if self.actions
                        else []
                    ),
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"来源：{self.source} | {self.timestamp}",
                            }
                        ],
                    },
                ],
            },
        }
