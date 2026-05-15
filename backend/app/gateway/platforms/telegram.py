"""
Telegram Platform Adapter.

Implements the BasePlatformAdapter for Telegram messaging platform.
Supports:
- Text, image, video, audio, document messages
- Inline keyboards and reply keyboards
- Callback queries
- Commands
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable
import json

from .base import BasePlatformAdapter
from ..session import SessionContext, PlatformIdentity

logger = logging.getLogger(__name__)

# Telegram message types we support
TELEGRAM_MSG_TYPES = ["text", "photo", "video", "audio", "document", "sticker", "location", "contact"]

# Telegram update types we handle
TELEGRAM_UPDATE_TYPES = [
    "message",
    "edited_message",
    "callback_query",
    "inline_query",
    "channel_post",
    "edited_channel_post",
]


class TelegramAdapter(BasePlatformAdapter):
    """
    Telegram platform adapter using the Telegram Bot API.

    Supports:
    - Receiving messages via long polling
    - Sending text, media, and document messages
    - Interactive keyboards (inline and reply)
    - Callback queries
    """

    name = "telegram"
    supports_streaming = True

    def __init__(
        self,
        bot_token: str,
        api_url: str = "https://api.telegram.org",
    ):
        """
        Initialize Telegram adapter.

        Args:
            bot_token: Telegram bot token from @BotFather
            api_url: Base URL for Telegram API (default: https://api.telegram.org)
        """
        super().__init__()
        self.bot_token = bot_token
        self.api_url = api_url.rstrip("/")
        self._client = None
        self._poll_task: Optional[asyncio.Task] = None
        self._offset: int = 0
        self._message_handler: Optional[Callable[[SessionContext], Awaitable[None]]] = None

    async def connect(self) -> None:
        """Connect to Telegram using long polling."""
        await super().connect()
        try:
            # Verify bot token by getting bot info
            me = await self._call_api("getMe")
            if not me or me.get("ok"):
                logger.info(f"{self.name}: Connected as @{me.get('result', {}).get('username', 'unknown')}")
            else:
                logger.error(f"{self.name}: Bot token verification failed")
                raise ValueError("Invalid bot token")

            # Start long polling
            self._poll_task = asyncio.create_task(self._long_poll())

        except Exception as e:
            logger.error(f"{self.name}: Failed to connect: {e}")
            self._connected = False
            self._running = False
            raise

    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        await super().disconnect()
        logger.info(f"{self.name}: Disconnected from Telegram")

    async def _call_api(self, method: str, **params) -> Optional[dict]:
        """
        Make a call to the Telegram Bot API.

        Args:
            method: API method name
            **params: Method parameters

        Returns:
            API response dict or None on error
        """
        import aiohttp

        url = f"{self.api_url}/bot{self.bot_token}/{method}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        logger.error(f"{self.name}: API call {method} failed with status {response.status}")
                        return None
                    data = await response.json()
                    if not data.get("ok"):
                        logger.error(f"{self.name}: API call {method} failed: {data.get('description')}")
                        return None
                    return data
        except asyncio.TimeoutError:
            logger.error(f"{self.name}: API call {method} timed out")
            return None
        except Exception as e:
            logger.error(f"{self.name}: API call {method} error: {e}")
            return None

    async def _long_poll(self) -> None:
        """Long poll for updates from Telegram."""
        logger.info(f"{self.name}: Starting long polling")

        while self._connected and self._running:
            try:
                updates = await self._get_updates()
                if updates:
                    for update in updates:
                        await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{self.name}: Poll error: {e}")
                await asyncio.sleep(5)  # Back off on error

    async def _get_updates(self) -> list:
        """
        Get updates using long polling.

        Returns:
            List of updates
        """
        import aiohttp

        url = f"{self.api_url}/bot{self.bot_token}/getUpdates"
        params = {
            "offset": self._offset,
            "timeout": 30,
            "allowed_updates": TELEGRAM_UPDATE_TYPES,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status != 200:
                        return []
                    data = await response.json()
                    if not data.get("ok"):
                        return []
                    return data.get("result", [])
        except Exception:
            return []

    async def _process_update(self, update: dict) -> None:
        """
        Process an incoming Telegram update.

        Args:
            update: Telegram update dict
        """
        try:
            update_id = update.get("update_id", 0)
            self._offset = update_id + 1

            # Process message
            if "message" in update:
                await self._handle_message(update["message"])
            elif "edited_message" in update:
                await self._handle_message(update["edited_message"])
            elif "callback_query" in update:
                await self._handle_callback_query(update["callback_query"])
            elif "inline_query" in update:
                # Inline queries are not handled in basic messaging mode
                pass
            elif "channel_post" in update:
                await self._handle_message(update["channel_post"])
            elif "edited_channel_post" in update:
                await self._handle_message(update["edited_channel_post"])

        except Exception as e:
            logger.error(f"{self.name}: Error processing update: {e}")

    async def _handle_message(self, message: dict) -> None:
        """
        Handle an incoming message.

        Args:
            message: Telegram message dict
        """
        try:
            message_id = str(message.get("message_id", ""))
            chat = message.get("chat", {})
            chat_id = str(chat.get("id", ""))
            user = message.get("from", {})
            user_id = str(user.get("id", "unknown"))
            content = message.get("text", "") or message.get("caption", "")

            # Get message type
            msg_type = "text"
            if message.get("photo"):
                msg_type = "photo"
            elif message.get("video"):
                msg_type = "video"
            elif message.get("audio"):
                msg_type = "audio"
            elif message.get("document"):
                msg_type = "document"
            elif message.get("sticker"):
                msg_type = "sticker"
            elif message.get("location"):
                msg_type = "location"
            elif message.get("contact"):
                msg_type = "contact"

            # Skip content-less messages
            if not content and msg_type == "text":
                return

            # Create platform identity
            identity = PlatformIdentity(
                platform="telegram",
                user_id=user_id,
                chat_id=chat_id,
            )

            # Create session context
            session_ctx = SessionContext(
                platform="telegram",
                identity=identity,
                message_id=message_id,
                content=content,
                raw_event=message,
            )

            # Route to handler
            await self._handle_incoming(session_ctx)

        except Exception as e:
            logger.error(f"{self.name}: Error handling message: {e}")

    async def _handle_callback_query(self, query: dict) -> None:
        """
        Handle a callback query (inline keyboard button press).

        Args:
            query: Telegram callback query dict
        """
        try:
            query_id = query.get("id", "")
            data = query.get("data", "")
            message = query.get("message", {})

            if not data:
                return

            chat = message.get("chat", {})
            chat_id = str(chat.get("id", ""))
            user = query.get("from", {})
            user_id = str(user.get("id", "unknown"))

            # Answer the callback query
            await self._call_api("answerCallbackQuery", callback_query_id=query_id)

            # Create platform identity
            identity = PlatformIdentity(
                platform="telegram",
                user_id=user_id,
                chat_id=chat_id,
            )

            # Create session context with callback data as content
            session_ctx = SessionContext(
                platform="telegram",
                identity=identity,
                message_id=str(message.get("message_id", "")),
                content=data,
                raw_event=query,
            )

            # Route to handler
            await self._handle_incoming(session_ctx)

        except Exception as e:
            logger.error(f"{self.name}: Error handling callback query: {e}")

    async def send_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """
        Send a message to a Telegram chat.

        Args:
            chat_id: Telegram chat ID
            content: Message content
            msg_type: Message type (text, photo, video, etc.)
            **kwargs: Additional options:
                - reply_to_message_id: ID of message to reply to
                - reply_markup: Keyboard markup (inline keyboard, reply keyboard, etc.)
                - parse_mode: Parse mode (Markdown or HTML)

        Returns:
            Message ID if successful
        """
        if not self._connected:
            logger.error(f"{self.name}: Not connected")
            return None

        try:
            params = {
                "chat_id": chat_id,
                "parse_mode": kwargs.get("parse_mode", "Markdown"),
            }

            # Handle different message types
            if msg_type == "text":
                params["text"] = await self.format_for_platform(content)
            elif msg_type == "photo":
                params["photo"] = content
                if kwargs.get("caption"):
                    params["caption"] = await self.format_for_platform(kwargs["caption"])
            elif msg_type == "video":
                params["video"] = content
                if kwargs.get("caption"):
                    params["caption"] = await self.format_for_platform(kwargs["caption"])
            elif msg_type == "document":
                params["document"] = content
                if kwargs.get("caption"):
                    params["caption"] = await self.format_for_platform(kwargs["caption"])
            elif msg_type == "audio":
                params["audio"] = content
                if kwargs.get("caption"):
                    params["caption"] = await self.format_for_platform(kwargs["caption"])
            else:
                params["text"] = await self.format_for_platform(content)

            # Optional reply
            if kwargs.get("reply_to_message_id"):
                params["reply_to_message_id"] = kwargs["reply_to_message_id"]

            # Optional keyboard
            if kwargs.get("reply_markup"):
                params["reply_markup"] = kwargs["reply_markup"]

            response = await self._call_api("sendMessage", **params)
            if response and response.get("ok"):
                msg_id = str(response.get("result", {}).get("message_id", ""))
                logger.debug(f"{self.name}: Sent message {msg_id} to {chat_id}")
                return msg_id

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
        """
        Send an inline keyboard card to a Telegram chat.

        Args:
            chat_id: Telegram chat ID
            card: Card definition dict with inline keyboard
            **kwargs: Additional options (reply_to_message_id, etc.)

        Returns:
            Message ID if successful
        """
        if not self._connected:
            logger.error(f"{self.name}: Not connected")
            return None

        try:
            # Build inline keyboard from card
            inline_keyboard = []
            if "buttons" in card:
                for row in card["buttons"]:
                    keyboard_row = []
                    for button in row:
                        keyboard_row.append({
                            "text": button.get("text", ""),
                            "callback_data": button.get("callback_data", button.get("url", "")),
                        })
                    inline_keyboard.append(keyboard_row)

            params = {
                "chat_id": chat_id,
                "text": card.get("text", card.get("title", "")),
                "parse_mode": "HTML",
                "reply_markup": json.dumps({"inline_keyboard": inline_keyboard}) if inline_keyboard else None,
            }

            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}

            response = await self._call_api("sendMessage", **params)
            if response and response.get("ok"):
                msg_id = str(response.get("result", {}).get("message_id", ""))
                logger.debug(f"{self.name}: Sent card {msg_id} to {chat_id}")
                return msg_id

            return None

        except Exception as e:
            logger.error(f"{self.name}: Error sending card: {e}")
            return None

    async def format_for_platform(self, content: str, **kwargs) -> str:
        """
        Format content for Telegram.

        Telegram has a 4096 character limit for text messages.
        Supports HTML and Markdown.
        """
        max_length = kwargs.get("max_length", 4096)

        if len(content) > max_length:
            content = content[: max_length - 3] + "..."

        return content

    def set_message_handler(self, handler: Callable[[SessionContext], Awaitable[None]]) -> None:
        """Set the handler for incoming messages."""
        self._message_handler = handler

    async def build_inline_keyboard(
        self,
        buttons: list[list[dict]],
    ) -> dict:
        """
        Build an inline keyboard markup.

        Args:
            buttons: 2D list of button definitions, each with:
                - text: Button label
                - callback_data: Data sent when button is pressed (for callback buttons)
                - url: URL to open (for URL buttons)

        Returns:
            Telegram-compatible reply_markup dict
        """
        inline_keyboard = []
        for row in buttons:
            keyboard_row = []
            for button in row:
                if "callback_data" in button:
                    keyboard_row.append({
                        "text": button["text"],
                        "callback_data": button["callback_data"],
                    })
                elif "url" in button:
                    keyboard_row.append({
                        "text": button["text"],
                        "url": button["url"],
                    })
            if keyboard_row:
                inline_keyboard.append(keyboard_row)

        return json.dumps({"inline_keyboard": inline_keyboard})

    async def build_reply_keyboard(
        self,
        buttons: list[list[str]],
        resize_keyboard: bool = True,
        one_time_keyboard: bool = False,
    ) -> dict:
        """
        Build a reply keyboard markup.

        Args:
            buttons: 2D list of button labels
            resize_keyboard: Resize keyboard to fit screen
            one_time_keyboard: Hide keyboard after use

        Returns:
            Telegram-compatible reply_markup dict
        """
        keyboard = []
        for row in buttons:
            keyboard.append([{"text": button} for button in row])

        return json.dumps({
            "keyboard": keyboard,
            "resize_keyboard": resize_keyboard,
            "one_time_keyboard": one_time_keyboard,
        })

    async def remove_reply_keyboard(self) -> dict:
        """Build a reply keyboard removal markup."""
        return json.dumps({"remove_keyboard": True})
