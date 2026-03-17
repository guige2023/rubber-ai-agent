from typing import Optional
from datetime import datetime
from pydantic_ai import RunContext
from app.core.deps import AgentDeps
from app.core.db import get_session
from app.models.database import Schedule

class TaskToolkit:
    """Tools for persistent Task tracking and automated Schedules."""

    @staticmethod
    def get_tools():
        return [
            TaskToolkit.create_task,
            TaskToolkit.update_task,
            TaskToolkit.list_tasks,
            TaskToolkit.create_schedule,
            TaskToolkit.list_schedules,
        ]

    @staticmethod
    async def create_task(
            ctx: RunContext[AgentDeps], title: str, instruction: str
    ) -> str:
        """Register a persistent Task record. Returns a task_id."""
        kernel = ctx.deps.kernel
        task = kernel.persist_task(
            session_id=ctx.deps.session_id, 
            title=title, 
            args={"instruction": instruction}
        )
        return task.id

    @staticmethod
    async def update_task(
            ctx: RunContext[AgentDeps], task_id: str, status: str, progress_note: Optional[str] = None
    ) -> str:
        """Update Task state ('pending', 'running', 'success', 'failed', 'canceled')."""
        kernel = ctx.deps.kernel
        meta = {"progress_note": progress_note} if progress_note else None
        kernel.persist_task_update(task_id, status=status, metadata=meta)
        return f"Task {task_id} updated to {status}"

    @staticmethod
    async def list_tasks(ctx: RunContext[AgentDeps]) -> str:
        """List all orchestration tasks for the current session."""
        kernel = ctx.deps.kernel
        session_id = ctx.deps.session_id
        relevant = [t for t in kernel.tasks.values() if t.session_id == session_id]
        if not relevant:
            return "No tasks found for this session."

        lines = ["Current Orchestration Tasks:"]
        for t in relevant:
            lines.append(f"- ID: {t.id} | Title: {t.title} | Status: {t.status}")
        return "\n".join(lines)

    @staticmethod
    async def create_schedule(
            ctx: RunContext[AgentDeps], name: str, cron_expression: str, instruction: str
    ) -> str:
        """Register a recurring execution schedule."""
        new_schedule = Schedule(
            name=name,
            cron_expression=cron_expression,
            args={"instruction": instruction}
        )
        with get_session() as session:
            session.add(new_schedule)
            session.commit()
            session.refresh(new_schedule)
        return f"Schedule '{name}' created with ID: {new_schedule.id}"

    @staticmethod
    async def list_schedules(ctx: RunContext[AgentDeps]) -> str:
        """List all automated routines."""
        with get_session() as session:
            from sqlmodel import select
            schedules = session.exec(select(Schedule)).all()
            if not schedules:
                return "No schedules registered."
            lines = ["Registered Automated Routines:"]
            for s in schedules:
                status = "Enabled" if s.enabled else "Disabled"
                lines.append(f"- [{status}] ID: {s.id} | Name: {s.name} | Cron: {s.cron_expression}")
            return "\n".join(lines)
