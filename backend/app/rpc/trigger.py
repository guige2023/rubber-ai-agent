"""
Trigger RPC methods - CRUD for triggers and webhook handling.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from app.core.trigger_manager import (
    TriggerManager,
    TriggerNotFoundError,
    TriggerValidationError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/triggers", tags=["triggers"])

# ---------------------------------------------------------------------------
# Request/Response Schemas
# ---------------------------------------------------------------------------


class TriggerCreateSchema(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field(..., pattern="^(webhook|file_watch|schedule|mqtt)$")
    config: dict[str, Any] = Field(default_factory=dict)
    instruction: str = Field(..., min_length=1)
    enabled: bool = True


class TriggerUpdateSchema(BaseModel):
    name: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    instruction: Optional[str] = None
    enabled: Optional[bool] = None


class TriggerResponse(BaseModel):
    id: str
    name: str
    type: str
    config: dict[str, Any]
    instruction: str
    enabled: bool
    last_triggered_at: Optional[str] = None
    trigger_count: int
    last_run_result: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


class TriggerListResponse(BaseModel):
    triggers: list[TriggerResponse]
    next_cursor: Optional[str] = None


class TriggerNowRequest(BaseModel):
    trigger_id: str = Field(..., min_length=1)
    event_type: str = "manual"
    body: Optional[dict[str, Any]] = None


class TriggerNowResponse(BaseModel):
    status: str
    trigger_id: str
    message: str
    event_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_trigger_manager(request: Request) -> TriggerManager:
    """Dependency to get TriggerManager from app state."""
    runtime = request.app.state.runtime
    if not hasattr(runtime, "trigger_manager"):
        raise HTTPException(503, "TriggerManager not initialized")
    return runtime.trigger_manager


def _trigger_to_response(t) -> TriggerResponse:
    """Convert a TriggerModel to TriggerResponse."""
    return TriggerResponse(
        id=t.id,
        name=t.name,
        type=t.type,
        config=t.config or {},
        instruction=t.instruction,
        enabled=t.enabled,
        last_triggered_at=t.last_triggered_at.isoformat() if t.last_triggered_at else None,
        trigger_count=t.trigger_count or 0,
        last_run_result=t.last_run_result,
        created_at=t.created_at.isoformat() if t.created_at else "",
        updated_at=t.updated_at.isoformat() if t.updated_at else "",
    )


# ---------------------------------------------------------------------------
# Trigger CRUD Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TriggerResponse, status_code=201)
async def create_trigger(
    body: TriggerCreateSchema,
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
):
    """
    Create a new trigger.

    Supported types:
    - webhook: HTTP webhook receiver
    - file_watch: File system watcher
    - schedule: Time-based schedule
    - mqtt: MQTT message listener
    """
    try:
        trigger = await tm.create_trigger(
            name=body.name,
            type=body.type,
            config=body.config,
            instruction=body.instruction,
            enabled=body.enabled,
        )
        # Sync to runtime
        await tm.sync_trigger(trigger.id)
        return _trigger_to_response(trigger)
    except TriggerValidationError as e:
        raise HTTPException(400, str(e))


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: str,
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
):
    """Get a trigger by ID."""
    try:
        trigger = tm.get_trigger(trigger_id)
        return _trigger_to_response(trigger)
    except TriggerNotFoundError:
        raise HTTPException(404, "Trigger not found")


@router.get("", response_model=TriggerListResponse)
async def list_triggers(
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
    cursor: Optional[str] = None,
    limit: int = 50,
    type: Optional[str] = None,
):
    """List all triggers with optional cursor pagination and type filter."""
    if limit > 100:
        limit = 100

    triggers, next_cursor = tm.list_triggers(
        cursor=cursor,
        limit=limit,
        type_filter=type,
    )
    return TriggerListResponse(
        triggers=[_trigger_to_response(t) for t in triggers],
        next_cursor=next_cursor,
    )


@router.patch("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: str,
    body: TriggerUpdateSchema,
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
):
    """Update a trigger's configuration."""
    try:
        changes = body.model_dump(exclude_none=True)
        trigger = await tm.update_trigger(trigger_id, **changes)
        await tm.sync_trigger(trigger_id)
        return _trigger_to_response(trigger)
    except TriggerNotFoundError:
        raise HTTPException(404, "Trigger not found")
    except TriggerValidationError as e:
        raise HTTPException(400, str(e))


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: str,
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
):
    """Delete a trigger."""
    try:
        await tm.delete_trigger(trigger_id)
    except TriggerNotFoundError:
        raise HTTPException(404, "Trigger not found")


@router.post("/trigger-now", response_model=TriggerNowResponse)
async def trigger_now(
    body: TriggerNowRequest,
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
):
    """
    Manually trigger a trigger's instruction immediately.

    This bypasses the normal webhook reception and directly executes
    the trigger's instruction via the runtime.
    """
    try:
        result = await tm.trigger_now(
            trigger_id=body.trigger_id,
            event_type=body.event_type,
            body=body.body,
        )
        return TriggerNowResponse(
            status=result.get("status", "unknown"),
            trigger_id=result.get("trigger_id", body.trigger_id),
            message=result.get("message", ""),
            event_type=result.get("event_type"),
        )
    except TriggerNotFoundError:
        raise HTTPException(404, "Trigger not found")


# ---------------------------------------------------------------------------
# Webhook Receiver Endpoint
# ---------------------------------------------------------------------------

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/{trigger_id}")
async def receive_webhook(
    trigger_id: str,
    request: Request,
    tm: Annotated[TriggerManager, Depends(get_trigger_manager)],
):
    """
    Receive an incoming webhook and dispatch to the appropriate trigger.

    This is the generic webhook receiver that routes requests to
    registered WebhookTrigger handlers.
    """
    # Get raw body for signature verification
    raw_body = await request.body()

    # Get headers (lowercase)
    headers = {k.lower(): v for k, v in request.headers.items()}

    # Try to parse JSON body
    try:
        body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        body = raw_body

    # Look up the trigger
    try:
        trigger = tm.get_trigger(trigger_id)
    except TriggerNotFoundError:
        raise HTTPException(404, "Trigger not found")

    if not trigger.enabled:
        return {"status": "disabled", "trigger_id": trigger_id, "message": "Trigger is disabled"}

    if trigger.type != "webhook":
        raise HTTPException(400, f"Trigger {trigger_id} is not a webhook type")

    # Get the webhook handler
    webhook = getattr(tm.runtime, "_webhook_triggers", {}).get(trigger_id)
    if not webhook:
        raise HTTPException(503, "Webhook handler not registered for this trigger")

    # Handle the request
    result = await webhook.handle_request(
        headers=headers,
        body=body if isinstance(body, bytes) else json.dumps(body).encode(),
        raw_body=raw_body,
    )

    return result
