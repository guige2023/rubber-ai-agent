"""
Concrete Agent Implementations.

All agents delegate to SkillToolkit via AgentClusterManager.invoke_skill_toolkit,
providing real LLM-powered execution instead of stub responses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from .base import AgentContext, AgentResult, BaseAgent
from .protocol import AgentProtocol

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _run_via_skilltool(
    skill_hint: str,
    instruction: str,
    session_id: str,
) -> dict[str, Any]:
    """
    Shared helper to run a task via SkillToolkit through the global cluster.

    Returns a dict with 'output' or 'error' key.
    This is called from async context so we use asyncio.get_event_loop().run_until_complete
    for the awaitable — but since invoke_skill_toolkit itself is async, we need to be
    in an async context. Use _run_via_skilltool_async instead from async code.
    """
    import asyncio
    from .manager import get_cluster

    try:
        loop = asyncio.get_running_loop()
        # If we're already in an async context, schedule and wait
        future = asyncio.ensure_future(
            get_cluster().invoke_skill_toolkit(
                skill_hint=skill_hint,
                instruction=instruction,
                session_id=session_id,
            )
        )
        # Cannot block on a future in a running loop — return placeholder
        # The async version should be used instead
        logger.warning(f"_run_via_skilltool called from async context for {skill_hint}, use async variant")
        return {"output": f"[async task scheduled for {skill_hint}]", "skill_hint": skill_hint}
    except RuntimeError:
        # No running loop — use run_until_complete
        return asyncio.get_event_loop().run_until_complete(
            get_cluster().invoke_skill_toolkit(
                skill_hint=skill_hint,
                instruction=instruction,
                session_id=session_id,
            )
        )


async def _run_via_skilltool_async(
    skill_hint: str,
    instruction: str,
    session_id: str,
) -> dict[str, Any]:
    """Async version — call invoke_skill_toolkit directly."""
    from .manager import get_cluster

    try:
        return await get_cluster().invoke_skill_toolkit(
            skill_hint=skill_hint,
            instruction=instruction,
            session_id=session_id,
        )
    except Exception as e:
        logger.exception(f"SkillToolkit delegate failed for '{skill_hint}': {e}")
        return {"error": str(e), "skill_hint": skill_hint}


class CoderAgent(BaseAgent):
    """
    Code generation and modification agent.

    Delegates to SkillToolkit for real LLM-powered code generation,
    bug fixing, test writing, and code review.
    """

    name = "coder"
    description = "Code generation and modification"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["check_code_quality", "scan_dependencies"]
    capabilities = ["code_generation", "bug_fixing", "test_generation", "refactoring"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle coding tasks via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class ReviewerAgent(BaseAgent):
    """
    Code review agent.

    Delegates to SkillToolkit for real LLM-powered code review,
    style compliance, security scanning, and quality assurance.
    """

    name = "reviewer"
    description = "Code review and analysis"
    version = "1.0.0"
    heartbeat_interval = "10m"
    heartbeat_tasks = ["review_pending_changes"]
    capabilities = ["code_review", "style_check", "security_scan", "quality_assurance"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Review code via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class MemoryAgent(BaseAgent):
    """
    Memory management agent.

    Delegates to SkillToolkit for memory consolidation,
    search, and L1/L2/L3 tier management.
    """

    name = "memory"
    description = "Memory consolidation and retrieval"
    version = "1.0.0"
    heartbeat_interval = "15m"
    heartbeat_tasks = ["consolidate_memories", "cleanup_old_memories"]
    capabilities = ["memory_consolidation", "memory_search", "memory_management"]

    def __init__(self) -> None:
        super().__init__()
        self._memory_manager = None

    def set_memory_manager(self, memory_manager: Any) -> None:
        """Set reference to memory manager."""
        self._memory_manager = memory_manager

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle memory tasks via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        task_lower = task.lower()

        # First try SkillToolkit for LLM-powered memory operations
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" not in result_data:
            return AgentResult(success=True, output=result_data)

        # Fallback to memory_manager for direct tier operations
        if self._memory_manager is not None:
            if "consolidate" in task_lower:
                stats = await self._memory_manager.consolidate()
                return AgentResult(success=True, output={"stats": stats})
            elif "search" in task_lower:
                query = task.replace("search", "").strip()
                results = await self._memory_manager.l2_search(query)
                return AgentResult(success=True, output={"results": results, "query": query})
            elif "stats" in task_lower or "status" in task_lower:
                stats = await self._memory_manager.get_stats()
                return AgentResult(success=True, output=stats)

        return AgentResult(success=False, output=None, error=result_data.get("error", "Memory manager not available"))


class MonitorAgent(BaseAgent):
    """
    System monitoring agent.

    Delegates to SkillToolkit for health checks, metrics,
    and anomaly detection.
    """

    name = "monitor"
    description = "System monitoring and health checks"
    version = "1.0.0"
    heartbeat_interval = "30s"
    heartbeat_tasks = ["check_system_health", "report_metrics"]
    capabilities = ["monitoring", "health_check", "metrics", "alerting"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Monitor system via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class SchedulerAgent(BaseAgent):
    """
    Task scheduling agent.

    Delegates to SkillToolkit for scheduling decisions,
    cron management, and task trigger logic.
    """

    name = "scheduler"
    description = "Task scheduling and cron management"
    version = "1.0.0"
    heartbeat_interval = "1m"
    heartbeat_tasks = ["check_scheduled_tasks", "trigger_due_tasks"]
    capabilities = ["scheduling", "cron", "task_management"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle scheduling via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class SecurityAgent(BaseAgent):
    """
    Security scanning agent.

    Delegates to SkillToolkit for vulnerability scanning,
    access log analysis, and security compliance checks.
    """

    name = "security"
    description = "Security scanning and compliance"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["scan_vulnerabilities", "check_access_logs"]
    capabilities = ["security_scan", "vulnerability_detection", "compliance"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Perform security scan via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class ReporterAgent(BaseAgent):
    """
    Report generation agent.

    Delegates to SkillToolkit for status report generation,
    summarization, and formatted output.
    """

    name = "reporter"
    description = "Report generation and summarization"
    version = "1.0.0"
    heartbeat_interval = "30m"
    heartbeat_tasks = ["generate_summary"]
    capabilities = ["reporting", "summarization", "formatting"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Generate report via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class ResearchAgent(BaseAgent):
    """
    Research agent for information gathering.

    Delegates to SkillToolkit for web research, fact checking,
    data collection, and source verification.
    """

    name = "research"
    description = "Research and information gathering"
    version = "1.0.0"
    heartbeat_interval = "15m"
    heartbeat_tasks = ["update_knowledge_base"]
    capabilities = ["research", "fact_check", "data_collection"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Perform research via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class SearchAgent(BaseAgent):
    """
    Search agent for web and internal search.

    Delegates to SkillToolkit for search operations,
    index management, and result ranking.
    """

    name = "search"
    description = "Search and discovery"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["refresh_index"]
    capabilities = ["search", "discovery", "indexing"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Perform search via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class AnalyticsAgent(BaseAgent):
    """
    Analytics agent for data analysis.

    Delegates to SkillToolkit for data aggregation,
    trend analysis, statistics, and visualization.
    """

    name = "analytics"
    description = "Data analytics and metrics"
    version = "1.0.0"
    heartbeat_interval = "10m"
    heartbeat_tasks = ["compute_metrics"]
    capabilities = ["analytics", "metrics", "trends", "visualization"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Analyze data via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class EmailAgent(BaseAgent):
    """
    Email processing agent.

    Delegates to SkillToolkit for email composition,
    filtering, and auto-response generation.
    """

    name = "email"
    description = "Email processing and management"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["check_inbox", "process_new_emails"]
    capabilities = ["email", "messaging", "notifications"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Process email task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class CalendarAgent(BaseAgent):
    """
    Calendar management agent.

    Delegates to SkillToolkit for event scheduling,
    availability checking, and reminder generation.
    """

    name = "calendar"
    description = "Calendar and scheduling"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["check_upcoming_events", "send_reminders"]
    capabilities = ["calendar", "scheduling", "reminders"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle calendar task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class FileAgent(BaseAgent):
    """
    File management agent.

    Delegates to SkillToolkit for file operations,
    directory management, and content organization.
    """

    name = "file"
    description = "File management and organization"
    version = "1.0.0"
    heartbeat_interval = "10m"
    heartbeat_tasks = ["index_files", "cleanup_temp"]
    capabilities = ["file_management", "search", "organization"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle file task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class ShellAgent(BaseAgent):
    """
    Shell command execution agent.

    Delegates to SkillToolkit for command generation,
    script creation, and output parsing.
    """

    name = "shell"
    description = "Shell command execution"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["check_running_processes"]
    capabilities = ["shell", "commands", "scripting", "automation"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Execute shell task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class BrowserAgent(BaseAgent):
    """
    Browser automation agent.

    Delegates to SkillToolkit for web navigation,
    form filling, and screenshot analysis.
    """

    name = "browser"
    description = "Browser automation"
    version = "1.0.0"
    heartbeat_interval = "15m"
    heartbeat_tasks = ["check_browser_health"]
    capabilities = ["browser", "automation", "scraping", "screenshots"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle browser task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class APIAgent(BaseAgent):
    """
    API management agent.

    Delegates to SkillToolkit for API call generation,
    response parsing, and documentation.
    """

    name = "api"
    description = "API management and integration"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["check_api_health", "update_docs"]
    capabilities = ["api", "integration", "http", "rest"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle API task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class DatabaseAgent(BaseAgent):
    """
    Database operations agent.

    Delegates to SkillToolkit for query generation,
    schema analysis, and backup planning.
    """

    name = "database"
    description = "Database operations and management"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["check_connections", "backup_check"]
    capabilities = ["database", "sql", "backup", "monitoring"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle database task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class TestAgent(BaseAgent):
    """
    Test generation and execution agent.

    Delegates to SkillToolkit for unit test generation,
    integration test creation, and coverage analysis.
    """

    name = "test"
    description = "Test generation and execution"
    version = "1.0.0"
    heartbeat_interval = "10m"
    heartbeat_tasks = ["run_test_suite"]
    capabilities = ["testing", "qa", "coverage", "automation"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle test task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class DebugAgent(BaseAgent):
    """
    Debugging and troubleshooting agent.

    Delegates to SkillToolkit for error analysis,
    stack trace parsing, and issue diagnosis.
    """

    name = "debug"
    description = "Debugging and troubleshooting"
    version = "1.0.0"
    heartbeat_interval = "5m"
    heartbeat_tasks = ["analyze_errors"]
    capabilities = ["debugging", "troubleshooting", "diagnosis", "logs"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle debug task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class DocAgent(BaseAgent):
    """
    Documentation generation agent.

    Delegates to SkillToolkit for API documentation,
    README generation, and code documentation.
    """

    name = "doc"
    description = "Documentation generation"
    version = "1.0.0"
    heartbeat_interval = "30m"
    heartbeat_tasks = ["update_docs"]
    capabilities = ["documentation", "writing", "formatting"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle documentation task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class BackupAgent(BaseAgent):
    """
    Backup management agent.

    Delegates to SkillToolkit for backup strategy,
    restore planning, and verification.
    """

    name = "backup"
    description = "Backup and restore management"
    version = "1.0.0"
    heartbeat_interval = "1h"
    heartbeat_tasks = ["verify_backup", "cleanup_old"]
    capabilities = ["backup", "restore", "disaster_recovery"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle backup task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class AlertAgent(BaseAgent):
    """
    Alert management agent.

    Delegates to SkillToolkit for alert generation,
    routing logic, and escalation decisions.
    """

    name = "alert"
    description = "Alert and notification management"
    version = "1.0.0"
    heartbeat_interval = "30s"
    heartbeat_tasks = ["check_alert_conditions"]
    capabilities = ["alerts", "notifications", "escalation", "monitoring"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle alert task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


class WorkflowAgent(BaseAgent):
    """
    Workflow orchestration agent.

    Delegates to SkillToolkit for workflow execution,
    task dependency analysis, and state management.
    """

    name = "workflow"
    description = "Workflow orchestration"
    version = "1.0.0"
    heartbeat_interval = "2m"
    heartbeat_tasks = ["check_workflow_status"]
    capabilities = ["workflow", "orchestration", "automation", "coordination"]

    async def _invoke_impl(
        self,
        task: str,
        context: Optional[AgentContext] = None,
    ) -> AgentResult:
        """Handle workflow task via SkillToolkit."""
        session_id = context.session_id if context else "agent"
        result_data = await _run_via_skilltool_async(
            skill_hint=self.name,
            instruction=task,
            session_id=session_id,
        )
        if "error" in result_data:
            return AgentResult(success=False, output=None, error=result_data["error"])
        return AgentResult(success=True, output=result_data)


# Registry of all available agents (22 agents)
AGENT_REGISTRY = {
    "coder": CoderAgent,
    "reviewer": ReviewerAgent,
    "memory": MemoryAgent,
    "monitor": MonitorAgent,
    "scheduler": SchedulerAgent,
    "security": SecurityAgent,
    "reporter": ReporterAgent,
    "research": ResearchAgent,
    "search": SearchAgent,
    "analytics": AnalyticsAgent,
    "email": EmailAgent,
    "calendar": CalendarAgent,
    "file": FileAgent,
    "shell": ShellAgent,
    "browser": BrowserAgent,
    "api": APIAgent,
    "database": DatabaseAgent,
    "test": TestAgent,
    "debug": DebugAgent,
    "doc": DocAgent,
    "backup": BackupAgent,
    "alert": AlertAgent,
    "workflow": WorkflowAgent,
}


def create_agent(agent_type: str) -> BaseAgent:
    """Factory function to create agents by type."""
    agent_class = AGENT_REGISTRY.get(agent_type)
    if not agent_class:
        raise ValueError(f"Unknown agent type: {agent_type}")
    return agent_class()


def get_all_agent_types() -> list[str]:
    """Get list of all available agent types."""
    return list(AGENT_REGISTRY.keys())
