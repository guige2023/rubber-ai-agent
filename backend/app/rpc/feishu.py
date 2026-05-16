"""
Feishu RPC handlers for webhook events.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.gateway import get_router, PlatformIdentity
from app.gateway.session import SessionContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feishu", tags=["feishu"])


# Pydantic request/response models for validation (P0-API-2)
class FeishuWebhookEvent(BaseModel):
    """Validated schema for Feishu webhook event payload."""
    event: Optional[dict] = Field(default=None, description="Event payload from Feishu")

    model_config = {"extra": "allow"}  # Allow unknown fields from Feishu


class FeishuSendMessageRequest(BaseModel):
    """Validated request for sending a Feishu message."""
    chat_id: str = Field(..., min_length=1, description="Feishu chat ID")
    content: str = Field(..., min_length=1, description="Message content")
    msg_type: str = Field(
        default="text",
        pattern="^(text|image|post|audio|media|file|sticker)$",
        description="Message type",
    )


class FeishuSendMessageResponse(BaseModel):
    """Response for send message API."""
    code: int = Field(..., description="Feishu API error code (0 = success)")
    msg: str = Field(..., description="Response message")
    message_id: Optional[str] = Field(default=None, description="Sent message ID")


class FeishuBotInfoResponse(BaseModel):
    """Response for bot info API."""
    connected: bool
    bot_name: Optional[str] = None
    message: Optional[str] = None


@router.post("/webhook")
async def handle_webhook(request: Request) -> dict:
    """
    Handle incoming Feishu webhook events.

    This endpoint receives events from Feishu's webhook system.
    For production, you may want to verify the signature.
    """
    try:
        body_dict = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Validate with Pydantic model (P0-API-2)
    validated = FeishuWebhookEvent.model_validate(body_dict)
    event_type = validated.event.get("type") if validated.event else None
    logger.debug(f"Feishu webhook: {event_type}")

    # Route to appropriate handler
    if event_type == "im.message.receive_v1":
        return await _handle_message_receive(validated.event or {})
    else:
        logger.debug(f"Unhandled event type: {event_type}")
        return {"code": 0, "msg": "ok"}


async def _handle_message_receive(event: dict) -> dict:
    """Handle incoming message event."""
    gateway_router = get_router()

    message = event.get("message", {})
    sender = event.get("sender", {})

    # Extract identity
    sender_id = sender.get("sender_id", {})
    open_id = sender_id.get("open_id", "unknown")
    chat_id = message.get("chat_id", "unknown")
    message_id = message.get("message_id")
    msg_type = message.get("message_type", "text")

    # Extract content
    content_str = message.get("content", "")
    content = content_str

    if msg_type == "text":
        try:
            content_obj = json.loads(content_str)
            content = content_obj.get("text", content_str)
        except (json.JSONDecodeError, Exception):
            pass

    # Create identity
    identity = PlatformIdentity(
        platform="feishu",
        user_id=open_id,
        chat_id=chat_id,
    )

    # Route through gateway
    response = await gateway_router.route_incoming(
        platform="feishu",
        event={"content": content, "message_id": message_id, "raw": event},
        identity=identity,
    )

    # Send response back to Feishu
    if response:
        await gateway_router.route_response(response)

    return {"code": 0, "msg": "ok"}


@router.get("/bot_info", response_model=FeishuBotInfoResponse)
async def get_bot_info() -> FeishuBotInfoResponse:
    """Get information about the configured Feishu bot."""
    from app.gateway import get_registry

    registry = get_registry()
    feishu = registry.get("feishu")

    if feishu:
        return FeishuBotInfoResponse(
            connected=feishu.is_connected,
            bot_name=getattr(feishu, "bot_name", "RabAiAgent"),
        )
    return FeishuBotInfoResponse(
        connected=False,
        message="Feishu not configured",
    )


@router.post("/send", response_model=FeishuSendMessageResponse)
async def send_message(body: FeishuSendMessageRequest) -> FeishuSendMessageResponse:
    """
    Send a message through Feishu.

    This is a simple API for sending messages without
    going through the full agent pipeline.
    """
    from app.gateway import get_registry

    registry = get_registry()
    feishu = registry.get("feishu")

    if not feishu:
        raise HTTPException(status_code=400, detail="Feishu not configured")

    if not feishu.is_connected:
        raise HTTPException(status_code=503, detail="Feishu not connected")

    message_id = await feishu.send_message(
        chat_id=body.chat_id,
        content=body.content,
        msg_type=body.msg_type,
    )

    if message_id:
        return FeishuSendMessageResponse(code=0, msg="ok", message_id=message_id)
    else:
        raise HTTPException(status_code=500, detail="Failed to send message")
