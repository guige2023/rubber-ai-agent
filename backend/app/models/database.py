from datetime import datetime, timezone
from typing import Optional

import shortuuid
from sqlalchemy import Column as SAColumn
from sqlalchemy import DateTime
from sqlalchemy import event
from sqlalchemy.orm.attributes import set_committed_value
from sqlmodel import SQLModel, Field, JSON


class SessionModel(SQLModel, table=True):
    __tablename__ = "sessions"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    title: str = Field(default="")
    memory: Optional[dict[str, object]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )

class MessageModel(SQLModel, table=True):
    __tablename__ = "messages"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    session_id: str = Field(index=True)
    role: str  # user, assistant, system, tool
    content: str
    parts: list[dict[str, object]] = Field(default_factory=list, sa_column=SAColumn(JSON))
    type: str  # text, tool_call, tool_result, thinking
    token_estimate: int = Field(default=0)
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )

class TaskModel(SQLModel, table=True):
    __tablename__ = "tasks"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    session_id: str = Field(index=True)
    parent_id: Optional[str] = None
    title: str
    args: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    status: str = Field(default="pending")  # pending, running, success, failed, canceled
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )
    finished_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(DateTime(timezone=True), nullable=True))

class ScheduleModel(SQLModel, table=True):
    __tablename__ = "schedules"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    name: str
    args: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    cron_expression: str
    timezone: str = Field(default="UTC")
    enabled: bool = Field(default=True)
    last_run_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(DateTime(timezone=True), nullable=True))
    next_run_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(DateTime(timezone=True), nullable=True))
    total_run_count: int = Field(default=0)
    last_run_result: Optional[dict[str, object]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )

class TriggerModel(SQLModel, table=True):
    __tablename__ = "triggers"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    name: str
    type: str = Field(default="webhook")  # webhook | file_watch | schedule | mqtt
    config: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    instruction: str = Field(default="")
    enabled: bool = Field(default=True)
    last_triggered_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(DateTime(timezone=True), nullable=True))
    trigger_count: int = Field(default=0)
    last_run_result: Optional[dict[str, object]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )


class AppConfigModel(SQLModel, table=True):
    __tablename__ = "app_configs"
    key: str = Field(primary_key=True)  # e.g., "llm.openai.api_key", "system.llm.active_model"
    value: object = Field(sa_column=SAColumn(JSON))
    category: str = Field(index=True)  # e.g., "llm", "system"
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True), nullable=False),
    )


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_datetime_fields(target: object) -> None:
    field_names = {
        SessionModel: ("created_at", "updated_at"),
        MessageModel: ("created_at",),
        TaskModel: ("created_at", "updated_at", "finished_at"),
        ScheduleModel: ("last_run_at", "next_run_at", "created_at", "updated_at"),
        TriggerModel: ("last_triggered_at", "created_at", "updated_at"),
        AppConfigModel: ("updated_at",),
    }.get(type(target), ())
    for field_name in field_names:
        set_committed_value(target, field_name, _as_utc_datetime(getattr(target, field_name, None)))


def _normalize_on_load(target: object, context: object) -> None:
    _normalize_datetime_fields(target)


def _normalize_on_refresh(target: object, context: object, attrs: object) -> None:
    _normalize_datetime_fields(target)


for _model in (SessionModel, MessageModel, TaskModel, ScheduleModel, TriggerModel, AppConfigModel):
    event.listen(_model, "load", _normalize_on_load)
    event.listen(_model, "refresh", _normalize_on_refresh)
