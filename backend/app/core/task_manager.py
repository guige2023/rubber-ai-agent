from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String as SAString, func, or_
from sqlmodel import select

from app.core.db import get_session
from app.core.pagination import fetch_datetime_cursor_page
from app.models.database import TaskModel
from app.models.schemas import TaskStatus

logger = logging.getLogger(__name__)

VALID_TASK_STATUSES = frozenset({
    TaskStatus.PENDING,
    TaskStatus.RUNNING,
    TaskStatus.SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.CANCELED,
})


class TaskManagerError(Exception):
    """Base error for task manager operations."""


class TaskNotFoundError(TaskManagerError):
    """Raised when a task does not exist."""


class TaskValidationError(TaskManagerError, ValueError):
    """Raised when task input is invalid."""


def _require_non_empty(field_name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TaskValidationError(f"{field_name} must not be empty.")
    return normalized


class TaskManager:
    """Manage RabAiAgent task records and task state transitions."""

    @staticmethod
    def find_duplicate_task(title: str) -> Optional[TaskModel]:
        """Search for an existing active task using order-agnostic word similarity."""
        import difflib

        def normalize(text: str) -> str:
            cleaned = "".join(c if c.isalnum() else " " for c in (text or "").lower())
            return " ".join(sorted(cleaned.split()))

        norm_title = normalize(title)
        if not norm_title:
            return None

        with get_session() as session:
            statement = select(TaskModel).where(TaskModel.status.in_(["pending", "running"]))  # type:ignore
            candidates = session.exec(statement).all()

            for candidate in candidates:
                norm_candidate = normalize(candidate.title)
                ratio = difflib.SequenceMatcher(None, norm_title, norm_candidate).ratio()
                if ratio > 0.85:
                    logger.info(
                        f"Task deduplication: {title!r} matched {candidate.title!r} "
                        f"(normalized ratio {ratio:.2f})"
                    )
                    return candidate

        return None

    def create_task(
            self,
            *,
            session_id: str,
            title: str,
            instruction: Optional[str] = None,
            metadata: Optional[dict[str, object]] = None,
            parent_id: Optional[str] = None,
            args: Optional[dict[str, object]] = None,
    ) -> TaskModel:
        normalized_title = _require_non_empty("title", title)
        task_args = dict(args or {})
        if instruction is not None:
            task_args["instruction"] = _require_non_empty("instruction", instruction)
            task_args["payload"] = dict(metadata or {})
        return self.persist_task(
            session_id=session_id,
            title=normalized_title,
            parent_id=parent_id,
            args=task_args,
        )

    def persist_task(
            self,
            session_id: str,
            title: str,
            parent_id: Optional[str] = None,
            args: Optional[dict[str, object]] = None,
    ) -> TaskModel:
        existing = self.find_duplicate_task(title)
        if existing:
            return existing

        logger.debug(f"Creating task: {title} (session_id: {session_id}, parent_id: {parent_id})")
        task = TaskModel(
            session_id=session_id,
            parent_id=parent_id,
            title=title,
            args=args or {},
        )
        with get_session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            logger.debug(f"Task persisted to DB with ID: {task.id}")

        return task

    @staticmethod
    def get_task(task_id: str) -> TaskModel:
        normalized_task_id = _require_non_empty("task_id", task_id)
        with get_session() as session:
            task = session.get(TaskModel, normalized_task_id)
            if not task:
                raise TaskNotFoundError("Task not found")
            return task

    @staticmethod
    def list_tasks(
            *,
            session_id: Optional[str] = None,
            status: Optional[str] = None,
            query: Optional[str] = None,
            cursor: Optional[str] = None,
            limit: int = 50,
    ) -> tuple[list[TaskModel], Optional[str], dict[str, int]]:
        normalized_status: Optional[str] = None
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in VALID_TASK_STATUSES:
                allowed = ", ".join(sorted(VALID_TASK_STATUSES))
                raise TaskValidationError(f"status must be one of: {allowed}.")

        normalized_query = query.strip() if query else None

        with get_session() as session:
            base_filters = []
            if session_id:
                base_filters.append(TaskModel.session_id == session_id)
            if normalized_query:
                base_filters.append(
                    or_(
                        TaskModel.title.contains(normalized_query),
                        TaskModel.args.cast(SAString).contains(normalized_query),
                    )
                )

            statement = select(TaskModel).where(*base_filters)
            if normalized_status:
                statement = statement.where(TaskModel.status == normalized_status)

            tasks, next_cursor = fetch_datetime_cursor_page(
                session,
                statement,
                model=TaskModel,
                sort_field="updated_at",
                cursor=cursor,
                limit=limit,
            )

            status_counts = dict.fromkeys(sorted(VALID_TASK_STATUSES), 0)
            summary_rows = session.exec(
                select(TaskModel.status, func.count()).where(*base_filters).group_by(TaskModel.status)
            ).all()
            for row_status, count in summary_rows:
                status_counts[row_status] = count

            return tasks, next_cursor, {
                **status_counts,
                "total": sum(status_counts.values()),
            }

    def update_task(
            self,
            task_id: str,
            *,
            title: Optional[str] = None,
            status: Optional[str] = None,
            progress_note: Optional[str] = None,
            instruction: Optional[str] = None,
            payload: Optional[dict[str, object]] = None,
            metadata: Optional[dict[str, object]] = None,
    ) -> None:
        normalized_task_id = _require_non_empty("task_id", task_id)
        normalized_status: Optional[str] = None
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in VALID_TASK_STATUSES:
                allowed = ", ".join(sorted(VALID_TASK_STATUSES))
                raise TaskValidationError(f"status must be one of: {allowed}.")

        with get_session() as session:
            task = session.get(TaskModel, normalized_task_id)
            if not task:
                raise TaskNotFoundError("Task not found")

            if title is not None:
                task.title = title
            if normalized_status is not None:
                task.status = normalized_status
                task.finished_at = (
                    datetime.now(timezone.utc)
                    if normalized_status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELED}
                    else None
                )
            if progress_note is not None or metadata:
                next_metadata = dict(task.metadata_ or {})
                if progress_note is not None:
                    next_metadata["progress_note"] = progress_note
                if metadata:
                    next_metadata.update(metadata)
                task.metadata_ = next_metadata
            if instruction is not None or payload is not None:
                args = dict(task.args or {})
                if instruction is not None:
                    args["instruction"] = instruction
                if payload is not None:
                    args["payload"] = payload
                task.args = args

            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()

    @staticmethod
    def persist_task_update(
            task_id: str,
            status: Optional[str] = None,
            metadata: Optional[dict[str, object]] = None,
    ) -> None:
        logger.debug(f"Updating task {task_id}: status={status}, metadata={metadata}")
        with get_session() as session:
            statement = select(TaskModel).where(TaskModel.id == task_id)
            db_task = session.exec(statement).first()

            if not db_task:
                return

            if status:
                db_task.status = status
                if status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                    db_task.finished_at = datetime.now(timezone.utc)
            if metadata:
                next_metadata = dict(db_task.metadata_)
                next_metadata.update(metadata)
                db_task.metadata_ = next_metadata
            db_task.updated_at = datetime.now(timezone.utc)
            session.add(db_task)
            session.commit()

    @staticmethod
    def delete_task(task_id: str) -> None:
        normalized_task_id = _require_non_empty("task_id", task_id)
        with get_session() as session:
            task = session.get(TaskModel, normalized_task_id)
            if not task:
                raise TaskNotFoundError("Task not found")
            session.delete(task)
            session.commit()
