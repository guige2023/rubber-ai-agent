"""
Agent Cluster Manager - Orchestrates all agents in the cluster.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from .base import AgentContext, AgentResult, BaseAgent, MasterAgent
from .heartbeat import DEFAULT_HEARTBEAT_CONFIGS, HeartbeatManager
from .memory import MemoryManager
from .protocol import AgentProtocol, get_router
from .registry import AgentRegistry, AgentStatus, get_registry

if TYPE_CHECKING:
    from .base import BaseAgent

logger = logging.getLogger(__name__)


class AgentClusterManager:
    """
    Central manager for the agent cluster.

    Responsibilities:
    - Agent lifecycle management
    - Heartbeat coordination
    - Memory management
    - Inter-agent communication
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._registry = get_registry()
        self._heartbeat_manager = HeartbeatManager(self._registry)
        self._memory_manager = MemoryManager()
        self._router = get_router()
        self._running = False
        self._master_agent: Optional[MasterAgent] = None
        self._agents: dict[str, BaseAgent] = {}

    async def initialize(
        self,
        l2_neo4j_uri: Optional[str] = None,
        l3_skills_path: Optional[str] = None,
    ) -> None:
        """Initialize the cluster manager."""
        # Initialize memory system
        await self._memory_manager.initialize(
            l2_uri=l2_neo4j_uri,
            l3_path=l3_skills_path,
        )

        # Initialize master agent
        self._master_agent = MasterAgent()
        await self._master_agent.initialize()

        logger.info("AgentClusterManager initialized")

    async def start(self) -> None:
        """Start all agents in the cluster."""
        if self._running:
            return

        self._running = True

        # Start heartbeat manager
        await self._heartbeat_manager.start()

        # Start master agent
        if self._master_agent:
            await self._master_agent.start()

        # Start all registered agents
        for agent in self._agents.values():
            try:
                await agent.start()
            except Exception as e:
                logger.error(f"Failed to start agent {agent.name}: {e}")

        logger.info(f"AgentClusterManager started with {len(self._agents)} agents")

    async def shutdown(self) -> None:
        """Shutdown all agents gracefully."""
        if not self._running:
            return

        self._running = False

        # Stop all agents
        for agent in self._agents.values():
            try:
                await agent.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down {agent.name}: {e}")

        # Stop master agent
        if self._master_agent:
            await self._master_agent.shutdown()

        # Stop heartbeat manager
        await self._heartbeat_manager.stop()

        # Shutdown memory
        await self._memory_manager.shutdown()

        logger.info("AgentClusterManager shutdown complete")

    def register_agent(self, agent: BaseAgent) -> None:
        """
        Register an agent with the cluster.

        Args:
            agent: Agent instance to register
        """
        self._agents[agent.name] = agent

        # Configure heartbeat for this agent
        config = DEFAULT_HEARTBEAT_CONFIGS.get(agent.name)
        if config:
            self._heartbeat_manager.configure(config)

        # Special handling for memory agent - set memory manager
        if agent.name == "memory":
            from .agents import MemoryAgent
            if isinstance(agent, MemoryAgent):
                agent.set_memory_manager(self._memory_manager)

        # Register sub-agent with master
        if self._master_agent and agent.name != "master":
            self._master_agent.register_sub_agent(agent)

        logger.info(f"Registered agent: {agent.name}")

    def unregister_agent(self, name: str) -> bool:
        """
        Unregister an agent from the cluster.

        Returns True if agent was found and removed.
        """
        if name in self._agents:
            agent = self._agents[name]
            asyncio.create_task(agent.shutdown())
            del self._agents[name]
            self._registry.unregister(name)
            return True
        return False

    async def invoke(
        self,
        agent_name: str,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """
        Invoke a specific agent.

        Args:
            agent_name: Name of agent to invoke
            task: Task description
            context: Execution context

        Returns:
            AgentResult with output
        """
        agent = self._agents.get(agent_name)
        if not agent:
            return AgentResult(
                success=False,
                output=None,
                error=f"Unknown agent: {agent_name}",
            )

        try:
            return await agent.invoke(task, context)
        except Exception as e:
            logger.error(f"Invoke error for {agent_name}: {e}")
            return AgentResult(
                success=False,
                output=None,
                error=str(e),
            )

    async def invoke_master(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """
        Invoke the master agent to coordinate a task.

        Args:
            task: Task to coordinate
            context: Execution context

        Returns:
            AgentResult with coordinated output
        """
        if not self._master_agent:
            return AgentResult(
                success=False,
                output=None,
                error="Master agent not initialized",
            )

        return await self._master_agent.invoke(task, context)

    async def invoke_with_fallback(
        self,
        task: str,
        preferred_agent: str,
        fallback_agents: list[str],
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """
        Invoke with fallback agents if primary fails.

        Args:
            task: Task description
            preferred_agent: Preferred agent name
            fallback_agents: List of fallback agent names
            context: Execution context

        Returns:
            AgentResult from first successful agent
        """
        # Try preferred agent first
        result = await self.invoke(preferred_agent, task, context)
        if result.success:
            return result

        # Try fallback agents
        for agent_name in fallback_agents:
            result = await self.invoke(agent_name, task, context)
            if result.success:
                logger.info(f"Fallback succeeded: {agent_name}")
                return result

        return result  # Last failure result

    async def invoke_skill_toolkit(
        self,
        skill_hint: str,
        instruction: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Invoke SkillToolkit for real LLM execution, bypassing stub agents.

        This bridges the agent_cluster to the pydantic_ai-based SkillToolkit:
        1. Locates the skill via runtime's skill_manager
        2. Builds a skill agent via runtime's agent_manager
        3. Runs it with the given instruction
        4. Returns structured output

        Args:
            skill_hint: Agent name used as skill hint (e.g. "coder", "research")
            instruction: Task instruction for the skill
            session_id: Current session ID

        Returns:
            dict with output/error and usage metadata
        """
        from pydantic_ai.usage import UsageLimits

        # Get the global runtime which holds the real AgentManager and SkillManager
        from app.core.runtime import RabAiAgentRuntime
        runtime = RabAiAgentRuntime.get_instance() if hasattr(RabAiAgentRuntime, "get_instance") else None

        if runtime is None:
            # Fallback: try to get from current asyncio task
            try:
                import asyncio
                task = asyncio.current_task()
                if task:
                    logger.debug(f"invoke_skill_toolkit: no global runtime, skill_hint={skill_hint}")
            except Exception:
                pass

            logger.warning(
                f"invoke_skill_toolkit: RabAiAgentRuntime not available, "
                f"skill '{skill_hint}' cannot execute via SkillToolkit"
            )
            return {
                "error": f"RabAiAgentRuntime not available for skill '{skill_hint}'",
                "skill_hint": skill_hint,
            }

        skill_manager = runtime.skill_manager
        agent_manager = runtime.agent_manager
        prompt_builder = runtime.prompt_builder

        # Check if the skill exists in skill_manager
        if skill_hint not in skill_manager.skills:
            logger.warning(
                f"invoke_skill_toolkit: skill '{skill_hint}' not found in skill_manager, "
                f"available: {list(skill_manager.skills.keys())[:10]}..."
            )
            return {
                "error": f"Skill '{skill_hint}' not registered in skill_manager",
                "skill_hint": skill_hint,
            }

        try:
            logger.info(f"invoke_skill_toolkit: executing skill '{skill_hint}'")

            # Build the skill agent
            skill_agent = agent_manager.build_skill_agent(
                skill_hint,
                session_id=session_id,
                run_id=None,
                usage_tracker=None,
            )

            # Augment instruction with runtime context
            augmented_instruction = prompt_builder.build_runtime_augmented_instruction(
                instruction,
                session_id,
                skill_name=skill_hint,
            )

            # Create minimal deps for the skill run
            deps = runtime.create_agent_deps(
                session_id=session_id,
                run_id=f"skill-{skill_hint}-{datetime.now(timezone.utc).timestamp()}",
                skill_name=skill_hint,
            )

            result = await skill_agent.run(
                augmented_instruction,
                deps=deps,
                usage_limits=UsageLimits(request_limit=150),
            )

            usage = result.usage()
            logger.info(
                f"invoke_skill_toolkit: skill '{skill_hint}' completed, "
                f"tokens={usage.total_tokens}"
            )

            return {
                "output": str(result.output),
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                },
                "skill_hint": skill_hint,
            }

        except Exception as e:
            logger.exception(f"invoke_skill_toolkit: skill '{skill_hint}' failed: {e}")
            return {
                "error": str(e),
                "skill_hint": skill_hint,
            }

    def get_status(self) -> dict[str, Any]:
        """
        Get cluster status.

        Returns:
            Dict with cluster status information
        """
        agent_statuses = []
        for name, agent in self._agents.items():
            meta = self._registry.get_metadata(name)
            if meta:
                agent_statuses.append({
                    "name": name,
                    "status": meta.status.value,
                    "last_heartbeat": meta.last_heartbeat.isoformat() if meta.last_heartbeat else None,
                    "last_active": meta.last_active.isoformat() if meta.last_active else None,
                    "total_invocations": meta.total_invocations,
                    "error_count": meta.error_count,
                })

        return {
            "running": self._running,
            "total_agents": len(self._agents),
            "agents": agent_statuses,
            "master_agent": {
                "registered": self._master_agent is not None,
                "running": self._master_agent._running if self._master_agent else False,
            },
        }

    async def get_status_async(self) -> dict[str, Any]:
        """Get cluster status with async memory stats."""
        status = self.get_status()
        status["memory"] = await self._memory_manager.get_stats()
        return status

    def list_agents(self) -> list[dict[str, Any]]:
        """List all agents with their status."""
        return [
            {
                "name": name,
                "description": agent.description,
                "version": agent.version,
                "heartbeat_interval": agent.heartbeat_interval,
                "capabilities": agent.capabilities,
            }
            for name, agent in self._agents.items()
        ]

    # === Memory Access ===

    @property
    def memory(self) -> MemoryManager:
        """Access the memory manager."""
        return self._memory_manager

    # === Heartbeat Control ===

    def trigger_heartbeat(self, agent_name: str) -> None:
        """Manually trigger heartbeat for an agent."""
        self._heartbeat_manager.enable(agent_name)

    def disable_heartbeat(self, agent_name: str) -> None:
        """Disable heartbeat for an agent."""
        self._heartbeat_manager.disable(agent_name)


# Global cluster instance
_cluster: Optional[AgentClusterManager] = None


def get_cluster() -> AgentClusterManager:
    """Get the global agent cluster manager."""
    global _cluster
    if _cluster is None:
        _cluster = AgentClusterManager()
    return _cluster
