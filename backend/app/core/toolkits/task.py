from __future__ import annotations

from typing import Optional

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps, get_schedule_manager, get_task_manager
from app.core.schedule_manager import ScheduleNotFoundError, ScheduleValidationError
from app.core.task_manager import TaskNotFoundError, TaskValidationError, VALID_TASK_STATUSES
from app.core.toolkits.base import Toolkit

PREVIEW_LIMIT = 120


def _require_non_empty(field_name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ModelRetry(f"{field_name} must not be empty.")
    return normalized


def _render_preview(value: str, *, limit: int = PREVIEW_LIMIT) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 3].rstrip()}..."


class TaskToolkit(Toolkit):
    """Persist and query tasks and schedule definitions for the agent runtime."""

    @staticmethod
    def get_tools():
        return [
            TaskToolkit.create_task,
            TaskToolkit.update_task,
            TaskToolkit.list_tasks,
            TaskToolkit.create_schedule,
            TaskToolkit.update_schedule,
            TaskToolkit.list_schedules,
        ]

    @staticmethod
    async def create_task(
            ctx: RunContext[AgentDeps],
            title: str,
            instruction: str,
            metadata: Optional[dict[str, object]] = None,
            parent_id: Optional[str] = None
    ) -> str:
        """Create or deduplicate a persisted task.

        Stores the task title, instruction, and optional metadata, then returns
        a confirmation with the canonical task ID.
        """
        session_id = ctx.deps.session_id
        normalized_title = _require_non_empty("title", title)
        normalized_instruction = _require_non_empty("instruction", instruction)

        task = get_task_manager(ctx.deps).create_task(
            session_id=session_id,
            title=normalized_title,
            instruction=normalized_instruction,
            metadata=metadata,
            parent_id=parent_id,
        )
        return f"Task created/verified: ID={task.id}, Title='{task.title}'"

    @staticmethod
    async def update_task(
            ctx: RunContext[AgentDeps], task_id: str, status: str, progress_note: Optional[str] = None
    ) -> str:
        """Update a task status and optional progress note.

        `status` must be one of: pending, running, success, failed, or canceled.
        """
        normalized_task_id = _require_non_empty("task_id", task_id)
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_TASK_STATUSES:
            allowed = ", ".join(sorted(VALID_TASK_STATUSES))
            raise ModelRetry(f"status must be one of: {allowed}.")

        try:
            get_task_manager(ctx.deps).update_task(
                normalized_task_id,
                status=normalized_status,
                progress_note=progress_note,
            )
        except TaskNotFoundError as exc:
            raise ModelRetry(str(exc)) from exc
        except TaskValidationError as exc:
            raise ModelRetry(str(exc)) from exc
        return f"Task {normalized_task_id} updated to {normalized_status}"

    @staticmethod
    async def list_tasks(
            ctx: RunContext[AgentDeps], 
            status: Optional[str] = None,
            query: Optional[str] = None
    ) -> str:
        """List persisted tasks with optional status and text filters."""
        normalized_status: Optional[str] = None
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in VALID_TASK_STATUSES:
                allowed = ", ".join(sorted(VALID_TASK_STATUSES))
                raise ModelRetry(f"status must be one of: {allowed}.")

        normalized_query = query.strip() if query else None

        tasks, _, _ = get_task_manager(ctx.deps).list_tasks(
            status=normalized_status,
            query=normalized_query,
            limit=200,
        )

        if not tasks:
            status_msg = f" with status '{normalized_status}'" if normalized_status else ""
            query_msg = f" matching '{normalized_query}'" if normalized_query else ""
            return f"No tasks found{status_msg}{query_msg}."

        lines = [f"Found {len(tasks)} tasks:"]
        for t in tasks:
            instruction = t.args.get("instruction", "No instruction")
            payload = t.args.get("payload", {})
            lines.append(f"- ID: {t.id} | [{t.status}] {t.title}")
            lines.append(f"  Context: {_render_preview(instruction)}")
            if payload:
                lines.append(f"  Metadata: {payload}")

        return "\n".join(lines)

    @staticmethod
    async def create_schedule(
            ctx: RunContext[AgentDeps],
            name: str,
            cron_expression: str,
            instruction: str,
            timezone: Optional[str] = None,
    ) -> str:
        """Create a persisted schedule definition.

        Stores the name, cron expression, and instruction in the database. This
        tool does not execute the schedule.
        """
        schedule_manager = get_schedule_manager(ctx.deps)
        if not schedule_manager:
            raise ModelRetry("Schedule manager is not available.")
        try:
            schedule = await schedule_manager.create_schedule(
                name=name,
                cron_expression=cron_expression,
                instruction=instruction,
                timezone_name=timezone,
            )
        except ScheduleValidationError as exc:
            raise ModelRetry(str(exc)) from exc
        return f"Schedule '{schedule.name}' created with ID: {schedule.id}"

    @staticmethod
    async def update_schedule(
            ctx: RunContext[AgentDeps],
            schedule_id: str,
            name: Optional[str] = None,
            cron_expression: Optional[str] = None,
            instruction: Optional[str] = None,
            timezone: Optional[str] = None,
            enabled: Optional[bool] = None,
    ) -> str:
        """Update a persisted schedule definition.

        Editable fields are name, cron_expression, instruction, timezone, and enabled.
        """
        normalized_schedule_id = _require_non_empty("schedule_id", schedule_id)
        if all(
                value is None
                for value in (name, cron_expression, instruction, timezone, enabled)
        ):
            raise ModelRetry("At least one schedule field must be provided.")

        schedule_manager = get_schedule_manager(ctx.deps)
        if not schedule_manager:
            raise ModelRetry("Schedule manager is not available.")
        try:
            await schedule_manager.update_schedule(
                normalized_schedule_id,
                name=name,
                cron_expression=cron_expression,
                instruction=instruction,
                timezone_name=timezone,
                enabled=enabled,
            )
        except ScheduleNotFoundError as exc:
            raise ModelRetry(str(exc)) from exc
        except ScheduleValidationError as exc:
            raise ModelRetry(str(exc)) from exc

        return f"Schedule {normalized_schedule_id} updated"

    @staticmethod
    async def list_schedules(ctx: RunContext[AgentDeps]) -> str:
        """List persisted schedule definitions by creation recency."""
        schedule_manager = get_schedule_manager(ctx.deps)
        if not schedule_manager:
            raise ModelRetry("Schedule manager is not available.")
        schedules, _ = schedule_manager.list_schedules(limit=200)
        if not schedules:
            return "No schedules registered."
        lines = ["Registered Automated Routines:"]
        for s in schedules:
            status = "Enabled" if s.enabled else "Disabled"
            lines.append(f"- [{status}] ID: {s.id} | Name: {s.name} | Cron: {s.cron_expression}")
        return "\n".join(lines)
