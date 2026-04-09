from typing import Optional, Any, Dict, List
from datetime import datetime
from pydantic_ai.tools import RunContext
from app.core.deps import AgentDeps
from app.core.db import get_session
from app.models.database import Schedule, Task
from sqlalchemy import String as SAString, or_
from sqlmodel import select

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
            ctx: RunContext[AgentDeps],
            title: str,
            instruction: str,
            metadata: Optional[Dict[str, Any]] = None,
            parent_id: Optional[str] = None
    ) -> str:
        """Register a persistent task for later execution and cross-session tracking.
        
        This tool uses 'title' for global, fuzzy deduplication. If a similar active 
        task exists, it will link to it rather than creating a new one.

        Args:
            title: The unique 'fingerprint' of this task. Should include the Action 
                   and the Target Entity (e.g. 'Submit example.com to AlternativeTo.net'). 
                   Keep it consistent to prevent redundant work.
            instruction: A detailed SOP or goal for the next agent. Explain exactly 
                         WHAT should be done and what success looks like.
            metadata: Technical 'hooks' and context. Include entities like domains, 
                      URLs, or usernames to allow fuzzy searching via 'list_tasks'.
            parent_id: The ID of a parent task, if this is a sub-step of a larger workflow.

        Example:
            create_task(
                title='Monitor prices for SKU-123',
                instruction='Check site X every 1h and report if price < $100',
                metadata={'sku': '123', 'site': 'X'}
            )
        """
        kernel = ctx.deps.kernel
        session_id = ctx.deps.session_id

        # Package data for the kernel (decoupling Skill from DB schema)
        task_args = {
            "instruction": instruction,
            "payload": metadata or {}
        }

        task = kernel.persist_task(
            session_id=session_id,
            title=title,
            parent_id=parent_id,
            args=task_args
        )
        return f"Task created/verified: ID={task.id}, Title='{task.title}'"

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
    async def list_tasks(
            ctx: RunContext[AgentDeps], 
            status: Optional[str] = None,
            query: Optional[str] = None
    ) -> str:
        """List tasks globally. Use status='pending' to find new work. Use query='domain.com' for fuzzy search."""
        with get_session() as db_session:
            statement = select(Task)
            if status:
                statement = statement.where(Task.status == status)
            if query:
                # Fuzzy match in Title or Instruction
                # Note: args is a JSON column, so we cast to string for partial search
                statement = statement.where(
                    or_(
                        Task.title.contains(query),
                        Task.args.cast(SAString).contains(query)
                    )
                )
            
            tasks = db_session.exec(statement).all()
            
            if not tasks:
                status_msg = f" with status '{status}'" if status else ""
                query_msg = f" matching '{query}'" if query else ""
                return f"No tasks found{status_msg}{query_msg}."

            lines = [f"Found {len(tasks)} tasks:"]
            for t in tasks:
                instruction = t.args.get("instruction", "No instruction")
                payload = t.args.get("payload", {})
                lines.append(f"- ID: {t.id} | [{t.status}] {t.title}")
                lines.append(f"  Context: {instruction[:120]}...")
                if payload:
                    lines.append(f"  Metadata: {payload}")
            
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
