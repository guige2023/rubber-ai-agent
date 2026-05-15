"""
Tests for HeartbeatRunner integration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHeartbeatRunner:
    """Tests for HeartbeatRunner class."""

    def test_default_heartbeat_tasks(self):
        """Test DEFAULT_HEARTBEAT_TASKS has expected tasks."""
        from app.core.heartbeat.runner import DEFAULT_HEARTBEAT_TASKS

        task_names = [t["name"] for t in DEFAULT_HEARTBEAT_TASKS]
        assert "memory-review" in task_names
        assert "skill-check" in task_names
        assert "gateway-health" in task_names
        assert "unanswered-check" in task_names
        assert "missed-crons-check" in task_names
        assert "daily-stats" in task_names

    def test_health_check_tasks_included(self):
        """Test health check tasks are properly marked."""
        from app.core.heartbeat.runner import DEFAULT_HEARTBEAT_TASKS

        for task in DEFAULT_HEARTBEAT_TASKS:
            if task["name"] in ["gateway-health", "unanswered-check", "missed-crons-check", "daily-stats"]:
                assert task.get("health_check") is True

    def test_initial_state(self):
        """Test HeartbeatRunner initial state."""
        from app.core.heartbeat.runner import HeartbeatRunner

        runner = HeartbeatRunner()
        assert runner._running is False
        assert runner._task is None
        assert runner._heartbeat_handler is None

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test HeartbeatRunner start and stop."""
        from app.core.heartbeat.runner import HeartbeatRunner

        runner = HeartbeatRunner()
        await runner.start()
        assert runner._running is True

        await runner.stop()
        assert runner._running is False

    def test_set_heartbeat_handler(self):
        """Test setting heartbeat handler."""
        from app.core.heartbeat.runner import HeartbeatRunner

        runner = HeartbeatRunner()

        async def handler(tasks):
            pass

        runner.set_heartbeat_handler(handler)
        assert runner._heartbeat_handler is handler

    def test_get_status(self):
        """Test get_status returns expected structure."""
        from app.core.heartbeat.runner import HeartbeatRunner

        runner = HeartbeatRunner()
        status = runner.get_status()

        assert "running" in status
        assert "scheduler" in status
        assert "cooldown" in status
        assert "next_due_ms" in status
        assert "tasks_count" in status


class TestHeartbeatScheduler:
    """Tests for HeartbeatScheduler."""

    def test_initial_state(self):
        """Test HeartbeatScheduler initial state."""
        from app.core.heartbeat.scheduler import HeartbeatScheduler, HeartbeatConfig

        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(config)

        assert scheduler._schedule is not None

    def test_calculate_next_returns_positive(self):
        """Test calculate_next returns positive timestamp."""
        from app.core.heartbeat.scheduler import HeartbeatScheduler, HeartbeatConfig

        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(config)

        now_ms = 1000000
        next_ms = scheduler.calculate_next(now_ms)

        assert next_ms > now_ms


class TestCooldownManager:
    """Tests for CooldownManager."""

    def test_initial_state(self):
        """Test CooldownManager initial state."""
        from app.core.heartbeat.cooldown import CooldownManager, CooldownConfig

        config = CooldownConfig()
        manager = CooldownManager(config)

        assert manager._last_heartbeat is None
        assert manager._consecutive_count == 0
        assert manager._cooldown_until is None

    @pytest.mark.asyncio
    async def test_should_defer_initially_false(self):
        """Test should_defer returns False when no recent heartbeat."""
        from app.core.heartbeat.cooldown import CooldownManager

        manager = CooldownManager()
        should_defer, reason = await manager.should_defer()

        assert should_defer is False

    @pytest.mark.asyncio
    async def test_record_heartbeat(self):
        """Test record_heartbeat updates state."""
        from app.core.heartbeat.cooldown import CooldownManager

        manager = CooldownManager()
        await manager.record_heartbeat(triggered=True)

        assert manager._last_heartbeat is not None
        assert manager._consecutive_count == 1

    def test_get_status(self):
        """Test get_status returns expected structure."""
        from app.core.heartbeat.cooldown import CooldownManager

        manager = CooldownManager()
        status = manager.get_status()

        assert "min_interval_ms" in status
        assert "max_consecutive" in status
        assert "consecutive_count" in status
