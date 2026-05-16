"""
TriggerManager - Unified trigger orchestration layer.

Manages all trigger types (webhook, file_watch, schedule, mqtt) and
coordinates execution via the runtime.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import shortuuid
from sqlalchemy import update
from sqlmodel import select

from app.core.db import get_session
from app.core.pagination import fetch_datetime_cursor_page
from app.models.database import TriggerModel

if TYPE_CHECKING:
    from app.core.runtime import RabAiAgentRuntime

logger = logging.getLogger(__name__)


class TriggerManagerError(Exception):
    """Base error for trigger manager operations."""


class TriggerNotFoundError(TriggerManagerError):
    """Raised when a trigger does not exist."""


class TriggerValidationError(TriggerManagerError, ValueError):
    """Raised when trigger input is invalid."""


def _require_non_empty(field_name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TriggerValidationError(f"{field_name} must not be empty.")
    return normalized


class TriggerManager:
    """
    Manages all trigger instances and coordinates with the runtime.

    This is the single entry point for trigger lifecycle management.
    Individual trigger types (WebhookTrigger, etc.) are created and
    managed internally.
    """

    # Supported trigger types
    SUPPORTED_TYPES = frozenset(["webhook", "file_watch", "schedule", "mqtt"])

    def __init__(self, runtime: "RabAiAgentRuntime") -> None:
        self.runtime = runtime
        self._webhook_handlers: dict[str, asyncio.Task] = {}
        self._file_watch_triggers: dict[str, object] = {}
        self._schedule_triggers: dict[str, object] = {}
        self._lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------

    async def create_trigger(
        self,
        *,
        name: str,
        type: str,  # webhook | file_watch | schedule | mqtt
        config: dict,
        instruction: str,
        enabled: bool = True,
    ) -> TriggerModel:
        """Create a new trigger and persist it to the database."""
        normalized_name = _require_non_empty("name", name)
        normalized_type = _require_non_empty("type", type)
        normalized_instruction = _require_non_empty("instruction", instruction)

        if normalized_type not in self.SUPPORTED_TYPES:
            raise TriggerValidationError(
                f"Unsupported trigger type: {normalized_type}. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_TYPES))}"
            )

        trigger = TriggerModel(
            name=normalized_name,
            type=normalized_type,
            config=config or {},
            instruction=normalized_instruction,
            enabled=enabled,
        )

        with get_session() as session:
            session.add(trigger)
            session.commit()
            session.refresh(trigger)

        logger.info(f"Created trigger {trigger.id} ({normalized_type}): {normalized_name}")
        return trigger

    @staticmethod
    def get_trigger(trigger_id: str) -> TriggerModel:
        """Get a trigger by ID."""
        normalized_id = _require_non_empty("trigger_id", trigger_id)
        with get_session() as session:
            trigger = session.get(TriggerModel, normalized_id)
            if not trigger:
                raise TriggerNotFoundError("Trigger not found")
            return trigger

    @staticmethod
    def list_triggers(
        *,
        cursor: Optional[str] = None,
        limit: int = 50,
        type_filter: Optional[str] = None,
    ) -> tuple[list[TriggerModel], Optional[str]]:
        """List triggers with optional type filter and cursor pagination."""
        with get_session() as session:
            query = select(TriggerModel)
            if type_filter:
                query = query.where(TriggerModel.type == type_filter)

            triggers, next_cursor = fetch_datetime_cursor_page(
                session,
                query,
                model=TriggerModel,
                sort_field="created_at",
                cursor=cursor,
                limit=limit,
            )
            return list(triggers), next_cursor

    async def update_trigger(
        self,
        trigger_id: str,
        *,
        name: Optional[str] = None,
        config: Optional[dict] = None,
        instruction: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> TriggerModel:
        """Update a trigger's configuration."""
        normalized_id = _require_non_empty("trigger_id", trigger_id)

        changes = {}
        if name is not None:
            changes["name"] = _require_non_empty("name", name)
        if config is not None:
            changes["config"] = config
        if instruction is not None:
            changes["instruction"] = _require_non_empty("instruction", instruction)
        if enabled is not None:
            changes["enabled"] = enabled

        changes["updated_at"] = datetime.now(timezone.utc)

        with get_session() as session:
            trigger = session.get(TriggerModel, normalized_id)
            if not trigger:
                raise TriggerNotFoundError("Trigger not found")

            session.execute(
                update(TriggerModel)
                .where(TriggerModel.id == normalized_id)
                .values(**changes)
            )
            session.commit()
            session.refresh(trigger)

        logger.info(f"Updated trigger {trigger_id}")
        return trigger

    async def delete_trigger(self, trigger_id: str) -> None:
        """Delete a trigger and clean up its resources."""
        normalized_id = _require_non_empty("trigger_id", trigger_id)

        with get_session() as session:
            trigger = session.get(TriggerModel, normalized_id)
            if not trigger:
                raise TriggerNotFoundError("Trigger not found")

            # Clean up any running tasks for this trigger
            await self._cleanup_trigger_tasks(normalized_id)

            session.delete(trigger)
            session.commit()

        logger.info(f"Deleted trigger {trigger_id}")

    # -------------------------------------------------------------------------
    # Webhook Management
    # -------------------------------------------------------------------------

    async def register_webhook_handler(
        self,
        trigger_id: str,
        config: dict,
        instruction: str,
    ) -> None:
        """
        Register a webhook trigger handler with the FastAPI app.

        The handler will be registered as: POST /webhooks/{trigger_id}
        """
        from app.core.triggers.webhook_handler import WebhookTrigger, WebhookConfig

        webhook_config = WebhookConfig(
            secret=config.get("secret"),
            event_filters=config.get("event_filters", []),
            headers=config.get("headers", {}),
            debounce_ms=config.get("debounce_ms", 1000),
        )

        trigger_instance = WebhookTrigger(
            trigger_id=trigger_id,
            config=webhook_config,
            runtime=self.runtime,
            instruction=instruction,
        )

        # Store in the runtime's webhook registry
        if not hasattr(self.runtime, "_webhook_triggers"):
            self.runtime._webhook_triggers = {}

        self.runtime._webhook_triggers[trigger_id] = trigger_instance
        logger.info(f"Registered webhook handler for trigger {trigger_id}")

    async def unregister_webhook_handler(self, trigger_id: str) -> None:
        """Unregister a webhook trigger handler."""
        if hasattr(self.runtime, "_webhook_triggers"):
            self.runtime._webhook_triggers.pop(trigger_id, None)
        await self._cleanup_trigger_tasks(trigger_id)
        logger.info(f"Unregistered webhook handler for trigger {trigger_id}")

    # -------------------------------------------------------------------------
    # File Watch Management
    # -------------------------------------------------------------------------

    async def register_file_watch_handler(
        self,
        trigger_id: str,
        config: dict,
        instruction: str,
    ) -> None:
        """Register a file watch trigger handler."""
        from app.core.triggers.file_watcher import FileWatchTrigger, FileWatchConfig

        file_config = FileWatchConfig(
            watch_path=config.get("watch_path", "."),
            patterns=config.get("patterns", ["*"]),
            ignore_patterns=config.get("ignore_patterns", []),
            recursive=config.get("recursive", True),
            debounce_ms=config.get("debounce_ms", 500),
            events=config.get("events", ["created", "modified", "deleted"]),
        )

        trigger_instance = FileWatchTrigger(
            trigger_id=trigger_id,
            config=file_config,
            runtime=self.runtime,
            instruction=instruction,
        )

        # Start the file watcher
        trigger_instance.start()

        self._file_watch_triggers[trigger_id] = trigger_instance
        logger.info(f"Registered file watch handler for trigger {trigger_id}")

    async def unregister_file_watch_handler(self, trigger_id: str) -> None:
        """Unregister a file watch trigger handler."""
        trigger = self._file_watch_triggers.pop(trigger_id, None)
        if trigger:
            trigger.stop()
            logger.info(f"Unregistered file watch handler for trigger {trigger_id}")

    # -------------------------------------------------------------------------
    # Schedule Management
    # -------------------------------------------------------------------------

    async def register_schedule_handler(
        self,
        trigger_id: str,
        config: dict,
        instruction: str,
    ) -> None:
        """Register a schedule trigger handler."""
        from app.core.triggers.schedule_trigger import ScheduleTrigger, ScheduleTriggerConfig

        sched_config = ScheduleTriggerConfig(
            cron=config.get("cron", "0 9 * * *"),
            timezone=config.get("timezone", "Asia/Shanghai"),
            enabled=config.get("enabled", True),
        )

        trigger_instance = ScheduleTrigger(
            trigger_id=trigger_id,
            config=sched_config,
            runtime=self.runtime,
            instruction=instruction,
        )

        # Activate the schedule
        trigger_instance.activate()

        self._schedule_triggers[trigger_id] = trigger_instance
        logger.info(f"Registered schedule handler for trigger {trigger_id}")

    async def unregister_schedule_handler(self, trigger_id: str) -> None:
        """Unregister a schedule trigger handler."""
        trigger = self._schedule_triggers.pop(trigger_id, None)
        if trigger:
            trigger.deactivate()
            logger.info(f"Unregistered schedule handler for trigger {trigger_id}")

    # -------------------------------------------------------------------------
    # Trigger Execution
    # -------------------------------------------------------------------------

    async def trigger_now(
        self,
        trigger_id: str,
        *,
        event_type: str = "manual",
        body: Optional[dict] = None,
    ) -> dict[str, object]:
        """
        Manually trigger a trigger's instruction immediately.

        This bypasses the normal webhook reception and directly executes
        the trigger's instruction.
        """
        trigger = self.get_trigger(trigger_id)

        if not trigger.enabled:
            return {
                "status": "disabled",
                "trigger_id": trigger_id,
                "message": "Trigger is disabled",
            }

        import json
        body_bytes = json.dumps(body or {}).encode() if body else b"{}"

        # Route to appropriate handler
        if trigger.type == "webhook":
            webhook = self.runtime._webhook_triggers.get(trigger_id)
            if webhook:
                result = await webhook.handle_request(
                    headers={"x-event-type": event_type},
                    body=body_bytes,
                    raw_body=body_bytes,
                )
                return result
            return {
                "status": "no_handler",
                "trigger_id": trigger_id,
                "message": "Webhook handler not registered",
            }
        elif trigger.type == "file_watch":
            # File watch triggers can be triggered manually too
            file_watch = self._file_watch_triggers.get(trigger_id)
            if file_watch:
                return {
                    "status": "triggered",
                    "trigger_id": trigger_id,
                    "message": "File watch trigger acknowledged (manual trigger does not simulate file events)",
                }
            return {
                "status": "no_handler",
                "trigger_id": trigger_id,
                "message": "File watch handler not registered",
            }
        elif trigger.type == "schedule":
            sched = self._schedule_triggers.get(trigger_id)
            if sched:
                return {
                    "status": "triggered",
                    "trigger_id": trigger_id,
                    "message": "Schedule trigger acknowledged",
                }
            return {
                "status": "no_handler",
                "trigger_id": trigger_id,
                "message": "Schedule handler not registered",
            }
        else:
            return {
                "status": "unsupported_type",
                "trigger_id": trigger_id,
                "type": trigger.type,
                "message": f"trigger_now: unsupported type {trigger.type}",
            }

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    async def _cleanup_trigger_tasks(self, trigger_id: str) -> None:
        """Clean up any running tasks for a trigger."""
        task = self._webhook_handlers.pop(trigger_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def sync_trigger(self, trigger_id: str) -> None:
        """
        Sync a trigger's state from DB to runtime.

        Called on startup and after trigger updates.
        """
        trigger = self.get_trigger(trigger_id)

        # First unregister any existing handler
        if trigger.type == "webhook":
            await self.unregister_webhook_handler(trigger_id)
        elif trigger.type == "file_watch":
            await self.unregister_file_watch_handler(trigger_id)
        elif trigger.type == "schedule":
            await self.unregister_schedule_handler(trigger_id)

        # Then register if enabled
        if not trigger.enabled:
            return

        if trigger.type == "webhook":
            await self.register_webhook_handler(
                trigger_id=trigger.id,
                config=trigger.config or {},
                instruction=trigger.instruction,
            )
        elif trigger.type == "file_watch":
            await self.register_file_watch_handler(
                trigger_id=trigger.id,
                config=trigger.config or {},
                instruction=trigger.instruction,
            )
        elif trigger.type == "schedule":
            await self.register_schedule_handler(
                trigger_id=trigger.id,
                config=trigger.config or {},
                instruction=trigger.instruction,
            )

    async def sync_all(self) -> None:
        """Sync all enabled triggers on startup."""
        with get_session() as session:
            triggers = list(session.exec(select(TriggerModel)).all())

        for trigger in triggers:
            try:
                await self.sync_trigger(trigger.id)
            except Exception as exc:
                logger.exception(f"Failed to sync trigger {trigger.id}: {exc}")
