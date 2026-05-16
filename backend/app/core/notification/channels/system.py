"""System notification channel (macOS Notification Center / Windows Toast)."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

from app.core.notification.channels.base import NotificationChannel
from app.core.notification.events import NotificationEvent, NotificationSeverity

logger = logging.getLogger(__name__)


class SystemNotifier(NotificationChannel):
    """Send notifications via OS-native notification center."""

    name = "system"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        return await self._send_native(event)

    async def _send_native(self, event: NotificationEvent) -> bool:
        """Send OS-native notification."""
        title = f"[{event.severity.value.upper()}] {event.title}"
        body = event.body.replace("\n", " ")

        if sys.platform == "darwin":
            return await self._send_macos(title, body)
        elif sys.platform == "win32":
            return await self._send_windows(title, body)
        else:
            logger.warning(f"[SystemNotifier] Unsupported platform: {sys.platform}")
            return False

    async def _send_macos(self, title: str, body: str) -> bool:
        """Send via macOS Notification Center (terminal-notifier or osascript)."""
        try:
            # Try osascript first (built-in, no extra install)
            script = f'display notification "{self._escape(body)}" with title "{self._escape(title)}"'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                self._log_result(None, True)  # type: ignore[arg-type]
                return True
            self._log_result(None, False, result.stderr.strip() or "osascript failed")  # type: ignore[arg-type]
            return False
        except FileNotFoundError:
            # osascript not found
            self._log_result(None, False, "osascript not found")
            return False
        except subprocess.TimeoutExpired:
            self._log_result(None, False, "timeout")
            return False
        except Exception as e:
            self._log_result(None, False, str(e))  # type: ignore[arg-type]
            return False

    async def _send_windows(self, title: str, body: str) -> bool:
        """Send via Windows Toast notification (PowerShell)."""
        try:
            ps_script = (
                f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, '
                f'ContentType = WindowsRuntime] | Out-Null; '
                f'$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('
                f'[Windows.UI.Notifications.ToastTemplateType]::ToastText02); '
                f'$textNodes = $template.GetElementsByTagName("text"); '
                f'$textNodes.Item(0).AppendChild($template.CreateTextNode("{self._escape_ps(title)}")) | Out-Null; '
                f'$textNodes.Item(1).AppendChild($template.CreateTextNode("{self._escape_ps(body)}")) | Out-Null; '
                f'$toast = [Windows.UI.Notifications.ToastNotification]::new($template); '
                f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("RabAi Agent").Show($toast)'
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self._log_result(None, True)  # type: ignore[arg-type]
                return True
            self._log_result(None, False, result.stderr.strip()[:100])  # type: ignore[arg-type]
            return False
        except Exception as e:
            self._log_result(None, False, str(e))  # type: ignore[arg-type]
            return False

    @staticmethod
    def _escape(s: str) -> str:
        """Escape double quotes for osascript."""
        return s.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _escape_ps(s: str) -> str:
        """Escape double quotes for PowerShell."""
        return s.replace('"', "'").replace("$", "`$")
