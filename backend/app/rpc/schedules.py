from __future__ import annotations

import logging
from typing import Optional

from jsonrpcserver import Success, method

from app.core.schedule_manager import ScheduleNotFoundError, ScheduleValidationError
from app.models.schemas import ScheduleSchema

logger = logging.getLogger(__name__)


@method
async def list_schedules(context, cursor: Optional[str] = None, limit: int = 50):
    """List automated routines with cursor-based pagination."""
    logger.debug(f"Listing automated schedules (cursor: {cursor}, limit: {limit})")

    schedules, next_cursor = context.schedule_manager.list_schedules(cursor=cursor, limit=limit)

    logger.debug(f"Found {len(schedules)} schedules")
    return Success({
        "schedules": [ScheduleSchema.model_validate(schedule).model_dump(mode="json") for schedule in schedules],
        "next_cursor": next_cursor,
    })


@method
async def get_schedule(context, schedule_id: str):
    """Return a single schedule with editable details."""
    logger.debug(f"Fetching schedule detail: {schedule_id}")
    try:
        schedule = context.schedule_manager.get_schedule(schedule_id)
    except ScheduleNotFoundError:
        return Success({"status": "error", "message": "Schedule not found"})
    except ScheduleValidationError as exc:
        return Success({"status": "error", "message": str(exc)})
    return Success({"schedule": ScheduleSchema.model_validate(schedule).model_dump(mode="json")})


@method
async def update_schedule(
    context,
    schedule_id: str,
    name: Optional[str] = None,
    cron_expression: Optional[str] = None,
    timezone: Optional[str] = None,
    enabled: Optional[bool] = None,
    instruction: Optional[str] = None,
):
    """Update editable schedule fields."""
    logger.info(f"Updating schedule: {schedule_id}")

    try:
        await context.schedule_manager.update_schedule(
            schedule_id,
            name=name,
            cron_expression=cron_expression,
            timezone_name=timezone,
            enabled=enabled,
            instruction=instruction,
        )
    except ScheduleNotFoundError:
        return Success({"status": "error", "message": "Schedule not found"})
    except ScheduleValidationError as exc:
        return Success({"status": "error", "message": str(exc)})
    return Success({"status": "success"})


@method
async def delete_schedule(context, schedule_id: str):
    """Delete a schedule."""
    logger.info(f"Deleting schedule: {schedule_id}")
    try:
        await context.schedule_manager.delete_schedule(schedule_id)
    except ScheduleNotFoundError:
        return Success({"status": "error", "message": "Schedule not found"})
    except ScheduleValidationError as exc:
        return Success({"status": "error", "message": str(exc)})
    return Success({"status": "success"})
