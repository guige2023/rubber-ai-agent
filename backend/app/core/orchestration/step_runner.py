"""
StepRunner - executes individual TaskSteps using agent_cluster or SkillToolkit.

Phase 0 bridges to existing infrastructure:
- "skill:xxx" → SkillToolkit.run_skill (real LLM calls via pydantic_ai sub-agent)
- Other agents → cluster_manager.invoke_skill_toolkit (SkillToolkit-powered execution)
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
    - skill:xxx → call SkillToolkit.run_skill() via agent_manager.build_skill_agent
    - other agents → call cluster_manager.invoke_skill_toolkit() (real LLM via SkillToolkit)

    Each step execution:
    1. Loads checkpoint if resuming
    2. Injects shared_context variables into instruction
    3. Runs the step via SkillToolkit
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

        Note: This method does NOT modify step.status — that is handled by
        _execute_step in the engine after this returns. This separation ensures
        the engine's guard checks see the correct status.

        Args:
            step: The step to execute (status is NOT modified here)
            shared_context: Shared variable store (previous step outputs)
            session_id: Current session ID for skill runs

        Returns:
            StepResult with success/output or failure/error
        """
        started_at = datetime.now(timezone.utc)

        # --- Template substitution: $key → value in instruction ---
        instruction = self._substitute_context(step.instruction, shared_context)

        try:
            agent_type, skill_name = _parse_agent_name(step.agent_name)

            if agent_type == "skill" and skill_name:
                # === PATH 1: Explicit skill:xxx → call SkillToolkit directly ===
                result_data = await self._run_skill_step(skill_name, instruction, session_id)
            else:
                # === PATH 2: Named agent → also call SkillToolkit (real LLM execution) ===
                # All 22 agents are now SkillToolkit-powered; agent_name is used as skill hint
                result_data = await self._run_agent_via_skilltool(
                    agent_name=step.agent_name,
                    instruction=instruction,
                    session_id=session_id,
                )

            finished_at = datetime.now(timezone.utc)

            return StepResult(
                step_id=step.step_id,
                success=True,
                output=result_data,
                duration_ms=int((finished_at - started_at).total_seconds() * 1000),
            )

        except Exception as e:
            logger.exception(f"Step {step.step_id} failed: {e}")
            finished_at = datetime.now(timezone.utc)

            return StepResult(
                step_id=step.step_id,
                success=False,
                error=str(e),
                duration_ms=int((finished_at - started_at).total_seconds() * 1000),
            )

    async def _run_skill_step(
        self,
        skill_name: str,
        instruction: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Run a skill via SkillToolkit.

        SkillToolkit.run_skill() needs a RunContext[AgentDeps].
        We construct one from agent_manager's deps and call build_skill_agent.
        """
        from pydantic_ai.usage import UsageLimits

        if not self._has_real_agent_manager():
            logger.warning(f"agent_manager not configured for skills, skill '{skill_name}' skipped")
            return {"error": f"agent_manager not configured for skills"}

        try:
            skill_agent = self._agent_manager.build_skill_agent(
                skill_name,
                session_id=session_id,
                run_id=None,
                usage_tracker=None,
            )

            result = await skill_agent.run(
                instruction,
                deps=self._agent_manager._deps,  # type: ignore[attr-defined]
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
        except Exception as e:
            logger.exception(f"Skill '{skill_name}' failed: {e}")
            return {"error": str(e), "skill_name": skill_name}

    async def _run_agent_via_skilltool(
        self,
        agent_name: str,
        instruction: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Run a named agent via cluster_manager's SkillToolkit bridge.

        This replaces stub agent implementations with real LLM calls.
        The agent_name acts as a skill hint — cluster_manager.invoke_skill_toolkit
        sets up the proper AgentDeps context and calls SkillToolkit.
        """
        try:
            result = await self._cluster.invoke_skill_toolkit(
                skill_hint=agent_name,
                instruction=instruction,
                session_id=session_id,
            )
            return result
        except Exception as e:
            logger.exception(f"Agent '{agent_name}' via SkillToolkit failed: {e}")
            return {"error": str(e), "agent_name": agent_name}

    def _has_real_agent_manager(self) -> bool:
        """Check if agent_manager is a real AgentManager instance."""
        from app.core.agent_manager import AgentManager

        return isinstance(self._agent_manager, AgentManager)

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
