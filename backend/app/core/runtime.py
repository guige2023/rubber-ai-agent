from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from app.core.config import Settings
from app.core.db import init_db
from app.core.heartbeat.runner import HeartbeatRunner, DEFAULT_HEARTBEAT_TASKS
from app.core.evolution.evolution_manager import EvolutionManager
from app.core.evolution.nudge import NudgeSignal
from app.core.memory.memory_manager import MemoryManager

if TYPE_CHECKING:
    from app.core.deps import AgentDeps
    from app.models.events import RabAiAgentEventEnvelope

logger = logging.getLogger(__name__)


_runtime_instance: "RabAiAgentRuntime | None" = None


class RabAiAgentRuntime:
    """Composition root for the RabAiAgent local sidecar runtime."""

    @classmethod
    def get_instance(cls) -> "RabAiAgentRuntime | None":
        """Get the global runtime instance if one has been created."""
        return _runtime_instance

    @classmethod
    def set_instance(cls, instance: "RabAiAgentRuntime") -> None:
        """Set the global runtime instance (called by the application entry point)."""
        global _runtime_instance
        _runtime_instance = instance

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._workspace_root: Path = settings.root_dir / "workspaces"
        self._init_directories(settings)
        init_db()
        settings.seed_runtime_defaults()
        self._init_managers(settings)
        # Register this instance as the global singleton
        RabAiAgentRuntime.set_instance(self)

    def _init_managers(self, settings: Settings) -> None:
        from app.core.agent_manager import AgentManager
        from app.core.browser_manager import BrowserManager
        from app.core.context_manager import ContextManager
        from app.core.model_manager import ModelManager
        from app.core.model_pricing import ModelPricingService
        from app.core.prompt_builder import PromptBuilder
        from app.core.run_registry import RunRegistry
        from app.core.schedule_manager import ScheduleManager
        from app.core.session_manager import SessionManager
        from app.core.skill_manager import SkillManager
        from app.core.task_manager import TaskManager
        from app.core.tool_manager import ToolManager

        self.model_manager = ModelManager(settings=settings)
        self.model_pricing_service = ModelPricingService(enabled=settings.model_pricing_refresh_enabled)
        self.skill_manager = SkillManager(settings=settings)
        self.task_manager = TaskManager()
        self.session_manager = SessionManager()
        self.tool_manager = ToolManager()
        self.schedule_manager = ScheduleManager(self, settings)
        self.browser_manager = BrowserManager(settings=settings, get_session_workspace=self.get_session_workspace)
        self.prompt_builder = PromptBuilder(
            settings=settings,
            skill_manager=self.skill_manager,
            get_session_workspace=self.get_session_workspace,
        )
        self.context_manager = ContextManager(
            settings=settings,
            model_manager=self.model_manager,
            session_manager=self.session_manager,
            build_system_prompt=self.prompt_builder.build_system_prompt,
        )
        self.agent_manager = AgentManager(
            settings=settings,
            model_manager=self.model_manager,
            model_pricing_service=self.model_pricing_service,
            tool_manager=self.tool_manager,
            prompt_builder=self.prompt_builder,
            session_manager=self.session_manager,
            context_manager=self.context_manager,
        )
        self.run_registry = RunRegistry(self)

        # Initialize MemoryManager
        self.memory_manager = MemoryManager()

        # Initialize EvolutionManager
        self.evolution_manager = EvolutionManager()

        # Initialize TriggerManager
        from app.core.trigger_manager import TriggerManager
        self.trigger_manager = TriggerManager(self)

        # Initialize NotificationManager
        from app.core.notification import NotificationManager
        self.notification_manager = NotificationManager()

        # Initialize HeartbeatRunner with default tasks
        self.heartbeat_runner = HeartbeatRunner(tasks=DEFAULT_HEARTBEAT_TASKS)
        self.heartbeat_runner.set_notification_manager(self.notification_manager)

    async def start(self) -> None:
        """Start all runtime systems."""
        # Set up heartbeat handler that processes signals via evolution manager
        async def heartbeat_handler(tasks: list[dict]) -> None:
            for task in tasks:
                # Extract prompt from heartbeat task
                task_prompt = task.get("prompt", "")
                if not task_prompt:
                    continue

                # Detect signals from the heartbeat task
                signals = self.evolution_manager.detect_signals(
                    user_message=task_prompt,
                    agent_response="",
                    tool_calls=[],
                )

                # Process any detected signals
                if signals:
                    await self.evolution_manager.process_signals(
                        signals,
                        {"source": "heartbeat", "task_name": task.get("name", "unknown")},
                    )

        self.heartbeat_runner.set_heartbeat_handler(heartbeat_handler)

        # Initialize and start memory manager
        await self.memory_manager.initialize()

        # Initialize evolution manager (starts background reviewer and curator)
        await self.evolution_manager.initialize()

        # Start heartbeat runner
        await self.heartbeat_runner.start()

        logger.info("RabAiAgentRuntime started: heartbeat, evolution, and memory systems initialized")

    async def shutdown(self) -> None:
        """Shutdown all runtime systems gracefully."""
        logger.info("Shutting down RabAiAgentRuntime...")

        # Stop heartbeat runner
        if hasattr(self, 'heartbeat_runner') and self.heartbeat_runner:
            await self.heartbeat_runner.stop()

        # Shutdown evolution manager
        if hasattr(self, 'evolution_manager') and self.evolution_manager:
            await self.evolution_manager.shutdown()

        # Shutdown memory manager
        if hasattr(self, 'memory_manager') and self.memory_manager:
            await self.memory_manager.shutdown()

        logger.info("RabAiAgentRuntime shutdown complete")

    @staticmethod
    def _init_directories(settings: Settings) -> None:
        sub_dirs = [
            settings.user_dir / "reports",
            settings.user_dir / "tasks",
            settings.user_dir / "logs",
            settings.user_dir / "workspaces",
            settings.browser_dir,
            settings.user_skills_dir,
        ]

        for sd in sub_dirs:
            if not sd.exists():
                sd.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created directory: {sd}")

    def get_session_workspace(self, session_id: str) -> Path:
        session_dir = self._workspace_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def create_agent_deps(
        self,
        session_id: str,
        *,
        run_id: str,
        skill_name: Optional[str] = None,
        emit_event_cb: Optional[Callable[["RabAiAgentEventEnvelope"], Awaitable[None]]] = None,
    ) -> "AgentDeps":
        from app.core.deps import AgentDeps

        return AgentDeps(
            session_id=session_id,
            settings=self.settings,
            workspace_dir=self.get_session_workspace(session_id),
            agent_manager=self.agent_manager,
            browser_manager=self.browser_manager,
            prompt_builder=self.prompt_builder,
            skill_manager=self.skill_manager,
            task_manager=self.task_manager,
            skill_name=skill_name,
            run_id=run_id,
            model_pricing_service=self.model_pricing_service,
            emit_event_cb=emit_event_cb,
            schedule_manager=self.schedule_manager,
        )

    async def run_master_agent(
        self,
        instruction: str,
        session_id: str,
        *,
        run_id: str,
        emit_event_cb: Optional[Callable[["RabAiAgentEventEnvelope"], Awaitable[None]]] = None,
    ) -> dict[str, object]:
        deps = self.create_agent_deps(
            session_id=session_id,
            run_id=run_id,
            emit_event_cb=emit_event_cb,
        )
        return await self.agent_manager.run_master_agent(
            instruction=instruction,
            session_id=session_id,
            run_id=run_id,
            deps=deps,
        )
