"""
Feishu RPC handlers for webhook events.
"""

import logging
from fastapi import APIRouter, Request, HTTPException

from app.gateway import get_router, PlatformIdentity
from app.gateway.session import SessionContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feishu", tags=["feishu"])


@router.post("/webhook")
async def handle_webhook(request: Request) -> dict:
    """
    Handle incoming Feishu webhook events.

    This endpoint receives events from Feishu's webhook system.
    For production, you may want to verify the signature.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = body.get("event", {}).get("type")
    logger.debug(f"Feishu webhook: {event_type}")

    # Route to appropriate handler
    if event_type == "im.message.receive_v1":
        return await _handle_message_receive(body)
    else:
        logger.debug(f"Unhandled event type: {event_type}")
        return {"code": 0, "msg": "ok"}


async def _handle_message_receive(body: dict) -> dict:
    """Handle incoming message event."""
    router = get_router()

    event = body.get("event", {})
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
            import json
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
    response = await router.route_incoming(
        platform="feishu",
        event={"content": content, "message_id": message_id, "raw": body},
        identity=identity,
    )

    # Send response back to Feishu
    if response:
        await router.route_response(response)

    return {"code": 0, "msg": "ok"}


@router.get("/bot_info")
async def get_bot_info() -> dict:
    """Get information about the configured Feishu bot."""
    from app.gateway import get_registry

    registry = get_registry()
    feishu = registry.get("feishu")

    if feishu:
        return {
            "connected": feishu.is_connected,
            "bot_name": getattr(feishu, "bot_name", "RabAiAgent"),
        }
    return {
        "connected": False,
        "message": "Feishu not configured",
    }


@router.post("/send")
async def send_message(
    chat_id: str,
    content: str,
    msg_type: str = "text",
) -> dict:
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
        chat_id=chat_id,
        content=content,
        msg_type=msg_type,
    )

    if message_id:
        return {"code": 0, "msg": "ok", "message_id": message_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to send message")
