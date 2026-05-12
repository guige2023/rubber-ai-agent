from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.exceptions import ModelRetry
from sqlalchemy import text
from sqlmodel import select

import app.core.task_manager as task_manager_module
from app.core.schedule_manager import ScheduleManager
from app.core.task_manager import TaskManager
from app.core.toolkits.task import TaskToolkit
from app.models.database import ScheduleModel, TaskModel


_UNSET = object()


def make_schedule_manager() -> ScheduleManager:
    schedule_manager = ScheduleManager(SimpleNamespace(), SimpleNamespace())
    schedule_manager.sync_schedule = AsyncMock()
    schedule_manager.remove_schedule = AsyncMock()
    return schedule_manager


def make_ctx(*, task_manager=_UNSET, schedule_manager=_UNSET, session_id: str = "session-1"):
    if task_manager is _UNSET:
        task_manager = TaskManager()
    if schedule_manager is _UNSET:
        schedule_manager = make_schedule_manager()
    return SimpleNamespace(
        deps=SimpleNamespace(
            task_manager=task_manager,
            schedule_manager=schedule_manager,
            session_id=session_id,
        )
    )


class StubTaskManager:
    def __init__(self) -> None:
        self.persist_task_calls: list[dict] = []
        self.persist_task_update_calls: list[dict] = []

    def persist_task(self, *, session_id: str, title: str, parent_id: str | None, args: dict):
        self.persist_task_calls.append({
            "session_id": session_id,
            "title": title,
            "parent_id": parent_id,
            "args": args,
        })
        return SimpleNamespace(id="task-123", title=title)

    def create_task(
            self,
            *,
            session_id: str,
            title: str,
            instruction: str,
            metadata: dict | None = None,
            parent_id: str | None = None,
    ):
        return self.persist_task(
            session_id=session_id,
            title=title,
            parent_id=parent_id,
            args={
                "instruction": instruction,
                "payload": dict(metadata or {}),
            },
        )

    def persist_task_update(self, task_id: str, *, status: str, metadata: dict | None = None) -> None:
        self.persist_task_update_calls.append({
            "task_id": task_id,
            "status": status,
            "metadata": metadata,
        })

    def update_task(self, task_id: str, *, status: str, progress_note: str | None = None) -> None:
        metadata = {"progress_note": progress_note} if progress_note is not None else None
        self.persist_task_update(task_id, status=status, metadata=metadata)


@pytest.mark.asyncio
async def test_create_task_packages_instruction_metadata_and_parent_id():
    task_manager = StubTaskManager()
    ctx = make_ctx(task_manager=task_manager, session_id="session-alpha")

    result = await TaskToolkit.create_task(
        ctx,
        title="  Monitor SKU-123  ",
        instruction="  Check site X every hour and report when price drops.  ",
        metadata={"sku": "123", "site": "X"},
        parent_id="parent-1",
    )

    assert result == "Task created/verified: ID=task-123, Title='Monitor SKU-123'"
    assert task_manager.persist_task_calls == [{
        "session_id": "session-alpha",
        "title": "Monitor SKU-123",
        "parent_id": "parent-1",
        "args": {
            "instruction": "Check site X every hour and report when price drops.",
            "payload": {"sku": "123", "site": "X"},
        },
    }]


@pytest.mark.asyncio
async def test_create_task_uses_task_manager_when_provided():
    task_manager = StubTaskManager()
    ctx = make_ctx(task_manager=task_manager, session_id="session-manager")

    result = await TaskToolkit.create_task(
        ctx,
        title="Manager task",
        instruction="Use the injected manager.",
    )

    assert "Task created/verified" in result
    assert task_manager.persist_task_calls[0]["session_id"] == "session-manager"


@pytest.mark.asyncio
async def test_create_task_defaults_metadata_to_empty_payload():
    task_manager = StubTaskManager()
    ctx = make_ctx(task_manager=task_manager)

    await TaskToolkit.create_task(
        ctx,
        title="Collect competitor pricing",
        instruction="Capture the current price sheet and summarize major deltas.",
    )

    assert task_manager.persist_task_calls[0]["args"]["payload"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "instruction", "expected_message"),
    [
        ("   ", "valid instruction", "title must not be empty."),
        ("Valid title", "   ", "instruction must not be empty."),
    ],
)
async def test_create_task_rejects_blank_required_fields(title, instruction, expected_message):
    task_manager = StubTaskManager()
    ctx = make_ctx(task_manager=task_manager)

    with pytest.raises(ModelRetry, match=expected_message):
        await TaskToolkit.create_task(ctx, title=title, instruction=instruction)


@pytest.mark.asyncio
async def test_update_task_forwards_status_and_allows_clearing_progress_note():
    task_manager = StubTaskManager()
    ctx = make_ctx(task_manager=task_manager)

    result = await TaskToolkit.update_task(ctx, task_id="task-77", status="RUNNING", progress_note="")

    assert result == "Task task-77 updated to running"
    assert task_manager.persist_task_update_calls == [{
        "task_id": "task-77",
        "status": "running",
        "metadata": {"progress_note": ""},
    }]


@pytest.mark.asyncio
async def test_update_task_rejects_invalid_status():
    task_manager = StubTaskManager()
    ctx = make_ctx(task_manager=task_manager)

    with pytest.raises(ModelRetry, match="status must be one of:"):
        await TaskToolkit.update_task(ctx, task_id="task-77", status="queued")


@pytest.mark.asyncio
async def test_list_tasks_returns_helpful_empty_messages():
    ctx = make_ctx()

    assert await TaskToolkit.list_tasks(ctx) == "No tasks found."
    assert (
        await TaskToolkit.list_tasks(ctx, status="pending", query="example.com")
        == "No tasks found with status 'pending' matching 'example.com'."
    )


@pytest.mark.asyncio
async def test_list_tasks_filters_orders_and_formats_results(session):
    now = datetime.now(timezone.utc)
    session.add_all([
        TaskModel(
            id="task-old",
            session_id="session-a",
            title="Old task",
            status="running",
            args={"instruction": "This older task should be filtered out by query.", "payload": {}},
            updated_at=now - timedelta(minutes=5),
        ),
        TaskModel(
            id="task-match-new",
            session_id="session-b",
            title="Submit example.com to Product Hunt",
            status="pending",
            args={
                "instruction": "Investigate the submission requirements for example.com and prepare the draft.",
                "payload": {"domain": "example.com", "channel": "product-hunt"},
            },
            updated_at=now,
        ),
        TaskModel(
            id="task-match-old",
            session_id="session-c",
            title="Submit docs.example.com to Directory",
            status="pending",
            args={
                "instruction": "Use the docs site pitch and include the launch summary in the submission.",
                "payload": {"domain": "docs.example.com"},
            },
            updated_at=now - timedelta(minutes=1),
        ),
    ])
    session.commit()

    result = await TaskToolkit.list_tasks(make_ctx(), status="PENDING", query="example.com")

    assert "Found 2 tasks:" in result
    assert result.index("task-match-new") < result.index("task-match-old")
    assert "- ID: task-match-new | [pending] Submit example.com to Product Hunt" in result
    assert "Metadata: {'domain': 'example.com', 'channel': 'product-hunt'}" in result
    assert "task-old" not in result


@pytest.mark.asyncio
async def test_list_tasks_rejects_invalid_status():
    with pytest.raises(ModelRetry, match="status must be one of:"):
        await TaskToolkit.list_tasks(make_ctx(), status="later")


def test_kernel_persist_task_update_writes_utc_timestamps(session, monkeypatch):
    task = TaskModel(
        id="task-utc-update",
        session_id="session-utc",
        title="UTC task",
        status="running",
        args={"instruction": "Keep task timestamps in UTC."},
    )
    session.add(task)
    session.commit()

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            if tz is timezone.utc:
                return datetime(2026, 4, 20, 2, 0, 0, tzinfo=timezone.utc)
            return datetime(2026, 4, 20, 10, 0, 0)

    monkeypatch.setattr(task_manager_module, "datetime", FakeDateTime)

    task_manager = TaskManager()

    task_manager.persist_task_update(
        "task-utc-update",
        status="success",
        metadata={"progress_note": "done"},
    )

    session.expire_all()
    refreshed = session.get(TaskModel, "task-utc-update")
    assert refreshed is not None
    assert refreshed.status == "success"
    assert refreshed.finished_at == datetime(2026, 4, 20, 2, 0, 0, tzinfo=timezone.utc)
    assert refreshed.updated_at == datetime(2026, 4, 20, 2, 0, 0, tzinfo=timezone.utc)

    row = session.execute(
        text("SELECT finished_at, updated_at FROM tasks WHERE id = :task_id"),
        {"task_id": task.id},
    ).one()
    assert row[0] == "2026-04-20 02:00:00.000000"
    assert row[1] == "2026-04-20 02:00:00.000000"


@pytest.mark.asyncio
async def test_create_schedule_persists_instruction_and_leaves_runtime_fields_empty(session):
    result = await TaskToolkit.create_schedule(
        make_ctx(),
        name="  Morning sync  ",
        cron_expression=" 0 8 * * * ",
        instruction="  Run the daily sync workflow and summarize failures. ",
    )

    schedule = session.exec(select(ScheduleModel)).one()

    assert result == f"Schedule 'Morning sync' created with ID: {schedule.id}"
    assert schedule.name == "Morning sync"
    assert schedule.cron_expression == "0 8 * * *"
    assert schedule.timezone == "UTC"
    assert schedule.args == {"instruction": "Run the daily sync workflow and summarize failures."}
    assert schedule.last_run_at is None
    assert schedule.next_run_at is not None
    assert schedule.enabled is True
    assert schedule.total_run_count == 0
    assert schedule.last_run_result is None


@pytest.mark.asyncio
async def test_create_schedule_syncs_schedule_manager_when_available(session):
    schedule_manager = make_schedule_manager()

    result = await TaskToolkit.create_schedule(
        make_ctx(schedule_manager=schedule_manager),
        name="Hourly check",
        cron_expression="0 * * * *",
        instruction="Run the hourly check.",
    )

    schedule = session.exec(select(ScheduleModel)).one()
    assert result == f"Schedule 'Hourly check' created with ID: {schedule.id}"
    schedule_manager.sync_schedule.assert_awaited_once_with(schedule.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "cron_expression", "instruction", "expected_message"),
    [
        ("", "0 * * * *", "run it", "name must not be empty."),
        ("Hourly", "   ", "run it", "cron_expression must not be empty."),
        ("Hourly", "0 * * * *", "   ", "instruction must not be empty."),
    ],
)
async def test_create_schedule_rejects_blank_required_fields(
    name,
    cron_expression,
    instruction,
    expected_message,
):
    with pytest.raises(ModelRetry, match=expected_message):
        await TaskToolkit.create_schedule(
            make_ctx(),
            name=name,
            cron_expression=cron_expression,
            instruction=instruction,
        )


@pytest.mark.asyncio
async def test_update_schedule_persists_editable_fields_and_syncs_schedule_manager(session):
    schedule = ScheduleModel(
        id="schedule-update",
        name="Nightly",
        cron_expression="0 0 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Initial instruction"},
    )
    session.add(schedule)
    session.commit()

    schedule_manager = make_schedule_manager()

    result = await TaskToolkit.update_schedule(
        make_ctx(schedule_manager=schedule_manager),
        schedule_id=" schedule-update ",
        name="  Morning check  ",
        cron_expression=" 0 8 * * * ",
        instruction="  Updated instruction.  ",
        timezone="Asia/Shanghai",
        enabled=False,
    )

    session.expire_all()
    refreshed = session.get(ScheduleModel, "schedule-update")

    assert result == "Schedule schedule-update updated"
    assert refreshed is not None
    assert refreshed.name == "Morning check"
    assert refreshed.cron_expression == "0 8 * * *"
    assert refreshed.timezone == "Asia/Shanghai"
    assert refreshed.enabled is False
    assert refreshed.args == {"instruction": "Updated instruction."}
    assert refreshed.next_run_at is None
    assert refreshed.updated_at > schedule.created_at
    schedule_manager.sync_schedule.assert_awaited_once_with("schedule-update")


@pytest.mark.asyncio
async def test_update_schedule_reenables_schedule_and_restores_next_run(session):
    schedule = ScheduleModel(
        id="schedule-reenable-tool",
        name="Re-enable me",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=False,
        args={"instruction": "Run again"},
        next_run_at=None,
    )
    session.add(schedule)
    session.commit()

    result = await TaskToolkit.update_schedule(
        make_ctx(),
        schedule_id="schedule-reenable-tool",
        enabled=True,
    )

    session.expire_all()
    refreshed = session.get(ScheduleModel, "schedule-reenable-tool")

    assert result == "Schedule schedule-reenable-tool updated"
    assert refreshed is not None
    assert refreshed.enabled is True
    assert refreshed.next_run_at is not None


@pytest.mark.asyncio
async def test_update_schedule_can_disable_invalid_persisted_schedule(session):
    schedule = ScheduleModel(
        id="schedule-invalid-disable-tool",
        name="Broken schedule",
        cron_expression="not-a-cron",
        timezone="Mars/Base",
        enabled=True,
        args={"instruction": "Still disable me"},
        next_run_at=datetime.now(timezone.utc),
    )
    session.add(schedule)
    session.commit()

    result = await TaskToolkit.update_schedule(
        make_ctx(),
        schedule_id="schedule-invalid-disable-tool",
        enabled=False,
    )

    session.expire_all()
    refreshed = session.get(ScheduleModel, "schedule-invalid-disable-tool")

    assert result == "Schedule schedule-invalid-disable-tool updated"
    assert refreshed is not None
    assert refreshed.enabled is False
    assert refreshed.next_run_at is None


@pytest.mark.asyncio
async def test_update_schedule_rejects_missing_or_invalid_input(session):
    schedule = ScheduleModel(
        id="schedule-invalid-input",
        name="Editable",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run it"},
    )
    session.add(schedule)
    session.commit()

    with pytest.raises(ModelRetry, match="At least one schedule field must be provided."):
        await TaskToolkit.update_schedule(make_ctx(), schedule_id="schedule-invalid-input")

    with pytest.raises(ModelRetry, match="name must not be empty."):
        await TaskToolkit.update_schedule(
            make_ctx(),
            schedule_id="schedule-invalid-input",
            name="   ",
        )

    with pytest.raises(ModelRetry, match="cron_expression must not be empty."):
        await TaskToolkit.update_schedule(
            make_ctx(),
            schedule_id="schedule-invalid-input",
            cron_expression="   ",
        )

    with pytest.raises(ModelRetry, match="Invalid timezone: Mars/Base"):
        await TaskToolkit.update_schedule(
            make_ctx(),
            schedule_id="schedule-invalid-input",
            timezone="Mars/Base",
        )


@pytest.mark.asyncio
async def test_list_schedules_returns_empty_message():
    assert await TaskToolkit.list_schedules(make_ctx()) == "No schedules registered."


@pytest.mark.asyncio
async def test_list_schedules_orders_results_and_displays_enabled_state(session):
    now = datetime.now(timezone.utc)
    session.add_all([
        ScheduleModel(
            id="schedule-created-new",
            name="Morning report",
            cron_expression="0 8 * * *",
            enabled=True,
            created_at=now,
            updated_at=now - timedelta(hours=1),
        ),
        ScheduleModel(
            id="schedule-updated-new",
            name="Nightly crawl",
            cron_expression="0 2 * * *",
            enabled=False,
            created_at=now - timedelta(hours=1),
            updated_at=now,
        ),
    ])
    session.commit()

    result = await TaskToolkit.list_schedules(make_ctx())

    assert result.startswith("Registered Automated Routines:")
    assert result.index("schedule-created-new") < result.index("schedule-updated-new")
    assert "- [Enabled] ID: schedule-created-new | Name: Morning report | Cron: 0 8 * * *" in result
    assert "- [Disabled] ID: schedule-updated-new | Name: Nightly crawl | Cron: 0 2 * * *" in result
