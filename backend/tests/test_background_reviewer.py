"""
Tests for BackgroundReviewer - async task processing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestReviewTask:
    """Tests for ReviewTask dataclass."""

    def test_review_task_default_id(self):
        """Test ReviewTask generates UUID by default."""
        from app.core.evolution.background_review import ReviewTask

        task = ReviewTask(task_type="test", prompt="test prompt")
        assert task.id is not None
        assert len(task.id) > 0

    def test_review_task_fields(self):
        """Test ReviewTask field values."""
        from app.core.evolution.background_review import ReviewTask

        task = ReviewTask(
            task_type="memory_review",
            prompt="Test prompt",
        )
        assert task.task_type == "memory_review"
        assert task.prompt == "Test prompt"
        assert task.started_at is None
        assert task.completed_at is None
        assert task.result is None
        assert task.error is None


class TestBackgroundReviewer:
    """Tests for BackgroundReviewer class."""

    def test_initial_state(self):
        """Test BackgroundReviewer initial state."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer()
        assert reviewer.max_concurrent == 2
        assert reviewer.max_queue_size == 10
        assert reviewer._running is False
        assert reviewer._workers == []

    @pytest.mark.asyncio
    async def test_start_creates_workers(self):
        """Test start creates worker tasks."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer(max_concurrent=2)
        await reviewer.start()
        assert reviewer._running is True
        assert len(reviewer._workers) == 2

        await reviewer.stop()
        assert reviewer._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_workers(self):
        """Test stop cancels running workers."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer(max_concurrent=2)
        await reviewer.start()
        assert reviewer._running is True

        await reviewer.stop()
        assert reviewer._running is False
        assert reviewer._workers == []

    @pytest.mark.asyncio
    async def test_submit_memory_review(self):
        """Test submitting memory review task."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer()
        await reviewer.start()

        task_id = await reviewer.submit_memory_review(
            session_context={"session_id": "test"},
            memory_prompt="Review memory",
        )

        assert task_id is not None
        assert reviewer._task_queue.qsize() == 1

        await reviewer.stop()

    @pytest.mark.asyncio
    async def test_submit_skill_review(self):
        """Test submitting skill review task."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer()
        await reviewer.start()

        task_id = await reviewer.submit_skill_review(
            signals=[{"type": "skill_creation"}],
            skill_prompt="Review skill",
        )

        assert task_id is not None
        assert reviewer._task_queue.qsize() == 1

        await reviewer.stop()

    def test_get_status(self):
        """Test get_status returns correct structure."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer()
        status = reviewer.get_status()

        assert "running" in status
        assert "active_reviews" in status
        assert "pending_in_queue" in status
        assert "max_concurrent" in status

    def test_get_active_tasks(self):
        """Test get_active_tasks returns list."""
        from app.core.evolution.background_review import BackgroundReviewer

        reviewer = BackgroundReviewer()
        tasks = reviewer.get_active_tasks()
        assert isinstance(tasks, list)
