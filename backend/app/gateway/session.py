"""
Session Context - Represents a messaging session across platforms.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import uuid


@dataclass
class PlatformIdentity:
    """Uniquely identifies a user/platform combination."""

    platform: str  # 'feishu', 'websocket', etc.
    user_id: str  # Platform-specific user identifier
    chat_id: str  # Conversation/channel ID
    thread_id: Optional[str] = None  # Thread ID for threaded conversations
    bot_id: Optional[str] = None  # Bot's own ID on this platform

    def session_key(self) -> str:
        """Generate unique session key for this identity."""
        parts = [self.platform, self.user_id, self.chat_id]
        if self.thread_id:
            parts.append(self.thread_id)
        return ":".join(parts)

    @classmethod
    def from_feishu(cls, open_id: str, chat_id: str, thread_id: Optional[str] = None) -> "PlatformIdentity":
        """Create identity from Feishu message."""
        return cls(platform="feishu", user_id=open_id, chat_id=chat_id, thread_id=thread_id)


@dataclass
class SessionContext:
    """
    Carries platform context through the message processing pipeline.

    Created per-message, this context allows the Agent to be platform-aware
    and format responses appropriately.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    platform: str = "unknown"
    identity: PlatformIdentity = None
    message_id: Optional[str] = None  # Platform's message ID
    parent_message_id: Optional[str] = None  # For reply chains
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Message content (populated during processing)
    content: Optional[str] = None
    raw_event: Optional[dict] = None

    # Response tracking
    response_sent: bool = False
    response_message_id: Optional[str] = None

    def __post_init__(self):
        if self.identity is None:
            self.identity = PlatformIdentity(
                platform=self.platform,
                user_id="unknown",
                chat_id="unknown",
            )

    @property
    def session_key(self) -> str:
        """Alias for identity.session_key()."""
        return self.identity.session_key()

    @property
    def is_direct_message(self) -> bool:
        """Check if this is a DM (not a group/channel)."""
        return self.identity.chat_id == self.identity.user_id

    def with_content(self, content: str) -> "SessionContext":
        """Chain method to set content."""
        self.content = content
        return self

    def with_raw_event(self, event: dict) -> "SessionContext":
        """Chain method to set raw event."""
        self.raw_event = event
        return self

    def mark_response_sent(self, message_id: Optional[str] = None) -> None:
        """Mark that a response was sent."""
        self.response_sent = True
        self.response_message_id = message_id

    def to_dict(self) -> dict:
        """Serialize to dict for logging."""
        return {
            "id": self.id,
            "platform": self.platform,
            "session_key": self.session_key,
            "message_id": self.message_id,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
