"""
Feishu (Lark) Platform Adapter.

Implements the BasePlatformAdapter for Feishu messaging platform.
Uses a subprocess to run the Feishu WebSocket SDK (which requires its own event loop).
"""

import asyncio
import logging
import os
import subprocess
import sys
import json
import threading
from typing import Optional, Callable, Awaitable

from .base import BasePlatformAdapter
from ..session import SessionContext, PlatformIdentity

logger = logging.getLogger(__name__)

# Feishu message types we support
FEISHU_MSG_TYPES = ["text", "image", "audio", "video", "file", "card", "interactive"]


class FeishuAdapter(BasePlatformAdapter):
    """
    Feishu platform adapter using a subprocess to run the Feishu WebSocket SDK.

    The SDK requires its own event loop, so we run it in a separate subprocess
    and communicate via JSON messages on stdin/stdout.
    """

    name = "feishu"
    supports_streaming = True

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_name: str = "RabAiAgent",
    ):
        super().__init__()
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_name = bot_name
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    async def connect(self) -> None:
        """Connect to Feishu using WebSocket mode (via subprocess)."""
        try:
            # Create a script that runs the Feishu WS client using the SDK
            ws_script = _create_ws_client_script()

            # Start subprocess with the script
            self._process = subprocess.Popen(
                [sys.executable, "-c", ws_script, self.app_id, self.app_secret],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ},
            )

            # Start reader thread
            self._stop_event.clear()
            self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._reader_thread.start()

            # Wait a moment for connection to establish
            await asyncio.sleep(3)

            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                raise RuntimeError(f"Feishu WS subprocess exited: {stderr}")

            self._connected = True
            logger.info(f"{self.name}: Connected to Feishu WebSocket (subprocess)")

        except Exception as e:
            logger.error(f"{self.name}: Failed to connect: {e}")
            raise

    def _read_stdout(self) -> None:
        """Read stdout from subprocess in a thread."""
        try:
            for line in iter(self._process.stdout.readline, b""):
                if self._stop_event.is_set():
                    break
                if line:
                    try:
                        msg = json.loads(line.decode().strip())
                        self._handle_subprocess_message(msg)
                    except json.JSONDecodeError:
                        logger.warning(f"{self.name}: Invalid JSON from subprocess: {line}")
        except Exception as e:
            if not self._stop_event.is_set():
                logger.error(f"{self.name}: Error reading subprocess stdout: {e}")

    def _handle_subprocess_message(self, msg: dict) -> None:
        """Handle message received from subprocess."""
        msg_type = msg.get("type")
        if msg_type == "message":
            event = msg.get("event", {})
            asyncio.create_task(self._on_message_receive(event))
        elif msg_type == "connected":
            logger.info(f"{self.name}: Feishu WebSocket connected")
        elif msg_type == "disconnected":
            logger.info(f"{self.name}: Feishu WebSocket disconnected")
        elif msg_type == "error":
            logger.error(f"{self.name}: Subprocess error: {msg.get('message')}")
        elif msg_type == "log":
            level = msg.get("level", "info")
            log_msg = msg.get("message", "")
            if level == "error":
                logger.error(f"{self.name} [WS]: {log_msg}")
            elif level == "warning":
                logger.warning(f"{self.name} [WS]: {log_msg}")
            else:
                logger.debug(f"{self.name} [WS]: {log_msg}")

    async def disconnect(self) -> None:
        """Disconnect from Feishu WebSocket."""
        self._stop_event.set()

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception as e:
                logger.error(f"{self.name}: Error disconnecting: {e}")

        if self._reader_thread:
            self._reader_thread.join(timeout=5)

        self._connected = False
        logger.info(f"{self.name}: Disconnected from Feishu")

    async def send_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        if not self._connected or not self._process:
            logger.error(f"{self.name}: Not connected")
            return None

        try:
            cmd = {
                "type": "send",
                "chat_id": chat_id,
                "content": content,
                "msg_type": msg_type,
                **kwargs,
            }
            self._process.stdin.write(json.dumps(cmd).encode() + b"\n")
            self._process.stdin.flush()
            return None
        except Exception as e:
            logger.error(f"{self.name}: Error sending message: {e}")
            return None

    async def send_card(
        self,
        chat_id: str,
        card: dict,
        **kwargs,
    ) -> Optional[str]:
        return await self.send_message(chat_id, json.dumps(card), msg_type="interactive", **kwargs)

    async def format_for_platform(self, content: str, **kwargs) -> str:
        msg_type = kwargs.get("msg_type", "text")
        max_length = 4000 if msg_type == "text" else 10000
        if len(content) > max_length:
            content = content[: max_length - 3] + "..."
        return content

    async def _on_message_receive(self, event) -> None:
        """Handle incoming Feishu message event."""
        try:
            message = event.get("message") or {}
            sender = event.get("sender") or {}

            msg_type = message.get("message_type", "text")
            if msg_type not in FEISHU_MSG_TYPES:
                logger.debug(f"{self.name}: Ignoring message type: {msg_type}")
                return

            sender_id = sender.get("sender_id") or {}
            open_id = sender_id.get("open_id")

            chat_id = message.get("chat_id")
            message_id = message.get("message_id")
            content_str = message.get("content", "")

            content = content_str
            if msg_type == "text":
                try:
                    content_obj = json.loads(content_str)
                    content = content_obj.get("text", content_str)
                except (json.JSONDecodeError, TypeError):
                    pass

            identity = PlatformIdentity(
                platform="feishu",
                user_id=open_id or "unknown",
                chat_id=chat_id or "unknown",
            )

            session_ctx = SessionContext(
                platform="feishu",
                identity=identity,
                message_id=message_id,
                content=content,
                raw_event=event,
            )

            await self._handle_incoming(session_ctx)

        except Exception as e:
            logger.error(f"{self.name}: Error handling message: {e}")

    def set_message_handler(self, handler: Callable[[SessionContext], Awaitable[None]]) -> None:
        self._message_handler = handler


def _create_ws_client_script() -> str:
    """Create the Python script that runs in the subprocess using the SDK."""
    return '''
import asyncio
import json
import sys

# Add the backend to path for imports
sys.path.insert(0, "{backend_path}")

from lark_oapi.ws import Client as WsClient
from lark_oapi import EventDispatcherHandler

def main():
    app_id = sys.argv[1] if len(sys.argv) > 1 else None
    app_secret = sys.argv[2] if len(sys.argv) > 2 else None

    if not app_id or not app_secret:
        print(json.dumps({{"type": "error", "message": "Missing app_id or app_secret"}}), flush=True)
        sys.exit(1)

    try:
        # Create event dispatcher handler
        handler_builder = EventDispatcherHandler.builder(
            encrypt_key="",
            verification_token="",
        )

        # Import the event class
        from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1

        # Message buffer for communication with parent
        message_buffer = []

        def handle_message(event):
            # Extract event data
            event_dict = {{
                "message": {{
                    "message_id": getattr(event.message, "message_id", None) if hasattr(event, "message") and event.message else None,
                    "chat_id": getattr(event.message, "chat_id", None) if hasattr(event, "message") and event.message else None,
                    "message_type": getattr(event.message, "message_type", None) if hasattr(event, "message") and event.message else None,
                    "content": getattr(event.message, "content", None) if hasattr(event, "message") and event.message else None,
                }},
                "sender": {{
                    "sender_id": {{
                        "open_id": getattr(event.sender, "open_id", None) if hasattr(event, "sender") and event.sender else None,
                    }},
                }},
            }}
            # Send to parent via stdout
            print(json.dumps({{"type": "message", "event": event_dict}}), flush=True)

        handler_builder.register_p2_im_message_receive_v1(handle_message)
        dispatcher = handler_builder.build()

        client = WsClient(app_id, app_secret, event_handler=dispatcher)

        print(json.dumps({{"type": "connected"}}), flush=True)

        # Run the WebSocket client (this blocks)
        client.start()

    except Exception as e:
        print(json.dumps({{"type": "error", "message": str(e)}}), flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
'''.format(backend_path=str(sys.path[0] if sys.path[0] else "."))
