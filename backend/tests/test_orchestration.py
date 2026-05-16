"""
Tests for the orchestration module (Phase 0).

Covers:
- models: TaskStep, OrchestrationPlan DAG behavior
- CheckpointStore: save/load/list/delete
- OrchestrationEngine: sequential, parallel, pause/resume
- StepRunner: template substitution, context propagation
"""

import asyncio
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.orchestration import (
    CheckpointStore,
    OrchestrationEngine,
    OrchestrationPlan,
    OrchestrationResult,
    PlanStatus,
    StepResult,
    StepRunner,
    StepStatus,
    TaskStep,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_db(tmp_path):
    """Temp SQLite DB for CheckpointStore."""
    return tmp_path / "test_orchestration.db"


@pytest.fixture
def checkpoint_store(temp_db):
    return CheckpointStore(db_path=temp_db)


@pytest.fixture
def mock_cluster_manager():
    """Mock AgentClusterManager."""
    manager = MagicMock()
    manager.invoke = AsyncMock()
    return manager


@pytest.fixture
def mock_agent_manager():
    """Mock AgentManager."""
    manager = MagicMock()
    manager.build_skill_agent = MagicMock()
    return manager


@pytest.fixture
def step_runner(mock_cluster_manager, mock_agent_manager, checkpoint_store):
    return StepRunner(
        cluster_manager=mock_cluster_manager,
        agent_manager=mock_agent_manager,
        checkpoint_store=checkpoint_store,
    )


@pytest.fixture
def engine(step_runner, checkpoint_store):
    return OrchestrationEngine(
        step_runner=step_runner,
        checkpoint_store=checkpoint_store,
    )


# =============================================================================
# Model Tests
# =============================================================================

class TestTaskStep:
    def test_default_context_key(self):
        step = TaskStep(step_id="s1", agent_name="coder", instruction="do it")
        assert step.context_key == "step_result_s1"

    def test_to_dict_roundtrip(self):
        step = TaskStep(
            step_id="s1",
            agent_name="coder",
            instruction="do it",
            status=StepStatus.RUNNING,
            depends_on=["s0"],
        )
        d = step.to_dict()
        restored = TaskStep.from_dict(d)
        assert restored.step_id == "s1"
        assert restored.agent_name == "coder"
        assert restored.status == StepStatus.RUNNING
        assert restored.depends_on == ["s0"]


class TestOrchestrationPlan:
    def test_create(self):
        plan = OrchestrationPlan.create("Test Plan")
        assert plan.plan_id.startswith("plan_")
        assert plan.title == "Test Plan"
        assert plan.status == PlanStatus.DRAFT

    def test_get_runnable_no_deps(self):
        plan = OrchestrationPlan.create("Test")
        plan.steps = [
            TaskStep(step_id="s1", agent_name="coder", instruction="step 1"),
            TaskStep(step_id="s2", agent_name="reviewer", instruction="step 2"),
        ]
        runnable = plan.get_runnable_steps()
        assert len(runnable) == 2

    def test_get_runnable_waits_for_deps(self):
        plan = OrchestrationPlan.create("Test")
        plan.steps = [
            TaskStep(step_id="s1", agent_name="coder", instruction="step 1"),
            TaskStep(
                step_id="s2",
                agent_name="reviewer",
                instruction="step 2",
                depends_on=["s1"],
            ),
        ]
        runnable = plan.get_runnable_steps()
        assert len(runnable) == 1
        assert runnable[0].step_id == "s1"

    def test_get_runnable_all_deps_satisfied(self):
        plan = OrchestrationPlan.create("Test")
        plan.steps = [
            TaskStep(step_id="s1", agent_name="coder", instruction="step 1", status=StepStatus.SUCCESS),
            TaskStep(
                step_id="s2",
                agent_name="reviewer",
                instruction="step 2",
                depends_on=["s1"],
            ),
        ]
        runnable = plan.get_runnable_steps()
        # Both s1 (SUCCESS) and s2 (PENDING, deps satisfied) are runnable:
        # get_runnable_steps does not filter by SUCCESS status — engine guards
        # against re-execution of terminal steps inside _execute_step.
        assert len(runnable) == 2
        assert {s.step_id for s in runnable} == {"s1", "s2"}

    def test_is_complete(self):
        plan = OrchestrationPlan.create("Test")
        plan.steps = [
            TaskStep(step_id="s1", agent_name="coder", instruction="step 1", status=StepStatus.SUCCESS),
            TaskStep(step_id="s2", agent_name="reviewer", instruction="step 2", status=StepStatus.SUCCESS),
        ]
        assert plan.is_complete() is True

    def test_is_not_complete(self):
        plan = OrchestrationPlan.create("Test")
        plan.steps = [
            TaskStep(step_id="s1", agent_name="coder", instruction="step 1", status=StepStatus.SUCCESS),
            TaskStep(step_id="s2", agent_name="reviewer", instruction="step 2", status=StepStatus.PENDING),
        ]
        assert plan.is_complete() is False

    def test_get_status_summary(self):
        plan = OrchestrationPlan.create("Test")
        plan.steps = [
            TaskStep(step_id="s1", agent_name="coder", instruction="step 1", status=StepStatus.SUCCESS),
            TaskStep(step_id="s2", agent_name="reviewer", instruction="step 2", status=StepStatus.RUNNING),
            TaskStep(step_id="s3", agent_name="test", instruction="step 3", status=StepStatus.PENDING),
        ]
        summary = plan.get_status_summary()
        assert summary["success"] == 1
        assert summary["running"] == 1
        assert summary["pending"] == 1


# =============================================================================
# CheckpointStore Tests
# =============================================================================

class TestCheckpointStore:
    def test_save_and_load(self, checkpoint_store):
        from app.core.orchestration import Checkpoint

        cp = Checkpoint(
            plan_id="plan_abc",
            step_id="s1",
            step_context={"x": 1},
            plan_status={"s1": "success"},
        )
        checkpoint_store.save(cp)

        loaded = checkpoint_store.load("plan_abc", "s1")
        assert loaded is not None
        assert loaded.plan_id == "plan_abc"
        assert loaded.step_id == "s1"
        assert loaded.step_context == {"x": 1}
        assert loaded.plan_status == {"s1": "success"}

    def test_load_latest(self, checkpoint_store):
        from app.core.orchestration import Checkpoint

        cp1 = Checkpoint(
            plan_id="plan_abc",
            step_id="s1",
            step_context={"v": 1},
            plan_status={"s1": "running"},
        )
        cp2 = Checkpoint(
            plan_id="plan_abc",
            step_id="s2",
            step_context={"v": 2},
            plan_status={"s1": "success", "s2": "running"},
        )
        checkpoint_store.save(cp1)
        # Small delay to ensure different timestamps
        checkpoint_store.save(cp2)

        latest = checkpoint_store.load_latest("plan_abc")
        assert latest is not None
        assert latest.step_id == "s2"
        assert latest.step_context == {"v": 2}

    def test_list_for_plan(self, checkpoint_store):
        from app.core.orchestration import Checkpoint

        for i in range(3):
            cp = Checkpoint(
                plan_id="plan_list",
                step_id=f"s{i}",
                step_context={"i": i},
                plan_status={},
            )
            checkpoint_store.save(cp)

        checkpoints = checkpoint_store.list_for_plan("plan_list")
        assert len(checkpoints) == 3

    def test_delete_for_plan(self, checkpoint_store):
        from app.core.orchestration import Checkpoint

        cp = Checkpoint(
            plan_id="plan_del",
            step_id="s1",
            step_context={},
            plan_status={},
        )
        checkpoint_store.save(cp)
        checkpoint_store.delete_for_plan("plan_del")

        assert checkpoint_store.load_latest("plan_del") is None

    def test_load_nonexistent(self, checkpoint_store):
        assert checkpoint_store.load("plan_xxx", "s1") is None


# =============================================================================
# StepRunner Tests
# =============================================================================

class TestStepRunner:
    def test_substitute_context(self, step_runner):
        ctx = {"foo": "bar", "num": 42, "nested": {"a": 1}}
        result = step_runner._substitute_context("hello $foo and $num", ctx)
        assert result == "hello bar and 42"

    def test_substitute_context_missing_key(self, step_runner):
        ctx = {"foo": "bar"}
        result = step_runner._substitute_context("hello $missing", ctx)
        assert result == "hello $missing"

    def test_substitute_context_escaped_dollar(self, step_runner):
        ctx = {"foo": "bar"}
        result = step_runner._substitute_context("price is $$100", ctx)
        assert result == "price is $100"

    def test_substitute_context_no_context_refs(self, step_runner):
        ctx = {}
        result = step_runner._substitute_context("plain text", ctx)
        assert result == "plain text"

    @pytest.mark.asyncio
    async def test_run_step_agent_cluster(self, step_runner, mock_cluster_manager):
        """Step with a regular agent_name → cluster.invoke_skill_toolkit()"""
        mock_cluster_manager.invoke_skill_toolkit = AsyncMock(return_value={"code": "x = 1"})

        step = TaskStep(
            step_id="s1",
            agent_name="coder",
            instruction="generate hello world",
        )

        result = await step_runner.run_step(step, {}, "test-session")

        assert result.success is True
        # run_step no longer modifies step.status — status is set by engine
        assert step.status == StepStatus.PENDING
        # _run_agent_via_skilltool returns the dict directly
        assert result.output["code"] == "x = 1"
        mock_cluster_manager.invoke_skill_toolkit.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_step_uses_context_in_instruction(self, step_runner, mock_cluster_manager):
        """$variable substitution in instruction before calling SkillToolkit"""
        mock_cluster_manager.invoke_skill_toolkit = AsyncMock(return_value={})

        step = TaskStep(
            step_id="s1",
            agent_name="coder",
            instruction="write $language code",
        )
        shared_ctx = {"language": "Python"}

        await step_runner.run_step(step, shared_ctx, "test-session")

        # The instruction passed to invoke_skill_toolkit should have $language substituted
        call_args = mock_cluster_manager.invoke_skill_toolkit.call_args
        instruction_passed = call_args.kwargs.get("instruction") or call_args[1].get("instruction")
        assert instruction_passed == "write Python code"


# =============================================================================
# OrchestrationEngine Tests
# =============================================================================

class TestOrchestrationEngine:
    @pytest.mark.asyncio
    async def test_sequential_steps(self, engine, step_runner, checkpoint_store):
        """Two steps where s2 depends on s1 → sequential execution"""
        call_log: list[str] = []

        async def mock_run_step(step, shared_ctx, session_id):
            call_log.append(f"start:{step.step_id}")
            await asyncio.sleep(0.01)
            step.status = StepStatus.SUCCESS
            step.finished_at = datetime.now(timezone.utc)
            step.result = {"done": True}
            call_log.append(f"end:{step.step_id}")
            return StepResult(step_id=step.step_id, success=True, output={"done": True})

        # Patch step_runner.run_step directly
        with patch.object(step_runner, "run_step", side_effect=mock_run_step):
            plan = OrchestrationPlan.create("Sequential Test")
            plan.steps = [
                TaskStep(step_id="s1", agent_name="coder", instruction="step 1"),
                TaskStep(step_id="s2", agent_name="reviewer", instruction="step 2", depends_on=["s1"]),
            ]
            plan.metadata["session_id"] = "test-session"

            result = await engine.run_plan(plan)

        assert result.success is True
        assert result.final_status == PlanStatus.SUCCESS
        assert len(result.step_results) == 2
        # s2 should not start until s1 ends
        s1_start = call_log.index("start:s1")
        s1_end = call_log.index("end:s1")
        s2_start = call_log.index("start:s2")
        assert s1_end < s2_start, "s2 should start after s1 ends"

    @pytest.mark.asyncio
    async def test_parallel_independent_steps(self, engine, step_runner):
        """Two steps with no dependencies → run concurrently"""
        start_times: dict[str, float] = {}
        end_times: dict[str, float] = {}
        barrier = asyncio.Barrier(2)

        async def mock_run_step(step, shared_ctx, session_id):
            start_times[step.step_id] = asyncio.get_event_loop().time()
            await barrier.wait()  # Both start together
            await asyncio.sleep(0.02)
            step.status = StepStatus.SUCCESS
            step.finished_at = datetime.now(timezone.utc)
            step.result = {"done": True}
            end_times[step.step_id] = asyncio.get_event_loop().time()
            return StepResult(step_id=step.step_id, success=True, output={"done": True})

        with patch.object(step_runner, "run_step", side_effect=mock_run_step):
            plan = OrchestrationPlan.create("Parallel Test")
            plan.steps = [
                TaskStep(step_id="p1", agent_name="research", instruction="research"),
                TaskStep(step_id="p2", agent_name="analytics", instruction="analyze"),
            ]
            plan.metadata["session_id"] = "test-session"

            result = await engine.run_plan(plan)

        assert result.success is True
        # Both should start within a short window (truly parallel)
        delta = abs(start_times["p1"] - start_times["p2"])
        assert delta < 0.05, f"Steps should start nearly together, delta={delta}"

    @pytest.mark.asyncio
    async def test_plan_pause_and_resume(self, engine, step_runner, checkpoint_store):
        """Pause after step 1, resume continues from step 2"""
        call_log: list[str] = []

        original_run_step = step_runner.run_step

        async def tracking_run_step(step, shared_ctx, session_id):
            call_log.append(step.step_id)
            step.status = StepStatus.SUCCESS
            step.finished_at = datetime.now(timezone.utc)
            step.result = {"done": True}
            return StepResult(step_id=step.step_id, success=True, output={"done": True})

        with patch.object(step_runner, "run_step", side_effect=tracking_run_step):
            plan = OrchestrationPlan.create("Pause Test")
            plan.steps = [
                TaskStep(step_id="s1", agent_name="coder", instruction="step 1"),
                TaskStep(step_id="s2", agent_name="reviewer", instruction="step 2"),
            ]
            plan.metadata["session_id"] = "test-session"

            # Run partial: only s1 completes
            plan.steps[0].status = StepStatus.SUCCESS
            plan.steps[0].result = {"done": True}
            plan.steps[0].finished_at = datetime.now(timezone.utc)

            # Save checkpoint at s1
            checkpoint_store.save_snapshot(
                plan_id=plan.plan_id,
                step_id="s1",
                step_context={"s1": {"done": True}},
                plan_status={"s1": "success", "s2": "pending"},
            )

            # Resume plan
            result = await engine.resume_plan(plan)

        assert result.success is True
        # s1 was already SUCCESS → NOT re-run (get_runnable_steps skips SUCCESS steps)
        assert "s1" not in call_log, f"s1 should NOT be re-run, got call_log={call_log}"
        # s2 was run during resume
        assert "s2" in call_log

    @pytest.mark.asyncio
    async def test_all_steps_fail(self, engine, step_runner):
        """All steps fail → plan FAILED"""
        async def failing_step(step, shared_ctx, session_id):
            step.status = StepStatus.FAILED
            step.error = "intentional failure"
            step.finished_at = datetime.now(timezone.utc)
            return StepResult(step_id=step.step_id, success=False, error="intentional failure")

        with patch.object(step_runner, "run_step", side_effect=failing_step):
            plan = OrchestrationPlan.create("Fail Test")
            plan.steps = [
                TaskStep(step_id="f1", agent_name="coder", instruction="fail this"),
            ]
            plan.metadata["session_id"] = "test-session"

            result = await engine.run_plan(plan)

        assert result.success is False
        assert result.final_status == PlanStatus.FAILED

    @pytest.mark.asyncio
    async def test_step_result_in_context(self, engine, step_runner):
        """Step 1 result is accessible as $step_result_s1 in step 2"""
        ctx_captures: list[dict] = []

        async def capturing_run_step(step, shared_ctx, session_id):
            ctx_captures.append(dict(shared_ctx))
            step.status = StepStatus.SUCCESS
            step.finished_at = datetime.now(timezone.utc)
            step.result = {"value": step.step_id}
            return StepResult(step_id=step.step_id, success=True, output={"value": step.step_id})

        with patch.object(step_runner, "run_step", side_effect=capturing_run_step):
            plan = OrchestrationPlan.create("Context Test")
            plan.steps = [
                TaskStep(step_id="c1", agent_name="coder", instruction="step 1", context_key="c1_result"),
                TaskStep(step_id="c2", agent_name="reviewer", instruction="step 2", depends_on=["c1"]),
            ]
            plan.metadata["session_id"] = "test-session"

            result = await engine.run_plan(plan)

        assert result.success is True
        # c2's shared_context should contain c1's result
        assert len(ctx_captures) == 2
        assert ctx_captures[1].get("c1_result") is not None


# =============================================================================
# Integration: Checkpoint + Engine
# =============================================================================

class TestCheckpointIntegration:
    @pytest.mark.asyncio
    async def test_checkpoint_saved_on_step_complete(self, engine, step_runner, checkpoint_store):
        """Verify checkpoint is persisted after each step"""
        async def quick_step(step, shared_ctx, session_id):
            step.status = StepStatus.SUCCESS
            step.finished_at = datetime.now(timezone.utc)
            step.result = {"ok": True}
            return StepResult(step_id=step.step_id, success=True, output={"ok": True})

        with patch.object(step_runner, "run_step", side_effect=quick_step):
            plan = OrchestrationPlan.create("Checkpoint Test")
            plan.steps = [
                TaskStep(step_id="cp1", agent_name="coder", instruction="cp step 1"),
            ]
            plan.metadata["session_id"] = "test-session"

            await engine.run_plan(plan)

        # Verify checkpoint was saved
        cp = checkpoint_store.load_latest(plan.plan_id)
        assert cp is not None
        assert cp.step_id == "cp1"
        assert cp.step_context == {"step_result_cp1": {"ok": True}}
