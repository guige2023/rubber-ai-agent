"""Email notification channel via Resend."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

from app.core.notification.channels.base import NotificationChannel
from app.core.notification.events import NotificationEvent, NotificationSeverity

logger = logging.getLogger(__name__)


class EmailNotifier(NotificationChannel):
    """Send notifications via email using Resend API."""

    name = "email"

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        to_email: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        self.api_key = api_key
        self.from_email = from_email
        self.to_email = to_email
        self.enabled = enabled and bool(api_key)

    async def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False

        if not self.api_key:
            self._log_result(event, False, "no api_key configured")
            return False

        return await self._send_email(event)

    async def _send_email(self, event: NotificationEvent) -> bool:
        """Send email via Resend."""
        import resend

        resend.api_key = self.api_key

        html_body = self._build_html(event)

        try:
            params = {
                "from": self.from_email or "Aito <aito@yourdomain.com>",
                "to": [self.to_email] if self.to_email else [],
                "subject": f"[{event.severity.value.upper()}] {event.title}",
                "html": html_body,
            }

            result = await asyncio.to_thread(
                resend.Emails.send, params
            )

            if result and result.get("id"):
                self._log_result(event, True)
                return True
            else:
                self._log_result(event, False, f"Resend returned unexpected result: {result}")
                return False

        except Exception as e:
            self._log_result(event, False, str(e))
            return False

    def _build_html(self, event: NotificationEvent) -> str:
        """Build HTML email body."""
        color_map = {
            NotificationSeverity.CRITICAL: "#dc2626",
            NotificationSeverity.WARNING: "#d97706",
            NotificationSeverity.INFO: "#6b7280",
        }
        color = color_map.get(event.severity, "#6b7280")

        actions_html = ""
        if event.actions:
            actions_html = f"""
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #eee;" />
            <h3 style="margin: 0 0 10px; font-size: 14px; color: #374151;">可执行操作</h3>
            <ul style="color: #6b7280; font-size: 14px;">
                {"".join(f"<li>{a}</li>" for a in event.actions)}
            </ul>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f9fafb; margin: 0; padding: 20px; }}
                .container {{ background: white; border-radius: 8px; max-width: 600px; margin: 0 auto; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                .header {{ background: {color}; color: white; padding: 20px 24px; }}
                .header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
                .body {{ padding: 24px; color: #374151; font-size: 15px; line-height: 1.6; }}
                .footer {{ padding: 16px 24px; border-top: 1px solid #eee; color: #9ca3af; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>【{event.severity.value.upper()}】{event.title}</h1>
                </div>
                <div class="body">
                    <p style="white-space: pre-wrap; margin: 0;">{event.body}</p>
                    {actions_html}
                </div>
                <div class="footer">
                    来源：{event.source} | {event.timestamp}
                </div>
            </div>
        </body>
        </html>
        """
