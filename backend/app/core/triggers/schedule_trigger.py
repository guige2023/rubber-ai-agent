"""
ScheduleTrigger - Time-based trigger using ScheduleManager.

Allows creating time-based triggers that execute on a cron schedule.
Uses the existing ScheduleManager infrastructure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.runtime import RabAiAgentRuntime

logger = logging.getLogger(__name__)


@dataclass
class ScheduleTriggerConfig:
    """Configuration for a schedule trigger."""
    cron: str  # Cron expression (e.g., "0 9 * * *" for 9 AM daily)
    timezone: str = "Asia/Shanghai"  # Timezone for the schedule
    enabled: bool = True  # Override the trigger's enabled state


class ScheduleTrigger:
    """
    A time-based trigger that executes on a cron schedule.

    Uses ScheduleManager's existing infrastructure. This is a thin wrapper
    that creates a schedule entry in ScheduleManager when the trigger is
    activated and removes it when deactivated.
    """

    def __init__(
        self,
        trigger_id: str,
        config: ScheduleTriggerConfig,
        runtime: "RabAiAgentRuntime",
        instruction: str,
    ) -> None:
        self.trigger_id = trigger_id
        self.config = config
        self.runtime = runtime
        self.instruction = instruction
        self._schedule_id: Optional[str] = None

    def activate(self) -> None:
        """
        Activate the schedule trigger by creating a schedule in ScheduleManager.

        This creates a recurring schedule that fires according to the cron
        expression and executes the trigger's instruction.
        """
        import croniter

        # Validate cron expression
        try:
            croniter.croniter(self.config.cron, datetime.now(timezone.utc))
        except Exception as e:
            logger.error(f"ScheduleTrigger {self.trigger_id}: invalid cron expression '{self.config.cron}': {e}")
            return

        # Build the schedule metadata
        metadata = {
            "trigger_id": self.trigger_id,
            "trigger_type": "schedule",
            "source": "trigger_manager",
        }

        try:
            # Use the runtime's schedule_manager to create the schedule
            schedule = self.runtime.schedule_manager.create_schedule(
                name=f"trigger:{self.trigger_id}",
                instruction=self.instruction,
                cron=self.config.cron,
                timezone=self.config.timezone,
                enabled=self.config.enabled,
                metadata=metadata,
            )
            self._schedule_id = schedule.id
            logger.info(
                f"ScheduleTrigger {self.trigger_id}: activated with schedule {schedule.id} "
                f"(cron={self.config.cron}, tz={self.config.timezone})"
            )
        except Exception as e:
            logger.exception(f"ScheduleTrigger {self.trigger_id}: failed to activate: {e}")

    def deactivate(self) -> None:
        """
        Deactivate the schedule trigger by removing the schedule from ScheduleManager.
        """
        if not self._schedule_id:
            logger.warning(f"ScheduleTrigger {self.trigger_id}: no active schedule to deactivate")
            return

        try:
            self.runtime.schedule_manager.delete_schedule(self._schedule_id)
            logger.info(f"ScheduleTrigger {self.trigger_id}: deactivated schedule {self._schedule_id}")
        except Exception as e:
            logger.exception(f"ScheduleTrigger {self.trigger_id}: failed to deactivate: {e}")
        finally:
            self._schedule_id = None

    @property
    def is_active(self) -> bool:
        return self._schedule_id is not None

    def get_next_fire_time(self) -> Optional[datetime]:
        """Get the next scheduled fire time."""
        if not self._schedule_id:
            return None
        try:
            schedule = self.runtime.schedule_manager.get_schedule(self._schedule_id)
            return schedule.next_run_at
        except Exception:
            return None
