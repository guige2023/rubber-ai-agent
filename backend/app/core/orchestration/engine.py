"""
OrchestrationEngine - DAG-based task plan executor with checkpoint support.

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

    Execution model:
    1. Find all steps whose dependencies are satisfied (runnable)
    2. Run them concurrently using asyncio.gather()
    3. Repeat until all steps done or a critical failure occurs

    Pause: signal _paused → set plan status to PAUSED, save checkpoint
    Resume: reload from latest checkpoint, continue execution
    """

    def __init__(
        self,
        step_runner: "StepRunner",
        checkpoint_store: CheckpointStore,
    ) -> None:
        self._runner = step_runner
        self._checkpoint = checkpoint_store
        self._shared_context: dict[str, Any] = {}
        self._plan: Optional[OrchestrationPlan] = None
        self._running = False
        self._paused = False
        self._canceled = False
        self._lock = asyncio.Lock()

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

        logger.info(f"OrchestrationEngine: starting plan {plan.plan_id} with {len(plan.steps)} steps")

        try:
            self._save_full_checkpoint(plan, "plan_started")

            while self._running and not self._canceled:
                # --- Collect runnable steps (dependencies satisfied, not yet started) ---
                runnable = [
                    s for s in plan.steps
                    if s.status not in (StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.RUNNING)
                    and all(
                        plan.get_step(d) and plan.get_step(d).status == StepStatus.SUCCESS
                        for d in s.depends_on
                    )
                ]

                if not runnable:
                    # No more work to start
                    if plan.is_complete():
                        plan.status = PlanStatus.SUCCESS
                    elif plan.is_failed():
                        plan.status = PlanStatus.FAILED
                    else:
                        # Non-terminal state with no runnable steps → FAILED
                        plan.status = PlanStatus.FAILED
                    break

                # --- Execute all runnable steps concurrently and wait for completion ---
                tasks = [
                    asyncio.create_task(self._execute_step(step, plan, step_results))
                    for step in runnable
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                # Brief yield to allow event loop to process any remaining callbacks
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            logger.info(f"OrchestrationEngine: plan {plan.plan_id} canceled")
            plan.status = PlanStatus.CANCELED
            self._running = False
            raise

        finally:
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
        """Resume a paused plan from the latest checkpoint."""
        checkpoint = self._checkpoint.load_latest(plan.plan_id)
        if checkpoint:
            self._shared_context = dict(checkpoint.step_context)
            for step_id, status_str in checkpoint.plan_status.items():
                step = plan.get_step(step_id)
                if step:
                    try:
                        step.status = StepStatus(status_str)
                    except ValueError:
                        pass
            logger.info(
                f"OrchestrationEngine: resumed plan {plan.plan_id} "
                f"from checkpoint step={checkpoint.step_id}"
            )
        else:
            logger.warning(f"No checkpoint found for plan {plan.plan_id}, starting fresh")

        return await self.run_plan(plan, shared_context=self._shared_context)

    async def cancel_plan(self, plan_id: str) -> None:
        """Cancel a running plan."""
        async with self._lock:
            self._canceled = True
            self._running = False
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

        # Double-check guard: skip if already terminal
        if step.status in (StepStatus.SUCCESS, StepStatus.FAILED):
            return

        step.status = StepStatus.RUNNING
        session_id = plan.metadata.get("session_id", "orchestration")

        try:
            result = await self._runner.run_step(step, self._shared_context, session_id)

            # Now set step status — run_step no longer does this
            if result.success:
                step.status = StepStatus.SUCCESS
                step.finished_at = datetime.now(timezone.utc)
                step.result = result.output
            else:
                step.status = StepStatus.FAILED
                step.error = result.error
                step.finished_at = datetime.now(timezone.utc)

            step_results.append(result)

            if result.success and result.output:
                self._shared_context[step.context_key] = result.output

            self._save_full_checkpoint(plan, f"step_completed:{step.step_id}")

            if plan.is_complete():
                plan.status = PlanStatus.SUCCESS
                self._running = False
            elif plan.is_failed():
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

    def _save_full_checkpoint(self, plan: OrchestrationPlan, reason: str) -> None:
        """Save a full plan checkpoint."""
        if not plan.steps:
            return

        last_completed = next(
            (s for s in reversed(plan.steps) if s.status in (StepStatus.SUCCESS, StepStatus.FAILED)),
            plan.steps[0],
        )

        plan_status = {s.step_id: s.status.value for s in plan.steps}
        self._checkpoint.save_snapshot(
            plan_id=plan.plan_id,
            step_id=last_completed.step_id,
            step_context=dict(self._shared_context),
            plan_status=plan_status,
        )
        logger.debug(
            f"Checkpoint saved: plan={plan.plan_id} "
            f"step={last_completed.step_id} reason={reason}"
        )
