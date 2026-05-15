"""
Base Agent - Abstract base class for all agents in the cluster.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from .registry import AgentMetadata, AgentStatus, get_registry

if TYPE_CHECKING:
    from .heartbeat import HeartbeatManager

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Context passed to agent invocations."""
    session_id: str
    user_id: Optional[str] = None
    metadata: dict[str, Any] = None
    timeout: int = 300  # seconds


@dataclass
class AgentResult:
    """Result from an agent invocation."""
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: int = 0
    metadata: dict[str, Any] = None


class BaseAgent(ABC):
    """
    Abstract base class for all cluster agents.

    Each agent has:
    - name: Unique identifier
    - description: Human-readable description
    - heartbeat_interval: How often to run heartbeat tasks
    - heartbeat_tasks: List of tasks to run on heartbeat

    Agents must implement:
    - initialize(): Async setup
    - invoke(): Handle a task
    - shutdown(): Cleanup
    """

    name: str = "base"
    description: str = "Base agent"
    version: str = "1.0.0"
    heartbeat_interval: str = "5m"
    heartbeat_tasks: list[str] = None
    capabilities: list[str] = None

    def __init__(self) -> None:
        self._initialized = False
        self._running = False
        self._heartbeat_manager: Optional[HeartbeatManager] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        if self.heartbeat_tasks is None:
            self.heartbeat_tasks = []
        if self.capabilities is None:
            self.capabilities = []

        self._registry = get_registry()

    @property
    def metadata(self) -> AgentMetadata:
        """Get agent metadata for registration."""
        return AgentMetadata(
            name=self.name,
            description=self.description,
            version=self.version,
            heartbeat_interval=self.heartbeat_interval,
            heartbeat_tasks=self.heartbeat_tasks,
            capabilities=self.capabilities,
        )

    async def initialize(self) -> None:
        """Async initialization. Override in subclass."""
        if self._initialized:
            logger.warning(f"Agent {self.name} already initialized")
            return

        # Register first (before any status updates)
        self._registry.register(self, self.metadata)

        self._initialized = True
        await self._registry.update_status(self.name, AgentStatus.IDLE)
        logger.info(f"Agent {self.name} initialized")

    async def start(self) -> None:
        """Start the agent's background tasks (e.g., heartbeat)."""
        if self._running:
            return

        self._running = True
        await self._registry.update_status(self.name, AgentStatus.RUNNING)

        # Start heartbeat loop if configured
        if self.heartbeat_interval and self.heartbeat_tasks:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(f"Agent {self.name} started")

    async def stop(self) -> None:
        """Stop the agent's background tasks."""
        if not self._running:
            return

        await self._registry.update_status(self.name, AgentStatus.STOPPING)

        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        await self._registry.update_status(self.name, AgentStatus.STOPPED)
        logger.info(f"Agent {self.name} stopped")

    async def shutdown(self) -> None:
        """Cleanup resources. Override in subclass."""
        await self.stop()
        self._initialized = False
        self._registry.unregister(self.name)
        logger.info(f"Agent {self.name} shutdown")

    async def invoke(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """
        Invoke the agent with a task.

        Args:
            task: Task description or command
            context: Execution context

        Returns:
            AgentResult with output or error
        """
        start_time = datetime.utcnow()
        await self._registry.increment_invocations(self.name)
        await self._registry.update_status(self.name, AgentStatus.RUNNING)

        try:
            async with self._lock:
                result = await self._invoke_impl(task, context)

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            result.duration_ms = duration_ms

            await self._registry.update_status(self.name, AgentStatus.IDLE)
            return result

        except Exception as e:
            logger.error(f"Agent {self.name} error: {e}")
            await self._registry.update_status(
                self.name,
                AgentStatus.ERROR,
                error_count=getattr(self._registry.get_metadata(self.name), "error_count", 0) + 1,
            )

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            return AgentResult(
                success=False,
                output=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    @abstractmethod
    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """
        Internal invoke implementation. Must be implemented by subclass.

        Args:
            task: Task to execute
            context: Execution context

        Returns:
            AgentResult with output
        """
        ...

    async def heartbeat(self) -> None:
        """
        Run heartbeat tasks.

        Called periodically based on heartbeat_interval.
        Override to implement custom heartbeat behavior.
        """
        if not self.heartbeat_tasks:
            return

        logger.debug(f"Agent {self.name} running heartbeat: {self.heartbeat_tasks}")
        await self._registry.update_heartbeat(self.name)

    async def _heartbeat_loop(self) -> None:
        """Internal heartbeat loop."""
        interval_seconds = self._parse_interval(self.heartbeat_interval)

        while self._running:
            try:
                await asyncio.sleep(interval_seconds)
                if self._running:
                    await self.heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Agent {self.name} heartbeat error: {e}")

    @staticmethod
    def _parse_interval(interval: str) -> int:
        """Parse interval string to seconds."""
        interval = interval.strip().lower()

        if interval.endswith("s"):
            return int(interval[:-1])
        elif interval.endswith("m"):
            return int(interval[:-1]) * 60
        elif interval.endswith("h"):
            return int(interval[:-1]) * 3600
        elif interval.endswith("d"):
            return int(interval[:-1]) * 86400
        else:
            try:
                return int(interval)
            except ValueError:
                return 300  # default 5 minutes


class MasterAgent(BaseAgent):
    """
    Master Agent - Coordinates other agents in the cluster.

    Responsibilities:
    - Task decomposition and routing
    - Result aggregation
    - Failure handling
    """

    name = "master"
    description = "Master agent for task coordination"
    heartbeat_interval = "1m"
    heartbeat_tasks = ["check_cluster_health", "balance_load"]
    capabilities = ["coordination", "routing", "aggregation"]

    def __init__(self) -> None:
        super().__init__()
        self._sub_agents: dict[str, BaseAgent] = {}

    def register_sub_agent(self, agent: BaseAgent) -> None:
        """Register a sub-agent for coordination."""
        self._sub_agents[agent.name] = agent

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """
        Master agent decomposes task and delegates to sub-agents.
        """
        # Simplified - real implementation would parse task and route
        outputs = []

        for agent_name, agent in self._sub_agents.items():
            try:
                result = await agent.invoke(f"assist: {task}", context)
                if result.success:
                    outputs.append({agent_name: result.output})
            except Exception as e:
                logger.error(f"Master failed to invoke {agent_name}: {e}")

        return AgentResult(
            success=True,
            output={"results": outputs, "task": task},
        )
