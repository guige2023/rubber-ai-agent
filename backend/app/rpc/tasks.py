from __future__ import annotations

import logging
from typing import Optional

from jsonrpcserver import Success, method

from app.core.task_manager import TaskNotFoundError, TaskValidationError
from app.models.schemas import TaskSchema

logger = logging.getLogger(__name__)


@method
async def list_tasks(
    context,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
):
    """List tasks, optionally filtered by session/status/query, with cursor-based pagination."""
    logger.debug(
        f"Listing tasks (session_id: {session_id}, status: {status}, query: {query}, cursor: {cursor}, limit: {limit})"
    )
    try:
        tasks, next_cursor, summary = context.task_manager.list_tasks(
            session_id=session_id,
            status=status,
            query=query,
            cursor=cursor,
            limit=limit,
        )
    except TaskValidationError as exc:
        return Success({"status": "error", "message": str(exc)})

    logger.debug(f"Found {len(tasks)} tasks")
    return Success({
        "tasks": [TaskSchema.model_validate(task).model_dump(mode="json") for task in tasks],
        "next_cursor": next_cursor,
        "summary": summary,
    })


@method
async def get_task(context, task_id: str):
    """Return a single task with editable details."""
    logger.debug(f"Fetching task detail: {task_id}")
    try:
        task = context.task_manager.get_task(task_id)
    except TaskNotFoundError:
        return Success({"status": "error", "message": "Task not found"})
    except TaskValidationError as exc:
        return Success({"status": "error", "message": str(exc)})
    else:
        return Success({"task": TaskSchema.model_validate(task).model_dump(mode="json")})


@method
async def update_task(
    context,
    task_id: str,
    title: Optional[str] = None,
    status: Optional[str] = None,
    progress_note: Optional[str] = None,
    instruction: Optional[str] = None,
    payload: Optional[dict[str, object]] = None,
):
    """Update editable task fields."""
    logger.info(f"Updating task: {task_id}")
    try:
        context.task_manager.update_task(
            task_id,
            title=title,
            status=status,
            progress_note=progress_note,
            instruction=instruction,
            payload=payload,
        )
    except TaskNotFoundError:
        return Success({"status": "error", "message": "Task not found"})
    except TaskValidationError as exc:
        return Success({"status": "error", "message": str(exc)})
    return Success({"status": "success"})


@method
async def delete_task(context, task_id: str):
    """Delete a task."""
    logger.info(f"Deleting task: {task_id}")
    try:
        context.task_manager.delete_task(task_id)
    except TaskNotFoundError:
        return Success({"status": "error", "message": "Task not found"})
    except TaskValidationError as exc:
        return Success({"status": "error", "message": str(exc)})
    return Success({"status": "success"})
