"""
Tests for NudgeEngine - self-evolution signal detection.
"""

import pytest
from datetime import datetime


class TestNudgeConfig:
    """Tests for NudgeConfig."""

    def test_default_values(self):
        """Test NudgeConfig default values."""
        from app.core.evolution.nudge import NudgeConfig

        config = NudgeConfig()
        assert config.memory_nudge_interval == 10
        assert config.skill_nudge_interval == 10
        assert config.min_confidence_threshold == 0.6
        assert config.complex_workflow_threshold == 5
        assert config.user_correction_keywords is not None
        assert len(config.user_correction_keywords) > 0


class TestNudgeEngine:
    """Tests for NudgeEngine class."""

    def test_initial_state(self):
        """Test NudgeEngine initial state."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        assert engine._turn_count == 0
        assert engine._tool_iteration_count == 0
        assert engine._pending_signals == []

    def test_on_user_turn_increments_counter(self):
        """Test on_user_turn increments turn counter."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        initial_count = engine._turn_count

        engine.on_user_turn()
        assert engine._turn_count == initial_count + 1

    def test_on_user_turn_returns_true_at_interval(self):
        """Test on_user_turn returns True when interval reached."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        engine._turn_count = 9  # One away from threshold

        result = engine.on_user_turn()
        assert result is True
        assert engine._turn_count == 0  # Reset after triggering

    def test_on_tool_iteration_increments_counter(self):
        """Test on_tool_iteration increments counter."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        initial_count = engine._tool_iteration_count

        engine.on_tool_iteration()
        assert engine._tool_iteration_count == initial_count + 1

    def test_reset_counters(self):
        """Test reset_counters resets both counters."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        engine._turn_count = 5
        engine._tool_iteration_count = 7

        engine.reset_counters()
        assert engine._turn_count == 0
        assert engine._tool_iteration_count == 0

    def test_detect_signals_no_signals(self):
        """Test detect_signals returns empty when no signals present."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        signals = engine.detect_signals(
            user_message="Hello, how are you?",
            agent_response="I'm doing well, thank you!",
            tool_calls=[],
        )
        assert len(signals) == 0

    def test_detect_signals_user_correction(self):
        """Test detect_signals detects user correction."""
        from app.core.evolution.nudge import NudgeEngine, NudgeType

        engine = NudgeEngine()
        signals = engine.detect_signals(
            user_message="Don't do that, it's wrong",
            agent_response="I understand",
            tool_calls=[],
        )
        assert len(signals) > 0
        assert signals[0].nudge_type == NudgeType.SKILL_IMPROVEMENT

    def test_detect_signals_complex_workflow(self):
        """Test detect_signals detects complex workflow."""
        from app.core.evolution.nudge import NudgeEngine, NudgeType

        engine = NudgeEngine()
        tool_calls = [
            {"tool": "tool1"},
            {"tool": "tool2"},
            {"tool": "tool3"},
            {"tool": "tool4"},
            {"tool": "tool5"},
            {"tool": "tool6"},
        ]
        signals = engine.detect_signals(
            user_message="Do something complex",
            agent_response="Done!",
            tool_calls=tool_calls,
        )
        assert len(signals) > 0
        assert signals[0].nudge_type == NudgeType.SKILL_CREATION

    def test_get_status(self):
        """Test get_status returns correct structure."""
        from app.core.evolution.nudge import NudgeEngine

        engine = NudgeEngine()
        status = engine.get_status()

        assert "turn_count" in status
        assert "tool_iteration_count" in status
        assert "memory_nudge_interval" in status
        assert "skill_nudge_interval" in status


class TestNudgeSignal:
    """Tests for NudgeSignal dataclass."""

    def test_nudge_signal_creation(self):
        """Test NudgeSignal creation."""
        from app.core.evolution.nudge import NudgeSignal, NudgeType

        signal = NudgeSignal(
            nudge_type=NudgeType.SKILL_CREATION,
            confidence=0.8,
            evidence="Test evidence",
        )
        assert signal.nudge_type == NudgeType.SKILL_CREATION
        assert signal.confidence == 0.8
        assert signal.evidence == "Test evidence"
        assert signal.detected_at is not None
