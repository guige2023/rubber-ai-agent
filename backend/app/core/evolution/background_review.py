"""
Background Reviewer - Fork agent for background self-evolution tasks.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ReviewTask:
    """A background review task."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str = ""  # "memory_review", "skill_review"
    prompt: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None


class BackgroundReviewer:
    """
    Manages background review tasks for self-evolution.

    Inspired by Hermes Agent's background review fork,
    this spawns isolated review tasks that run without
    blocking the main agent loop.
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        max_queue_size: int = 10,
    ):
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self._task_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._workers: list[asyncio.Task] = []
        self._active_reviews: dict[str, ReviewTask] = {}
        self._lock = asyncio.Lock()
        self._review_handler: Optional[Callable] = None

    def set_review_handler(
        self,
        handler: Callable[[ReviewTask], tuple[str, str]],
    ) -> None:
        """
        Set the handler that executes review tasks.

        The handler receives a ReviewTask and returns (result, error).

        The handler should use the memory and skill tools to perform reviews.
        """
        self._review_handler = handler

    async def start(self) -> None:
        """Start the background reviewer workers."""
        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.max_concurrent)
        ]
        logger.info(f"BackgroundReviewer started with {self.max_concurrent} workers")

    async def stop(self) -> None:
        """Stop the background reviewer workers."""
        self._running = False

        # Cancel all workers
        for worker in self._workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("BackgroundReviewer stopped")

    async def _worker(self, worker_id: int) -> None:
        """Worker coroutine that processes review tasks."""
        logger.debug(f"BackgroundReviewer worker {worker_id} started")

        while self._running:
            try:
                # Wait for task with timeout
                task = await asyncio.wait_for(
                    self._task_queue.get(),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if not self._running:
                break

            # Execute review
            await self._execute_review(task)

        logger.debug(f"BackgroundReviewer worker {worker_id} stopped")

    async def _execute_review(self, task: ReviewTask) -> None:
        """Execute a review task."""
        task.started_at = datetime.utcnow()

        async with self._lock:
            self._active_reviews[task.id] = task

        logger.info(f"Starting background review: {task.id} ({task.task_type})")

        try:
            if self._review_handler:
                result, error = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._review_handler(task),
                )
                task.result = result
                task.error = error
            else:
                # No handler set - simulate review
                await asyncio.sleep(1)  # Simulate work
                task.result = "Review completed (no handler)"
        except Exception as e:
            logger.error(f"Review {task.id} failed: {e}")
            task.error = str(e)

        task.completed_at = datetime.utcnow()

        async with self._lock:
            if task.id in self._active_reviews:
                del self._active_reviews[task.id]

        logger.info(
            f"Background review {task.id} completed in "
            f"{(task.completed_at - task.started_at).total_seconds():.1f}s"
        )

    async def submit_memory_review(
        self,
        session_context: dict,
        memory_prompt: str,
    ) -> str:
        """
        Submit a memory review task.

        Args:
            session_context: Context about the current session
            memory_prompt: Prompt for the memory review

        Returns:
            Task ID
        """
        task = ReviewTask(
            task_type="memory_review",
            prompt=memory_prompt,
        )
        task.context = session_context

        await self._task_queue.put(task)
        logger.info(f"Submitted memory review task: {task.id}")

        return task.id

    async def submit_skill_review(
        self,
        signals: list[dict],
        skill_prompt: str,
    ) -> str:
        """
        Submit a skill review task.

        Args:
            signals: Detected signals from nudge engine
            skill_prompt: Prompt for the skill review

        Returns:
            Task ID
        """
        task = ReviewTask(
            task_type="skill_review",
            prompt=skill_prompt,
        )
        task.signals = signals

        await self._task_queue.put(task)
        logger.info(f"Submitted skill review task: {task.id}")

        return task.id

    async def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get status of a review task."""
        async with self._lock:
            task = self._active_reviews.get(task_id)

        if task:
            return {
                "id": task.id,
                "task_type": task.task_type,
                "status": "running",
                "started_at": task.started_at.isoformat() if task.started_at else None,
            }

        return None

    def get_active_tasks(self) -> list[dict]:
        """Get all active review tasks."""
        # Note: This is a sync method but accesses async state
        # We use a simple list copy instead of locking for sync access
        tasks = list(self._active_reviews.values())

        return [
            {
                "id": t.id,
                "task_type": t.task_type,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "pending_items": self._task_queue.qsize(),
            }
            for t in tasks
        ]

    def get_status(self) -> dict:
        """Get background reviewer status."""
        return {
            "running": self._running,
            "active_reviews": len(self._active_reviews),
            "pending_in_queue": self._task_queue.qsize(),
            "max_concurrent": self.max_concurrent,
        }
