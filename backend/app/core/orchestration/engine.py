"""
OrchestrationEngine - DAG-based task plan executor with pause/resume support.

Phase 0 scope:
- Build OrchestrationPlan from a list of TaskSteps
- Topological sorting: run all steps with satisfied dependencies
- Support pause (save checkpoint, stop loop) and resume (reload, continue)
- Checkpoint on every step completion
- Context propagation between steps
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from .checkpoint import CheckpointStore
from .models import (
    OrchestrationPlan,
    OrchestrationResult,
    PlanStatus,
    StepResult,
    StepStatus,
    TaskStep,
)

if TYPE_CHECKING:
    from .step_runner import StepRunner

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    """
    DAG-based task orchestration engine.

    Core loop:
    1. Topo-sort steps by depends_on
    2. Find all steps whose dependencies are satisfied (runnable)
    3. Run all runnable steps concurrently
    4. On each completion: update plan state, save checkpoint, trigger dependents
    5. Repeat until all steps done or a critical failure occurs

    Pause: signal _paused flag → current step completes → engine stops
    Resume: reload plan + shared_context from latest checkpoint → continue loop
    """

    def __init__(
        self,
        step_runner: "StepRunner",
        checkpoint_store: CheckpointStore,
    ) -> None:
        self._runner = step_runner
        self._checkpoint = checkpoint_store
        self._shared_context: dict[str, Any] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._paused = False
        self._canceled = False
        self._plan: Optional[OrchestrationPlan] = None
        self._lock = asyncio.Lock()
        self._step_completed_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_plan(
        self,
        plan: OrchestrationPlan,
        shared_context: Optional[dict[str, Any]] = None,
    ) -> OrchestrationResult:
        """
        Execute an OrchestrationPlan to completion.

        Args:
            plan: The plan to execute
            shared_context: Initial context (optional)

        Returns:
            OrchestrationResult with all step results and final status
        """
        self._plan = plan
        self._shared_context = shared_context or {}
        self._paused = False
        self._canceled = False

        plan.status = PlanStatus.RUNNING
        plan.updated_at = datetime.now(timezone.utc)

        step_results: list[StepResult] = []
        start_time = datetime.now(timezone.utc)

        self._running = True
        self._step_completed_event.clear()

        logger.info(f"OrchestrationEngine: starting plan {plan.plan_id} with {len(plan.steps)} steps")

        try:
            # Initial checkpoint: save plan structure
            self._save_full_checkpoint(plan, "plan_started")

            while self._running:
                if self._canceled:
                    plan.status = PlanStatus.CANCELED
                    break

                # --- Collect runnable steps ---
                runnable = plan.get_runnable_steps()
                if not runnable and not self._active_tasks:
                    # No more work and nothing running → plan complete
                    if plan.is_complete():
                        plan.status = PlanStatus.SUCCESS
                    elif plan.is_failed():
                        plan.status = PlanStatus.FAILED
                    else:
                        # Some steps stuck in non-terminal state (e.g. waiting on deps that failed)
                        plan.status = PlanStatus.FAILED
                    break

                if not runnable and self._active_tasks:
                    # Waiting for in-flight tasks - yield briefly
                    await asyncio.sleep(0.05)
                    continue

                # --- Launch runnable steps concurrently ---
                for step in runnable:
                    asyncio.create_task(self._execute_step(step, plan, step_results))

                # Yield control so in-flight tasks can start
                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info(f"OrchestrationEngine: plan {plan.plan_id} canceled")
            plan.status = PlanStatus.CANCELED
            self._running = False
            raise

        finally:
            # --- Finalize plan state ---
            self._running = False
            plan.updated_at = datetime.now(timezone.utc)
            if plan.status == PlanStatus.RUNNING:
                plan.status = PlanStatus.SUCCESS if plan.is_complete() else PlanStatus.FAILED
            if plan.status in (PlanStatus.SUCCESS, PlanStatus.FAILED, PlanStatus.CANCELED):
                plan.finished_at = datetime.now(timezone.utc)

            total_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            self._save_full_checkpoint(plan, plan.status.value)

            logger.info(
                f"OrchestrationEngine: plan {plan.plan_id} finished with status={plan.status.value}"
            )

        return OrchestrationResult(
            plan_id=plan.plan_id,
            success=plan.status == PlanStatus.SUCCESS,
            final_status=plan.status,
            step_results=step_results,
            shared_context=dict(self._shared_context),
            total_duration_ms=total_ms,
        )

    async def pause_plan(self, plan_id: str) -> None:
        """Signal the engine to pause after the current step completes."""
        async with self._lock:
            self._paused = True
            self._running = False
            if self._plan and self._plan.plan_id == plan_id:
                self._plan.status = PlanStatus.PAUSED
                self._save_full_checkpoint(self._plan, "paused")
        logger.info(f"OrchestrationEngine: pause requested for plan {plan_id}")

    async def resume_plan(
        self,
        plan: OrchestrationPlan,
    ) -> OrchestrationResult:
        """
        Resume a paused plan from the latest checkpoint.

        Restores shared_context from checkpoint and continues execution.
        """
        # Load latest checkpoint
        checkpoint = self._checkpoint.load_latest(plan.plan_id)
        if checkpoint:
            self._shared_context = dict(checkpoint.step_context)
            # Restore step statuses from checkpoint
            for step_id, status_str in checkpoint.plan_status.items():
                step = plan.get_step(step_id)
                if step:
                    try:
                        step.status = StepStatus(status_str)
                    except ValueError:
                        pass
            logger.info(f"OrchestrationEngine: resumed plan {plan.plan_id} from checkpoint step={checkpoint.step_id}")
        else:
            logger.warning(f"No checkpoint found for plan {plan.plan_id}, starting fresh")

        return await self.run_plan(plan, shared_context=self._shared_context)

    async def cancel_plan(self, plan_id: str) -> None:
        """Cancel running plan."""
        async with self._lock:
            self._canceled = True
            self._running = False
            # Cancel all active step tasks
            for task in self._active_tasks.values():
                if not task.done():
                    task.cancel()
        logger.info(f"OrchestrationEngine: cancel requested for plan {plan_id}")

    def get_shared_context(self) -> dict[str, Any]:
        """Return current shared_context snapshot."""
        return dict(self._shared_context)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        step: TaskStep,
        plan: OrchestrationPlan,
        step_results: list[StepResult],
    ) -> None:
        """Execute a single step and handle completion."""
        step_key = step.step_id
        self._active_tasks[step_key] = asyncio.current_task()

        session_id = plan.metadata.get("session_id", "orchestration")

        try:
            result = await self._runner.run_step(step, self._shared_context, session_id)
            step_results.append(result)

            # --- Propagate result into shared_context for dependents ---
            if result.success and result.output:
                self._shared_context[step.context_key] = result.output

            # --- Save checkpoint after every step completion ---
            self._save_full_checkpoint(plan, f"step_completed:{step.step_id}")

            # --- Check for plan completion ---
            if plan.is_complete():
                plan.status = PlanStatus.SUCCESS
                self._running = False

            if plan.is_failed():
                plan.status = PlanStatus.FAILED
                self._running = False

        except asyncio.CancelledError:
            step.status = StepStatus.PAUSED
            self._save_full_checkpoint(plan, f"step_paused:{step.step_id}")
            raise

        except Exception as e:
            logger.exception(f"Step {step.step_id} raised: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)

        finally:
            self._active_tasks.pop(step_key, None)
            self._step_completed_event.set()

    def _save_full_checkpoint(self, plan: OrchestrationPlan, reason: str) -> None:
        """Save a full plan checkpoint to the store."""
        if not plan.steps:
            return
        # Save checkpoint keyed to the last step that completed
        last_step = None
        for s in plan.steps:
            if s.status in (StepStatus.SUCCESS, StepStatus.FAILED):
                last_step = s

        if last_step is None:
            # No step has completed yet, use a dummy marker
            last_step = plan.steps[0]

        plan_status = {s.step_id: s.status.value for s in plan.steps}
        self._checkpoint.save_snapshot(
            plan_id=plan.plan_id,
            step_id=last_step.step_id,
            step_context=dict(self._shared_context),
            plan_status=plan_status,
        )
        logger.debug(f"Checkpoint saved: plan={plan.plan_id} step={last_step.step_id} reason={reason}")
