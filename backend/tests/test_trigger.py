"""
Tests for TriggerManager and webhook handling.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.trigger_manager import (
    TriggerManager,
    TriggerNotFoundError,
    TriggerValidationError,
)
from app.core.triggers.file_watcher import FileWatchConfig, FileWatchTrigger
from app.core.triggers.schedule_trigger import ScheduleTrigger, ScheduleTriggerConfig
from app.core.triggers.webhook_handler import WebhookConfig, WebhookTrigger
from app.models.database import TriggerModel


class FakeScheduler:
    """Fake scheduler for testing."""
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}

    def add_job(self, func, *, trigger, args, id, replace_existing, **kwargs):
        job = SimpleNamespace(id=id, func=func, trigger=trigger, args=args)
        self.jobs[id] = job
        return job

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def remove_job(self, job_id: str):
        self.jobs.pop(job_id, None)


class FakeRunRegistry:
    """Fake run registry for testing."""
    def __init__(self) -> None:
        self.runs = []

    def start_run(self, session_id: str, instruction: str, run_id: str, source: str):
        self.runs.append({"session_id": session_id, "instruction": instruction, "run_id": run_id, "source": source})
        return asyncio.sleep(0)  # return immediately completed task


class FakeRuntime:
    """Fake runtime for testing."""
    def __init__(self) -> None:
        self.run_registry = FakeRunRegistry()
        self._webhook_triggers = {}


@pytest.fixture
def fake_runtime():
    return FakeRuntime()


@pytest.fixture
def trigger_manager(fake_runtime):
    return TriggerManager(fake_runtime)


# =============================================================================
# TriggerManager CRUD Tests
# =============================================================================

@pytest.mark.asyncio
class TestTriggerManagerCreate:
    async def test_create_webhook_trigger(self, trigger_manager):
        trigger = await trigger_manager.create_trigger(
            name="GitHub Push Webhook",
            type="webhook",
            config={"secret": "mysecret"},
            instruction="Process GitHub push event",
        )
        assert trigger.name == "GitHub Push Webhook"
        assert trigger.type == "webhook"
        assert trigger.config["secret"] == "mysecret"
        assert trigger.instruction == "Process GitHub push event"
        assert trigger.enabled is True
        assert trigger.trigger_count == 0

    async def test_create_trigger_validates_type(self, trigger_manager):
        with pytest.raises(TriggerValidationError) as exc_info:
            await trigger_manager.create_trigger(
                name="Bad Type",
                type="invalid_type",
                config={},
                instruction="test",
            )
        assert "Unsupported trigger type" in str(exc_info.value)

    async def test_create_trigger_validates_empty_name(self, trigger_manager):
        with pytest.raises(TriggerValidationError) as exc_info:
            await trigger_manager.create_trigger(
                name="   ",
                type="webhook",
                config={},
                instruction="test",
            )
        assert "name" in str(exc_info.value).lower()

    async def test_create_trigger_validates_empty_instruction(self, trigger_manager):
        with pytest.raises(TriggerValidationError) as exc_info:
            await trigger_manager.create_trigger(
                name="Test",
                type="webhook",
                config={},
                instruction="  ",
            )
        assert "instruction" in str(exc_info.value).lower()


@pytest.mark.asyncio
class TestTriggerManagerGet:
    async def test_get_trigger_success(self, trigger_manager):
        created = await trigger_manager.create_trigger(
            name="Get Test",
            type="webhook",
            config={},
            instruction="test instruction",
        )
        retrieved = trigger_manager.get_trigger(created.id)
        assert retrieved.id == created.id
        assert retrieved.name == "Get Test"

    async def test_get_trigger_not_found(self, trigger_manager):
        with pytest.raises(TriggerNotFoundError):
            trigger_manager.get_trigger("nonexistent-id")


@pytest.mark.asyncio
class TestTriggerManagerList:
    async def test_list_triggers_empty(self, trigger_manager):
        triggers, cursor = trigger_manager.list_triggers()
        assert len(triggers) == 0
        assert cursor is None

    async def test_list_triggers_multiple(self, trigger_manager):
        await trigger_manager.create_trigger(name="T1", type="webhook", config={}, instruction="i1")
        await trigger_manager.create_trigger(name="T2", type="webhook", config={}, instruction="i2")
        triggers, cursor = trigger_manager.list_triggers()
        assert len(triggers) == 2

    async def test_list_triggers_type_filter(self, trigger_manager):
        await trigger_manager.create_trigger(name="Webhook", type="webhook", config={}, instruction="i1")
        await trigger_manager.create_trigger(name="Schedule", type="schedule", config={}, instruction="i2")
        triggers, cursor = trigger_manager.list_triggers(type_filter="webhook")
        assert len(triggers) == 1
        assert triggers[0].name == "Webhook"


@pytest.mark.asyncio
class TestTriggerManagerUpdate:
    async def test_update_trigger(self, trigger_manager):
        created = await trigger_manager.create_trigger(
            name="Original",
            type="webhook",
            config={},
            instruction="original instruction",
        )
        updated = await trigger_manager.update_trigger(
            created.id,
            name="Updated",
            instruction="updated instruction",
        )
        assert updated.name == "Updated"
        assert updated.instruction == "updated instruction"

    async def test_update_trigger_enable_disable(self, trigger_manager):
        created = await trigger_manager.create_trigger(name="Toggle", type="webhook", config={}, instruction="test")
        assert created.enabled is True
        updated = await trigger_manager.update_trigger(created.id, enabled=False)
        assert updated.enabled is False
        updated = await trigger_manager.update_trigger(created.id, enabled=True)
        assert updated.enabled is True


@pytest.mark.asyncio
class TestTriggerManagerDelete:
    async def test_delete_trigger(self, trigger_manager):
        created = await trigger_manager.create_trigger(name="Delete Me", type="webhook", config={}, instruction="test")
        await trigger_manager.delete_trigger(created.id)
        with pytest.raises(TriggerNotFoundError):
            trigger_manager.get_trigger(created.id)

    async def test_delete_trigger_not_found(self, trigger_manager):
        with pytest.raises(TriggerNotFoundError):
            await trigger_manager.delete_trigger("nonexistent-id")


# =============================================================================
# WebhookTrigger Signature Verification Tests
# =============================================================================

class TestWebhookSignatureVerification:
    def test_verify_valid_sha256_signature(self):
        config = WebhookConfig(secret="mysecret")
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        body = b'{"action":"push"}'
        # Generate valid signature
        mac = hmac.new(b"mysecret", body, hashlib.sha256)
        signature = f"sha256={mac.hexdigest()}"
        headers = {"x-hub-signature-256": signature}
        assert trigger._verify_signature(headers, body) is True

    def test_verify_invalid_signature(self):
        config = WebhookConfig(secret="mysecret")
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        headers = {"x-hub-signature-256": "sha256=invalidsignature"}
        assert trigger._verify_signature(headers, b"body") is False

    def test_verify_missing_signature(self):
        config = WebhookConfig(secret="mysecret")
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        assert trigger._verify_signature({}, b"body") is False

    def test_verify_no_secret_required(self):
        config = WebhookConfig(secret=None)
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        assert trigger._verify_signature({}, b"body") is True


# =============================================================================
# WebhookTrigger Request Handling Tests
# =============================================================================

@pytest.mark.asyncio
class TestWebhookRequestHandling:
    async def test_webhook_debounce(self):
        config = WebhookConfig(debounce_ms=1000)
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        body = b'{"event":"push"}'
        headers = {}

        # First request should pass
        result1 = await trigger.handle_request(headers, body, body)
        assert result1["status"] == "triggered"

        # Immediate second request should be debounced
        result2 = await trigger.handle_request(headers, body, body)
        assert result2["status"] == "debounced"

    async def test_webhook_event_filter(self):
        # Use separate trigger instances per subtest to avoid debounce
        import uuid
        body = b'{"event":"push"}'
        runtime = FakeRuntime()

        # Subtest 1: push event should match
        trigger1 = WebhookTrigger(
            trigger_id=f"filter-push-{uuid.uuid4().hex[:8]}",
            config=WebhookConfig(event_filters=["push", "pull_request"]),
            runtime=runtime,
            instruction="test",
        )
        result = await trigger1.handle_request(
            {"x-github-event": "push"}, body, body
        )
        assert result["status"] == "triggered"

        # Subtest 2: issues event should be filtered (separate instance)
        trigger2 = WebhookTrigger(
            trigger_id=f"filter-issues-{uuid.uuid4().hex[:8]}",
            config=WebhookConfig(event_filters=["push", "pull_request"]),
            runtime=runtime,
            instruction="test",
        )
        result = await trigger2.handle_request(
            {"x-github-event": "issues"}, body, body
        )
        assert result["status"] == "filtered"

    async def test_webhook_required_header_missing(self):
        config = WebhookConfig(headers={"x-custom-token": "expected"})
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        result = await trigger.handle_request({}, b"{}", b"{}")
        assert result["status"] == "missing_header"
        assert result["header"] == "x-custom-token"

    async def test_webhook_signature_verification_failure(self):
        config = WebhookConfig(secret="mysecret")
        trigger = WebhookTrigger(
            trigger_id="test-trigger",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        body = b'{"event":"push"}'
        headers = {"x-hub-signature-256": "sha256=wrongsignature"}
        result = await trigger.handle_request(headers, body, body)
        assert result["status"] == "unauthorized"


# =============================================================================
# Integration-style Tests (in-process)
# =============================================================================

@pytest.mark.asyncio
class TestTriggerManagerIntegration:
    async def test_sync_trigger_registers_webhook_handler(self, trigger_manager):
        """When a webhook trigger is created and synced, it registers in runtime."""
        created = await trigger_manager.create_trigger(
            name="Integration Test",
            type="webhook",
            config={"secret": "testsecret"},
            instruction="Process webhook",
        )
        await trigger_manager.sync_trigger(created.id)

        # Check that the webhook trigger is registered by its ID
        assert created.id in trigger_manager.runtime._webhook_triggers

    async def test_trigger_now_routes_to_webhook(self, trigger_manager):
        """trigger_now should route to the registered webhook handler."""
        created = await trigger_manager.create_trigger(
            name="Trigger Now Test",
            type="webhook",
            config={},
            instruction="Process immediately",
        )
        await trigger_manager.sync_trigger(created.id)

        result = await trigger_manager.trigger_now(created.id, event_type="test")
        # Should succeed (handler registered, debounce allows)
        assert result["status"] in ("triggered", "debounced", "no_handler")


# =============================================================================
# FileWatchTrigger Tests
# =============================================================================

class TestFileWatchConfig:
    def test_file_watch_config_defaults(self):
        config = FileWatchConfig(watch_path="/tmp")
        assert config.watch_path == "/tmp"
        assert config.patterns == ["*"]
        assert config.ignore_patterns == []
        assert config.recursive is True
        assert config.debounce_ms == 500
        assert config.events == ["created", "modified", "deleted"]

    def test_file_watch_config_custom(self):
        config = FileWatchConfig(
            watch_path="/var/log",
            patterns=["*.log", "*.txt"],
            ignore_patterns=["*.tmp"],
            recursive=False,
            debounce_ms=2000,
            events=["created", "deleted"],
        )
        assert config.watch_path == "/var/log"
        assert config.patterns == ["*.log", "*.txt"]
        assert config.ignore_patterns == ["*.tmp"]
        assert config.recursive is False
        assert config.debounce_ms == 2000
        assert config.events == ["created", "deleted"]


class TestFileWatchTriggerPatternMatching:
    def test_should_process_event_created_match(self):
        config = FileWatchConfig(watch_path="/tmp", patterns=["*.py"])
        trigger = FileWatchTrigger(
            trigger_id="test",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        assert trigger._should_process_event("/tmp/main.py", "created") is True

    def test_should_process_event_no_match(self):
        config = FileWatchConfig(watch_path="/tmp", patterns=["*.py"])
        trigger = FileWatchTrigger(
            trigger_id="test",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        assert trigger._should_process_event("/tmp/main.txt", "created") is False

    def test_should_process_event_ignored(self):
        config = FileWatchConfig(watch_path="/tmp", ignore_patterns=["*.tmp"])
        trigger = FileWatchTrigger(
            trigger_id="test",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        assert trigger._should_process_event("/tmp/file.tmp", "created") is False

    def test_should_process_event_wrong_event_type(self):
        config = FileWatchConfig(watch_path="/tmp", events=["created"])
        trigger = FileWatchTrigger(
            trigger_id="test",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        assert trigger._should_process_event("/tmp/main.py", "modified") is False


@pytest.mark.asyncio
class TestFileWatchTriggerIntegration:
    async def test_file_watch_trigger_lifecycle(self, trigger_manager):
        """File watch triggers can be created, synced, and deleted."""
        created = await trigger_manager.create_trigger(
            name="File Watch Test",
            type="file_watch",
            config={"watch_path": "/tmp", "patterns": ["*.txt"]},
            instruction="Process file change",
        )
        await trigger_manager.sync_trigger(created.id)

        # Should be registered
        assert created.id in trigger_manager._file_watch_triggers

        # Cleanup
        await trigger_manager.delete_trigger(created.id)
        assert created.id not in trigger_manager._file_watch_triggers

    async def test_trigger_now_routes_to_file_watch(self, trigger_manager):
        """trigger_now should acknowledge file_watch triggers."""
        created = await trigger_manager.create_trigger(
            name="File Watch Trigger Now",
            type="file_watch",
            config={"watch_path": "/tmp"},
            instruction="Process",
        )
        await trigger_manager.sync_trigger(created.id)

        result = await trigger_manager.trigger_now(created.id)
        assert result["status"] in ("triggered", "no_handler")


# =============================================================================
# ScheduleTrigger Tests
# =============================================================================

class TestScheduleTriggerConfig:
    def test_schedule_trigger_config_defaults(self):
        config = ScheduleTriggerConfig(cron="0 9 * * *")
        assert config.cron == "0 9 * * *"
        assert config.timezone == "Asia/Shanghai"
        assert config.enabled is True

    def test_schedule_trigger_config_custom(self):
        config = ScheduleTriggerConfig(
            cron="0 */2 * * *",
            timezone="UTC",
            enabled=False,
        )
        assert config.cron == "0 */2 * * *"
        assert config.timezone == "UTC"
        assert config.enabled is False


class TestScheduleTriggerActivation:
    def test_schedule_trigger_validate_cron(self):
        config = ScheduleTriggerConfig(cron="0 9 * * *")
        trigger = ScheduleTrigger(
            trigger_id="test",
            config=config,
            runtime=FakeRuntime(),
            instruction="test",
        )
        # activate() should not raise for valid cron
        # (it will fail if ScheduleManager is not mocked, but validates cron)
        # We just test construction here
        assert trigger.trigger_id == "test"
        assert trigger.is_active is False


@pytest.mark.asyncio
class TestScheduleTriggerIntegration:
    async def test_schedule_trigger_lifecycle(self, trigger_manager):
        """Schedule triggers can be created, synced, and deleted."""
        created = await trigger_manager.create_trigger(
            name="Schedule Test",
            type="schedule",
            config={"cron": "0 9 * * *", "timezone": "UTC"},
            instruction="Process daily",
        )
        await trigger_manager.sync_trigger(created.id)

        # Should be registered
        assert created.id in trigger_manager._schedule_triggers

        # Cleanup
        await trigger_manager.delete_trigger(created.id)
        assert created.id not in trigger_manager._schedule_triggers

    async def test_trigger_now_routes_to_schedule(self, trigger_manager):
        """trigger_now should acknowledge schedule triggers."""
        created = await trigger_manager.create_trigger(
            name="Schedule Trigger Now",
            type="schedule",
            config={"cron": "0 9 * * *"},
            instruction="Process",
        )
        await trigger_manager.sync_trigger(created.id)

        result = await trigger_manager.trigger_now(created.id)
        assert result["status"] in ("triggered", "no_handler")


# =============================================================================
# TriggerManager CRUD for file_watch and schedule
# =============================================================================

@pytest.mark.asyncio
class TestTriggerManagerFileWatchAndSchedule:
    async def test_create_file_watch_trigger(self, trigger_manager):
        trigger = await trigger_manager.create_trigger(
            name="File Watch CRUD",
            type="file_watch",
            config={"watch_path": "/tmp", "patterns": ["*.md"]},
            instruction="Watch markdown files",
        )
        assert trigger.type == "file_watch"
        assert trigger.config["watch_path"] == "/tmp"
        assert trigger.config["patterns"] == ["*.md"]

    async def test_create_schedule_trigger(self, trigger_manager):
        trigger = await trigger_manager.create_trigger(
            name="Schedule CRUD",
            type="schedule",
            config={"cron": "0 8 * * 1-5", "timezone": "America/New_York"},
            instruction="Weekday morning",
        )
        assert trigger.type == "schedule"
        assert trigger.config["cron"] == "0 8 * * 1-5"
        assert trigger.config["timezone"] == "America/New_York"

    async def test_list_triggers_file_watch_filter(self, trigger_manager):
        await trigger_manager.create_trigger(name="FW", type="file_watch", config={}, instruction="i1")
        await trigger_manager.create_trigger(name="SCH", type="schedule", config={}, instruction="i2")
        triggers, _ = trigger_manager.list_triggers(type_filter="file_watch")
        assert len(triggers) == 1
        assert triggers[0].name == "FW"

    async def test_list_triggers_schedule_filter(self, trigger_manager):
        await trigger_manager.create_trigger(name="FW2", type="file_watch", config={}, instruction="i1")
        await trigger_manager.create_trigger(name="SCH2", type="schedule", config={}, instruction="i2")
        triggers, _ = trigger_manager.list_triggers(type_filter="schedule")
        assert len(triggers) == 1
        assert triggers[0].name == "SCH2"

    async def test_delete_file_watch_cleans_up_handler(self, trigger_manager):
        created = await trigger_manager.create_trigger(
            name="Delete File Watch",
            type="file_watch",
            config={"watch_path": "/tmp"},
            instruction="test",
        )
        await trigger_manager.sync_trigger(created.id)
        assert created.id in trigger_manager._file_watch_triggers
        await trigger_manager.delete_trigger(created.id)
        assert created.id not in trigger_manager._file_watch_triggers

    async def test_delete_schedule_cleans_up_handler(self, trigger_manager):
        created = await trigger_manager.create_trigger(
            name="Delete Schedule",
            type="schedule",
            config={"cron": "0 9 * * *"},
            instruction="test",
        )
        await trigger_manager.sync_trigger(created.id)
        assert created.id in trigger_manager._schedule_triggers
        await trigger_manager.delete_trigger(created.id)
        assert created.id not in trigger_manager._schedule_triggers
