import logging
from pydantic_ai import RunContext
from app.core.deps import AgentDeps
from app.core.prompts import SKILL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class SkillToolkit:
    """Tools for discovering and executing specialized Skills."""

    @staticmethod
    def get_tools():
        return [SkillToolkit.run_skill]

    @staticmethod

    async def read_skill_sop(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Read the full SOP (SKILL.md) of a specific skill before executing it."""
        return ctx.deps.kernel.read_skill_sop(skill_name)

    @staticmethod
    async def run_skill(
        ctx: RunContext[AgentDeps],
        skill_name: str,
        instruction: str,
    ) -> str:
        """
        Delegate a task to a specialized Skill agent.
        Use this when a skill in <Available Skills> matches the user's intent.
        The skill agent has its own expert-level SOP and will use Browser/File tools autonomously.
        Pass the user's original instruction (or a refined version) as `instruction`.
        """
        kernel = ctx.deps.kernel
        session_id = ctx.deps.session_id
        
        if skill_name not in kernel.skills:
            return f"Error: Skill '{skill_name}' not found."

        workspace = kernel.get_session_workspace(session_id)
        sop = kernel.read_skill_sop(skill_name)

        logger.info(f"Executing skill '{skill_name}' in {workspace}")

        import platform
        from datetime import datetime
        
        # Determine browser visibility
        is_headless = kernel._session_headless.get(session_id, True)
        visibility = "Visible (headless=False). You can ask the user to help." if not is_headless else "Headless (Invisible). Manual intervention is NOT possible."

        skill_context = SKILL_SYSTEM_PROMPT.format(
            skill_name=skill_name,
            sop=sop,
            root_dir=str(kernel._settings.root_dir),
            browser_visibility=visibility,
            os_name=platform.system(),
            current_time=datetime.now().astimezone().isoformat()
        )
        
        # Build a temporary agent for the skill
        executor = kernel.build_agent(skill_context)

        try:
            # IMPORTANT: Pass ctx.usage to sub-agent to aggregate token costs automatically
            result = await executor.run(instruction, deps=ctx.deps, usage=ctx.usage)
            usage = result.usage()
            logger.info({
                "message": {
                    "session_id": session_id,
                    "skill_name": skill_name,
                    "type": "skill_usage",
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens
                }
            })
            return f"Skill '{skill_name}' execution completed. Result: {str(result.output)}"
        except Exception as e:
            logger.exception(f"Error executing skill {skill_name}")
            return f"Error executing Skill '{skill_name}': {e}"
