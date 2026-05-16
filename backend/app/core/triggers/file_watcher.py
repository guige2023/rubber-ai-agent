"""
FileWatchTrigger - File system watcher trigger using watchdog.

Triggers agent instruction when files matching a pattern are created/modified/deleted.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.runtime import RabAiAgentRuntime

logger = logging.getLogger(__name__)


@dataclass
class FileWatchConfig:
    """Configuration for a file watch trigger."""
    watch_path: str  # Directory or file path to watch
    patterns: list[str] = field(default_factory=lambda: ["*"])  # Glob patterns to match
    ignore_patterns: list[str] = field(default_factory=lambda: [])  # Patterns to ignore
    recursive: bool = True  # Watch subdirectories
    debounce_ms: int = 500  # Debounce window in ms
    events: list[str] = field(default_factory=lambda: ["created", "modified", "deleted"])  # Event types to watch


class FileWatchTrigger:
    """
    Watches a file system path and triggers an instruction on matching events.

    Features:
    - Glob pattern matching for file filtering
    - Ignore pattern support
    - Recursive directory watching
    - Debouncing to prevent trigger storms
    - Multiple event type support (created, modified, deleted)
    """

    def __init__(
        self,
        trigger_id: str,
        config: FileWatchConfig,
        runtime: "RabAiAgentRuntime",
        instruction: str,
    ) -> None:
        self.trigger_id = trigger_id
        self.config = config
        self.runtime = runtime
        self.instruction = instruction
        self._observer: Optional[object] = None
        self._last_triggered_at: float = 0
        self._lock = asyncio.Lock()
        self._event_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._processing = False

    def _compile_patterns(self, patterns: list[str]) -> list[re.Pattern]:
        """Convert glob patterns to compiled regex patterns."""
        compiled = []
        for pattern in patterns:
            # Convert glob to regex: * → .*, ? → ., . → \.
            regex = pattern.replace(".", r"\.").replace("**", ".*").replace("*", "[^/]*").replace("?", ".")
            compiled.append(re.compile(f"^{regex}$"))
        return compiled

    def _matches_patterns(self, path: str, patterns: list[re.Pattern]) -> bool:
        """Check if a path matches any of the compiled patterns."""
        if not patterns:
            return True
        name = Path(path).name
        return any(p.match(name) for p in patterns)

    def _should_process_event(self, path: str, event_type: str) -> bool:
        """Check if an event should be processed based on config."""
        # Check event type filter
        if event_type not in self.config.events:
            return False

        # Check ignore patterns first
        if self.config.ignore_patterns:
            ignore_compiled = self._compile_patterns(self.config.ignore_patterns)
            if self._matches_patterns(path, ignore_compiled):
                return False

        # Check include patterns
        if self.config.patterns:
            include_compiled = self._compile_patterns(self.config.patterns)
            return self._matches_patterns(path, include_compiled)

        return True

    def _create_handlers(self):
        """Create watchdog event handlers."""
        from watchdog.events import (
            FileSystemEventHandler,
            FileCreatedEvent,
            FileModifiedEvent,
            FileDeletedEvent,
            DirectoryCreatedEvent,
            DirectoryModifiedEvent,
            DirectoryDeletedEvent,
        )

        config = self.config
        self_handlers = self  # Capture self reference

        class TriggerEventHandler(FileSystemEventHandler):
            def __init__(self):
                super().__init__()

            def on_created(self, event):
                event_type = "created"
                if hasattr(event, 'is_directory') and event.is_directory:
                    event_type = "directory_created"
                self_handlers._queue_event(event.src_path, event_type)

            def on_modified(self, event):
                if hasattr(event, 'is_directory') and event.is_directory:
                    return  # Skip directory modifications
                self_handlers._queue_event(event.src_path, "modified")

            def on_deleted(self, event):
                event_type = "deleted"
                if hasattr(event, 'is_directory') and event.is_directory:
                    event_type = "directory_deleted"
                self_handlers._queue_event(event.src_path, event_type)

        return TriggerEventHandler()

    def _queue_event(self, path: str, event_type: str) -> None:
        """Queue an event for processing."""
        if not self._should_process_event(path, event_type):
            return

        # Debounce check
        import time
        now = time.monotonic() * 1000
        if now - self._last_triggered_at < self.config.debounce_ms:
            return
        self._last_triggered_at = now

        self._event_queue.put_nowait({"path": path, "event_type": event_type})
        if not self._processing:
            asyncio.create_task(self._process_events())

    async def _process_events(self) -> None:
        """Process queued events."""
        self._processing = True
        try:
            while not self._event_queue.empty():
                event = await self._event_queue.get()
                await self._execute_instruction(event["path"], event["event_type"])
        finally:
            self._processing = False

    async def _execute_instruction(self, file_path: str, event_type: str) -> None:
        """Execute the trigger's instruction via the runtime."""
        from datetime import datetime, timezone

        run_id = f"fw-{self.trigger_id[:8]}"
        instruction_with_context = (
            f"{self.instruction}\n\n"
            f"[File Watch Event Context]\n"
            f"Trigger ID: {self.trigger_id}\n"
            f"Event Type: {event_type}\n"
            f"File Path: {file_path}\n"
            f"Watch Path: {self.config.watch_path}\n"
        )

        logger.info(f"FileWatch {self.trigger_id}: triggering on {event_type}: {file_path}")

        try:
            asyncio.create_task(
                self._run_triggered_instruction(
                    instruction=instruction_with_context,
                    run_id=run_id,
                    file_path=file_path,
                    event_type=event_type,
                )
            )
        except Exception as e:
            logger.error(f"FileWatch {self.trigger_id}: failed to schedule instruction: {e}")

    async def _run_triggered_instruction(
        self,
        instruction: str,
        run_id: str,
        file_path: str,
        event_type: str,
    ) -> None:
        """Run the triggered instruction via run_registry."""
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc)
        finished_at = started_at
        result_status = "success"
        result_summary = None
        result_error = None

        try:
            runner_task = self.runtime.run_registry.start_run(
                session_id=self.trigger_id,
                instruction=instruction,
                run_id=run_id,
                source="file_watch",
            )
            result = await runner_task
            finished_at = datetime.now(timezone.utc)

            if isinstance(result, dict):
                payload = result.get("payload", {})
                messages = payload.get("messages", []) if isinstance(payload, dict) else []
                last_message = messages[-1] if messages else {}
                content = str(last_message.get("content", ""))[:500]
                result_summary = content or None
        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            result_status = "failed"
            result_error = str(e)[:500]
            logger.exception(f"FileWatch trigger {self.trigger_id} run failed")

        await self._update_trigger_stats(
            trigger_id=self.trigger_id,
            last_triggered_at=started_at,
            last_run_result={
                "status": result_status,
                "summary": result_summary,
                "error": result_error,
                "run_id": run_id,
                "event_type": event_type,
                "file_path": file_path,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
            },
        )

    @staticmethod
    async def _update_trigger_stats(
        trigger_id: str,
        last_triggered_at: datetime,
        last_run_result: dict,
    ) -> None:
        """Update trigger statistics in the database."""
        from app.core.db import get_session
        from app.models.database import TriggerModel

        try:
            with get_session() as session:
                trigger = session.get(TriggerModel, trigger_id)
                if trigger:
                    trigger.last_triggered_at = last_triggered_at
                    trigger.trigger_count = (trigger.trigger_count or 0) + 1
                    trigger.last_run_result = last_run_result
                    session.add(trigger)
                    session.commit()
        except Exception as e:
            logger.error(f"Failed to update trigger stats for {trigger_id}: {e}")

    def start(self) -> None:
        """Start the file watcher."""
        try:
            from watchdog.observers import Observer
        except ImportError:
            logger.error("watchdog not installed. Install with: pip install watchdog")
            return

        watch_path = Path(self.config.watch_path)
        if not watch_path.exists():
            logger.error(f"Watch path does not exist: {self.config.watch_path}")
            return

        self._observer = Observer()
        handler = self._create_handlers()
        self._observer.schedule(
            handler,
            str(watch_path),
            recursive=self.config.recursive,
        )
        self._observer.start()
        logger.info(f"FileWatch {self.trigger_id}: started watching {self.config.watch_path} (recursive={self.config.recursive})")

    def stop(self) -> None:
        """Stop the file watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info(f"FileWatch {self.trigger_id}: stopped")

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
