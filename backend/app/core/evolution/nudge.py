"""
Nudge Engine - Detects conditions that should trigger self-evolution.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class NudgeType(str, Enum):
    """Types of nudge events."""

    MEMORY_REVIEW = "memory_review"  # Review conversation for user preferences
    SKILL_CREATION = "skill_creation"  # Create/update skills
    POLICY_INDUCTION = "policy_induction"  # Induce new policies
    SKILL_IMPROVEMENT = "skill_improvement"  # Improve existing skills


@dataclass
class NudgeSignal:
    """
    A detected signal that may trigger evolution.

    Signals are collected observations about the conversation
    that might warrant agent self-modification.
    """

    nudge_type: NudgeType
    confidence: float  # 0-1 confidence that this warrants action
    evidence: str  # What was observed
    context: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NudgeConfig:
    """Configuration for nudge detection."""

    memory_nudge_interval: int = 10  # Turns between memory reviews
    skill_nudge_interval: int = 10  # Tool iterations between skill reviews
    min_confidence_threshold: float = 0.6  # Minimum confidence to trigger
    user_correction_keywords: list[str] = None  # Keywords indicating user correction
    frustration_keywords: list[str] = None  # Keywords indicating frustration
    complex_workflow_threshold: int = 5  # Tool calls to consider complex


class NudgeEngine:
    """
    Detects conditions that should trigger self-evolution.

    Monitors:
    - User corrections ("don't do X", "stop")
    - Workarounds discovered for errors
    - Complex workflows completed successfully
    - Frustration signals
    - Knowledge gaps
    """

    def __init__(self, config: Optional[NudgeConfig] = None):
        self.config = config or NudgeConfig()
        if self.config.user_correction_keywords is None:
            self.config.user_correction_keywords = [
                "don't",
                "stop",
                "not like that",
                "wrong",
                "incorrect",
                "fix",
                "change",
                "instead",
                "try again",
                "别",
                "不要",
                "不对",
            ]
        if self.config.frustration_keywords is None:
            self.config.frustration_keywords = [
                "frustrated",
                "annoying",
                "takes too long",
                "重复",
                "太慢",
                "烦人",
            ]

        self._turn_count: int = 0
        self._tool_iteration_count: int = 0
        self._last_memory_nudge: Optional[datetime] = None
        self._last_skill_nudge: Optional[datetime] = None
        self._pending_signals: list[NudgeSignal] = []

    def reset_counters(self) -> None:
        """Reset turn and tool counters."""
        self._turn_count = 0
        self._tool_iteration_count = 0

    def on_user_turn(self) -> bool:
        """
        Called after each user turn.

        Returns:
            True if memory nudge should be triggered
        """
        self._turn_count += 1

        if self._turn_count >= self.config.memory_nudge_interval:
            self._turn_count = 0
            self._last_memory_nudge = datetime.utcnow()
            return True

        return False

    def on_tool_iteration(self) -> bool:
        """
        Called after each tool use iteration.

        Returns:
            True if skill nudge should be triggered
        """
        self._tool_iteration_count += 1

        if self._tool_iteration_count >= self.config.skill_nudge_interval:
            self._tool_iteration_count = 0
            self._last_skill_nudge = datetime.utcnow()
            return True

        return False

    def detect_signals(
        self,
        user_message: str,
        agent_response: str,
        tool_calls: list[dict],
        errors_overcome: list[str] = None,
    ) -> list[NudgeSignal]:
        """
        Analyze conversation for evolution signals.

        Args:
            user_message: The user's message
            agent_response: The agent's response
            tool_calls: List of tool calls made
            errors_overcome: Any errors that were overcome

        Returns:
            List of detected signals
        """
        signals = []

        # Check for user corrections
        correction_signal = self._check_user_corrections(user_message)
        if correction_signal:
            signals.append(correction_signal)

        # Check for frustration
        frustration_signal = self._check_frustration(user_message)
        if frustration_signal:
            signals.append(frustration_signal)

        # Check for complex workflow completion
        if len(tool_calls) >= self.config.complex_workflow_threshold:
            workflow_signal = self._detect_complex_workflow(
                tool_calls, agent_response
            )
            if workflow_signal:
                signals.append(workflow_signal)

        # Check for errors overcome
        if errors_overcome:
            error_signal = self._detect_error_workarounds(errors_overcome)
            if error_signal:
                signals.append(error_signal)

        # Check for knowledge gaps (agent saying it doesn't know)
        knowledge_signal = self._detect_knowledge_gaps(agent_response)
        if knowledge_signal:
            signals.append(knowledge_signal)

        return signals

    def _check_user_corrections(self, user_message: str) -> Optional[NudgeSignal]:
        """Check if user is correcting the agent."""
        message_lower = user_message.lower()

        for keyword in self.config.user_correction_keywords:
            if keyword.lower() in message_lower:
                return NudgeSignal(
                    nudge_type=NudgeType.SKILL_IMPROVEMENT,
                    confidence=0.8,
                    evidence=f"User correction detected: '{keyword}'",
                    context={"keyword": keyword, "message": user_message},
                )

        return None

    def _check_frustration(self, user_message: str) -> Optional[NudgeSignal]:
        """Check for user frustration signals."""
        message_lower = user_message.lower()

        for keyword in self.config.frustration_keywords:
            if keyword.lower() in message_lower:
                return NudgeSignal(
                    nudge_type=NudgeType.SKILL_IMPROVEMENT,
                    confidence=0.7,
                    evidence=f"Frustration signal detected: '{keyword}'",
                    context={"keyword": keyword, "message": user_message},
                )

        return None

    def _detect_complex_workflow(
        self,
        tool_calls: list[dict],
        response: str,
    ) -> Optional[NudgeSignal]:
        """Detect successful complex workflow that could become a skill."""
        if len(tool_calls) >= self.config.complex_workflow_threshold:
            tool_names = [tc.get("tool", tc.get("name", "")) for tc in tool_calls]
            return NudgeSignal(
                nudge_type=NudgeType.SKILL_CREATION,
                confidence=0.7,
                evidence=f"Complex workflow completed: {len(tool_calls)} tools",
                context={
                    "tool_count": len(tool_calls),
                    "tools": tool_names,
                    "workflow_summary": response[:200] if response else "",
                },
            )

        return None

    def _detect_error_workarounds(
        self,
        errors_overcome: list[str],
    ) -> Optional[NudgeSignal]:
        """Detect successful error workarounds."""
        if errors_overcome:
            return NudgeSignal(
                nudge_type=NudgeType.SKILL_CREATION,
                confidence=0.85,
                evidence=f"Error workaround discovered: {len(errors_overcome)} errors overcome",
                context={"errors": errors_overcome},
            )

        return None

    def _detect_knowledge_gaps(self, agent_response: str) -> Optional[NudgeSignal]:
        """Detect when agent indicates lack of knowledge."""
        knowledge_gap_phrases = [
            "i don't know",
            "i'm not sure",
            "i cannot find",
            "doesn't appear to be",
            "no information about",
            "不知道",
            "不确定",
        ]

        response_lower = agent_response.lower()
        for phrase in knowledge_gap_phrases:
            if phrase.lower() in response_lower:
                return NudgeSignal(
                    nudge_type=NudgeType.MEMORY_REVIEW,
                    confidence=0.6,
                    evidence=f"Knowledge gap detected: '{phrase}'",
                    context={"phrase": phrase},
                )

        return None

    def get_pending_signals(self) -> list[NudgeSignal]:
        """Get all pending signals."""
        return self._pending_signals.copy()

    def clear_signals(self) -> None:
        """Clear all pending signals."""
        self._pending_signals.clear()

    def get_status(self) -> dict:
        """Get nudge engine status."""
        return {
            "turn_count": self._turn_count,
            "tool_iteration_count": self._tool_iteration_count,
            "memory_nudge_interval": self.config.memory_nudge_interval,
            "skill_nudge_interval": self.config.skill_nudge_interval,
            "pending_signals": len(self._pending_signals),
            "last_memory_nudge": (
                self._last_memory_nudge.isoformat()
                if self._last_memory_nudge
                else None
            ),
            "last_skill_nudge": (
                self._last_skill_nudge.isoformat()
                if self._last_skill_nudge
                else None
            ),
        }
