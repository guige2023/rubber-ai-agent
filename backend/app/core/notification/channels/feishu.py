"""Feishu proactive notification channel via IM API."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Optional

from app.core.notification.channels.base import NotificationChannel
from app.core.notification.events import NotificationEvent, NotificationSeverity

logger = logging.getLogger(__name__)

# Feishu app credentials
FEISHU_APP_ID = "cli_a9f69d8a1e789bb4"
FEISHU_APP_SECRET = "2CMYfVOxlVBIY3fBdG0qpHg8A853b5nu"
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
FEISHU_RECIPIENT_OPEN_ID = "ou_bd6d23d82e92c82ecf712192c22eedab"

# Token cache
_token_cache: Optional[tuple[str, float]] = None
_TOKEN_TTL_SECONDS = 7000  # Feishu tokens last 2h, refresh after ~70min


def _get_tenant_token() -> Optional[str]:
    """Get a cached tenant access token, refreshing if stale."""
    global _token_cache
    now = time.time()

    if _token_cache is not None:
        token, expires_at = _token_cache
        if now < expires_at - 60:  # Refresh 60s early
            return token

    # Fetch new token
    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read())
            if data.get("code") == 0:
                token = data["tenant_access_token"]
                _token_cache = (token, now + _TOKEN_TTL_SECONDS)
                logger.debug("Feishu tenant token refreshed")
                return token
            else:
                logger.warning(f"Feishu token fetch failed: {data.get('msg')}")
    except Exception as e:
        logger.warning(f"Feishu token fetch error: {e}")

    return None


class FeishuNotifier(NotificationChannel):
    """Send proactive notifications via Feishu IM API."""

    name = "feishu"

    def __init__(
        self,
        recipient_open_id: str = FEISHU_RECIPIENT_OPEN_ID,
        enabled: bool = True,
    ) -> None:
        self.recipient_open_id = recipient_open_id
        self.enabled = enabled

    async def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False

        return await self._send_message(event)

    async def send_critical(self, event: NotificationEvent) -> bool:
        return await self.send(event)

    async def send_warning(self, event: NotificationEvent) -> bool:
        return await self.send(event)

    async def send_info(self, event: NotificationEvent) -> bool:
        return await self.send(event)

    def _build_payload(self, event: NotificationEvent) -> dict:
        """Build Feishu message payload."""
        # Use card for rich formatting
        card = event.to_feishu_card()
        return {
            "receive_id": self.recipient_open_id,
            "msg_type": "interactive",
            "content": json.dumps(card["card"], ensure_ascii=False),
        }

    async def _send_message(self, event: NotificationEvent) -> bool:
        """Send a message via Feishu IM API."""
        token = _get_tenant_token()
        if not token:
            self._log_result(event, False, "no token")
            return False

        payload = self._build_payload(event)
        url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                result = json.loads(resp.read())
                if result.get("code") == 0:
                    self._log_result(event, True)
                    return True
                else:
                    # Token may be expired — clear cache and retry once
                    if result.get("code") in (99991663, 99991664):
                        global _token_cache
                        _token_cache = None
                        return await self._send_message(event)
                    self._log_result(event, False, result.get("msg"))
                    return False
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            self._log_result(event, False, f"HTTP {e.code}: {body}")
            return False
        except Exception as e:
            self._log_result(event, False, str(e))
            return False
