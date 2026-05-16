"""
StepRunner - executes individual TaskSteps using agent_cluster or SkillToolkit.

Phase 0 bridges to existing infrastructure:
- "skill:xxx" → SkillToolkit.run_skill (real LLM calls via pydantic_ai sub-agent)
- Other agents → cluster_manager.invoke (stub implementation in Phase 0)
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from .checkpoint import CheckpointStore
from .models import StepResult, StepStatus, TaskStep

if TYPE_CHECKING:
    from app.core.agent_cluster.base import AgentContext
    from app.core.agent_cluster.manager import AgentClusterManager

logger = logging.getLogger(__name__)

# Pattern: "skill:web-search" → skill_name="web-search"
SKILL_PREFIX = "skill:"
_SKILL_PATTERN = re.compile(r"^skill:(\w[\w\-]*)$")


def _parse_agent_name(agent_name: str) -> tuple[str, Optional[str]]:
    """Parse agent_name into (agent_type, skill_name)."""
    m = _SKILL_PATTERN.match(agent_name.strip())
    if m:
        return "skill", m.group(1)
    return agent_name, None


class StepRunner:
    """
    Executes individual TaskSteps.

    Phase 0 strategy:
    - skill:xxx → call SkillToolkit.run_skill() via agent_manager
    - other agents → call cluster_manager.invoke() (stub agents, but full machinery works)

    Each step execution:
    1. Loads checkpoint if resuming
    2. Injects shared_context variables into instruction
    3. Runs the step
    4. Saves checkpoint on completion
    """

    def __init__(
        self,
        cluster_manager: "AgentClusterManager",
        agent_manager: Any,  # AgentManager from agent_manager.py
        checkpoint_store: CheckpointStore,
    ) -> None:
        self._cluster = cluster_manager
        self._agent_manager = agent_manager
        self._checkpoint = checkpoint_store

    async def run_step(
        self,
        step: TaskStep,
        shared_context: dict[str, Any],
        session_id: str,
    ) -> StepResult:
        """
        Execute a single TaskStep and return its result.

        Args:
            step: The step to execute
            shared_context: Shared variable store (previous step outputs)
            session_id: Current session ID for skill runs

        Returns:
            StepResult with success/output or failure/error
        """
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(timezone.utc)

        # --- Template substitution: $key → value in instruction ---
        instruction = self._substitute_context(step.instruction, shared_context)

        try:
            agent_type, skill_name = _parse_agent_name(step.agent_name)

            if agent_type == "skill" and skill_name:
                # === PATH 1: SkillToolkit (real LLM calls) ===
                result_data = await self._run_skill_step(skill_name, instruction, session_id)
            else:
                # === PATH 2: agent_cluster invoke (stub in Phase 0) ===
                result_data = await self._run_agent_step(agent_type, instruction)

            step.status = StepStatus.SUCCESS
            step.finished_at = datetime.now(timezone.utc)
            step.result = result_data

            # Update shared_context with this step's output
            shared_context[step.context_key] = result_data

            # Save checkpoint after successful completion
            if step.checkpoint_enabled:
                self._save_checkpoint(step, shared_context)

            return StepResult(
                step_id=step.step_id,
                success=True,
                output=result_data,
                duration_ms=int(
                    (step.finished_at - step.started_at).total_seconds() * 1000
                ),
            )

        except Exception as e:
            logger.exception(f"Step {step.step_id} failed: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.finished_at = datetime.now(timezone.utc)

            return StepResult(
                step_id=step.step_id,
                success=False,
                error=str(e),
                duration_ms=int(
                    (step.finished_at - step.started_at).total_seconds() * 1000
                ),
            )

    async def _run_skill_step(
        self,
        skill_name: str,
        instruction: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Run a skill via SkillToolkit.

        SkillToolkit.run_skill() needs:
        - RunContext[AgentDeps] → we construct from deps
        - skill_name
        - instruction

        In Phase 0 we call agent_manager.build_skill_agent() directly,
        bypassing the ToolContext wrapper, to avoid the pydantic_ai RunContext machinery.
        """
        from app.core.agent_manager import AgentManager
        from pydantic_ai.usage import UsageLimits

        if not isinstance(self._agent_manager, AgentManager):
            # Fallback if agent_manager is not the expected type
            logger.warning(f"agent_manager is not AgentManager, skill '{skill_name}' fallback skipped")
            return {"error": f"agent_manager not configured for skills"}

        # Get skill_deps from the current running context
        # In practice, this would be injected. Here we use a minimal approach.
        skill_agent = self._agent_manager.build_skill_agent(
            skill_name,
            session_id=session_id,
            run_id=None,
            usage_tracker=None,
        )

        # Run the skill sub-agent directly
        result = await skill_agent.run(
            instruction,
            deps=self._agent_manager._deps,  # type: ignore
            usage_limits=UsageLimits(request_limit=100),
        )

        return {
            "output": str(result.output),
            "usage": {
                "input_tokens": result.usage().input_tokens,
                "output_tokens": result.usage().output_tokens,
                "total_tokens": result.usage().total_tokens,
            },
        }

    async def _run_agent_step(
        self,
        agent_name: str,
        instruction: str,
    ) -> dict[str, Any]:
        """Run via agent_cluster (stub in Phase 0)."""
        context: Optional[AgentContext] = None
        from app.core.agent_cluster.base import AgentContext as AC

        result = await self._cluster.invoke(
            agent_name=agent_name,
            task=instruction,
            context=context,
        )
        return {
            "output": result.output,
            "success": result.success,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    def _substitute_context(self, template: str, context: dict[str, Any]) -> str:
        """
        Replace $key references in template with values from context.

        Supports:
        - $step_result_xxx → context value (previous step output)
        - $key → top-level context value
        - $$ → literal $
        """
        # Escape double-dollar signs first
        result = template.replace("$$", "\x00DOLLAR\x00")

        def replacer(m: re.Match) -> str:
            key = m.group(1)
            value = context.get(key)
            if value is None:
                return m.group(0)  # Keep original if not found
            if isinstance(value, dict):
                import json

                return json.dumps(value)
            return str(value)

        # Replace $identifier patterns
        result = re.sub(r"\$([a-zA-Z_][a-zA-Z0-9_]*)", replacer, result)

        # Restore escaped dollars
        result = result.replace("\x00DOLLAR\x00", "$")
        return result

    def _save_checkpoint(self, step: TaskStep, shared_context: dict[str, Any]) -> None:
        """Save a checkpoint after step completion."""
        plan_status = {s.step_id: s.status.value for s in [step]}
        self._checkpoint.save_snapshot(
            plan_id=getattr(step, "_plan_id", "unknown"),
            step_id=step.step_id,
            step_context=dict(shared_context),
            plan_status=plan_status,
        )
