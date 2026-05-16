"""Tests for the notification system."""

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/Users/guige/my_project/RabAi Agent/backend")

from app.core.notification.events import NotificationEvent, NotificationSeverity
from app.core.notification.manager import (
    NotificationConfig,
    NotificationManager,
    NotificationPriority,
    _DedupeKey,
)
from app.core.notification.channels.base import NotificationChannel


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def config() -> NotificationConfig:
    return NotificationConfig(
        enabled=True,
        feishu_enabled=False,  # Disable actual Feishu in tests
        email_enabled=False,
        system_enabled=False,
        max_retries=2,
        retry_base_delay=0.1,
    )


@pytest.fixture
def manager(config: NotificationConfig) -> NotificationManager:
    return NotificationManager(config)


@pytest.fixture
def critical_event() -> NotificationEvent:
    return NotificationEvent(
        severity=NotificationSeverity.CRITICAL,
        source="test",
        title="Critical Alert",
        body="Something bad happened.",
    )


@pytest.fixture
def warning_event() -> NotificationEvent:
    return NotificationEvent(
        severity=NotificationSeverity.WARNING,
        source="test",
        title="Warning",
        body="Something might be wrong.",
    )


@pytest.fixture
def info_event() -> NotificationEvent:
    return NotificationEvent(
        severity=NotificationSeverity.INFO,
        source="test",
        title="Info",
        body="Just so you know.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# NotificationEvent Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNotificationEvent:
    def test_severity_order(self):
        """CRITICAL < HIGH < NORMAL < LOW in priority (lower IntEnum value = higher priority)."""
        assert NotificationPriority.CRITICAL < NotificationPriority.HIGH
        assert NotificationPriority.HIGH < NotificationPriority.NORMAL
        assert NotificationPriority.NORMAL < NotificationPriority.LOW

    def test_to_text(self, critical_event: NotificationEvent):
        text = critical_event.to_text()
        assert "【CRITICAL】Critical Alert" in text
        assert "Something bad happened." in text

    def test_to_text_with_actions(self, warning_event: NotificationEvent):
        ev = NotificationEvent(
            severity=NotificationSeverity.WARNING,
            source="test",
            title="With Actions",
            body="Body",
            actions=("Fix it", "Ignore"),
        )
        text = ev.to_text()
        assert "Fix it" in text
        assert "Ignore" in text

    def test_to_feishu_card(self, info_event: NotificationEvent):
        card = info_event.to_feishu_card()
        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["template"] == "grey"
        assert "info" in card["card"]["header"]["title"]["content"].lower()

    def test_feishu_card_actions_hidden_when_empty(self, info_event: NotificationEvent):
        card = info_event.to_feishu_card()
        elements = card["card"]["elements"]
        # No action elements
        action_elements = [e for e in elements if "可执行操作" in e.get("content", "")]
        assert len(action_elements) == 0

    def test_feishu_card_actions_shown_when_present(self):
        ev = NotificationEvent(
            severity=NotificationSeverity.WARNING,
            source="test",
            title="Action Card",
            body="Body",
            actions=("Button1", "Button2"),
        )
        card = ev.to_feishu_card()
        elements = card["card"]["elements"]
        action_elements = [e for e in elements if "可执行操作" in str(e)]
        assert len(action_elements) > 0


# ─────────────────────────────────────────────────────────────────────────────
# NotificationConfig Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNotificationConfig:
    def test_default_values(self):
        cfg = NotificationConfig()
        assert cfg.enabled is True
        assert cfg.max_retries == 3
        assert cfg.retry_base_delay == 2.0
        assert cfg.system_enabled is True

    def test_quiet_hours_properties(self):
        cfg = NotificationConfig(quiet_hours=(22, 7))
        assert cfg.quiet_start == 22
        assert cfg.quiet_end == 7


# ─────────────────────────────────────────────────────────────────────────────
# NotificationManager Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNotificationManagerInit:
    def test_no_channels_when_all_disabled(self):
        cfg = NotificationConfig(
            feishu_enabled=False,
            email_enabled=False,
            system_enabled=False,
        )
        mgr = NotificationManager(cfg)
        assert len(mgr._channels) == 0

    def test_feishu_channel_enabled(self):
        cfg = NotificationConfig(feishu_enabled=True)
        mgr = NotificationManager(cfg)
        channel_names = [ch.name for ch in mgr._channels]
        assert "feishu" in channel_names

    def test_system_channel_enabled(self):
        cfg = NotificationConfig(system_enabled=True)
        mgr = NotificationManager(cfg)
        channel_names = [ch.name for ch in mgr._channels]
        assert "system" in channel_names


class TestNotificationManagerDedup:
    def test_no_dedup_for_different_events(self, manager: NotificationManager, warning_event, info_event):
        key1 = _DedupeKey(source=warning_event.source, title=warning_event.title)
        key2 = _DedupeKey(source=info_event.source, title=info_event.title)
        # Events have different titles so dedupe keys differ
        assert key1 != key2

    def test_dedup_key_hash(self):
        key1 = _DedupeKey(source="test", title="Same")
        key2 = _DedupeKey(source="test", title="Same")
        assert hash(key1) == hash(key2)

    def test_dedup_ttl(self, manager: NotificationManager, warning_event):
        # Should not be deduped on first call
        assert manager._is_dupe(warning_event) is False
        # Immediate second call should be deduped
        assert manager._is_dupe(warning_event) is True


class TestNotificationManagerDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_respects_disabled(self):
        cfg = NotificationConfig(enabled=False)
        mgr = NotificationManager(cfg)
        ev = NotificationEvent(
            severity=NotificationSeverity.CRITICAL,
            source="test",
            title="Should not deliver",
            body="msg",
        )
        # Should return early, no channels
        await mgr.dispatch(ev)
        assert len(mgr._queue) == 0

    @pytest.mark.asyncio
    async def test_dispatch_enqueues_event(self, manager: NotificationManager, warning_event):
        await manager.dispatch(warning_event)
        assert len(manager._queue) == 1
        priority, ev = manager._queue[0]
        assert ev == warning_event

    @pytest.mark.asyncio
    async def test_dispatch_dedupes(self, manager: NotificationManager, warning_event):
        await manager.dispatch(warning_event)
        await manager.dispatch(warning_event)  # duplicate
        # Only one in queue (first one was already enqueued before dedupe check)
        # Actually: first dispatch enqueues, second is deduped before dispatch
        # So we should only have 1
        assert len(manager._queue) == 1

    @pytest.mark.asyncio
    async def test_critical_bypasses_quiet_hours(self, manager: NotificationManager, critical_event):
        # Patch _in_quiet_hours to return True
        with patch("app.core.notification.manager._in_quiet_hours", return_value=True):
            await manager.dispatch(critical_event)
            # CRITICAL should still be queued
            assert len(manager._queue) == 1


class TestNotificationManagerStatus:
    def test_get_status(self, manager: NotificationManager):
        status = manager.get_status()
        assert "enabled" in status
        assert "channels" in status
        assert "max_retries" in status
        assert status["max_retries"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Priority Queue Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPriorityQueue:
    @pytest.mark.asyncio
    async def test_critical_queued_before_info(self, manager: NotificationManager):
        info_ev = NotificationEvent(
            severity=NotificationSeverity.INFO,
            source="test",
            title="Info",
            body="msg",
        )
        critical_ev = NotificationEvent(
            severity=NotificationSeverity.CRITICAL,
            source="test",
            title="Critical",
            body="msg",
        )
        # Enqueue info first, then critical
        await manager.dispatch(info_ev)
        await manager.dispatch(critical_ev)

        # Critical should be first in sorted queue
        assert manager._queue[0][1].severity == NotificationSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_priority_high_for_warning(self, manager: NotificationManager, warning_event):
        await manager.dispatch(warning_event)
        priority, ev = manager._queue[0]
        # WARNING → HIGH priority
        assert priority == NotificationPriority.HIGH


# ─────────────────────────────────────────────────────────────────────────────
# Retry Mechanism Tests
# ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

class TestRetryMechanism:
    @pytest.mark.asyncio
    async def test_send_with_retry_success_first_attempt(self, manager: NotificationManager, warning_event):
        mock_channel = MagicMock()
        mock_channel.name = "test_channel"
        mock_channel.send_warning = AsyncMock(return_value=True)

        result = await manager._send_with_retry(
            mock_channel, warning_event, NotificationSeverity.WARNING
        )
        assert result is True
        mock_channel.send_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_retry_eventual_success(self, manager: NotificationManager, warning_event):
        mock_channel = MagicMock()
        mock_channel.name = "test_channel"
        # Fail twice, succeed on third
        mock_channel.send_warning = AsyncMock(
            side_effect=[False, False, True]
        )

        result = await manager._send_with_retry(
            mock_channel, warning_event, NotificationSeverity.WARNING
        )
        assert result is True
        assert mock_channel.send_warning.call_count == 3

    @pytest.mark.asyncio
    async def test_send_with_retry_all_fail(self, manager: NotificationManager, warning_event):
        mock_channel = MagicMock()
        mock_channel.name = "test_channel"
        mock_channel.send_warning = AsyncMock(return_value=False)

        result = await manager._send_with_retry(
            mock_channel, warning_event, NotificationSeverity.WARNING
        )
        assert result is False
        # max_retries=2 → 3 total attempts
        assert mock_channel.send_warning.call_count == 3

    @pytest.mark.asyncio
    async def test_send_with_retry_exception_then_success(self, manager: NotificationManager, warning_event):
        mock_channel = MagicMock()
        mock_channel.name = "test_channel"
        mock_channel.send_warning = AsyncMock(
            side_effect=[Exception("network error"), True]
        )

        result = await manager._send_with_retry(
            mock_channel, warning_event, NotificationSeverity.WARNING
        )
        assert result is True
        assert mock_channel.send_warning.call_count == 2

    @pytest.mark.asyncio
    async def test_failed_notifications_recorded(self, manager: NotificationManager, warning_event):
        mock_channel = MagicMock()
        mock_channel.name = "fail_channel"
        mock_channel.send_warning = AsyncMock(return_value=False)

        await manager._send_with_retry(
            mock_channel, warning_event, NotificationSeverity.WARNING
        )

        failed = manager.get_failed_notifications()
        assert len(failed) == 1
        assert failed[0]["channel"] == "fail_channel"
        assert failed[0]["title"] == warning_event.title


# ─────────────────────────────────────────────────────────────────────────────
# SystemNotifier Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemNotifier:
    @pytest.mark.asyncio
    async def test_send_disabled(self):
        from app.core.notification.channels.system import SystemNotifier

        notifier = SystemNotifier(enabled=False)
        ev = NotificationEvent(
            severity=NotificationSeverity.INFO,
            source="test",
            title="Test",
            body="msg",
        )
        result = await notifier.send(ev)
        assert result is False

    @pytest.mark.asyncio
    @patch("subprocess.run")
    def test_send_macos_success(self, mock_run):
        import sys
        original_platform = sys.platform
        sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        from app.core.notification.channels.system import SystemNotifier

        notifier = SystemNotifier(enabled=True)
        ev = NotificationEvent(
            severity=NotificationSeverity.INFO,
            source="test",
            title="Test",
            body="Hello",
        )

        result = asyncio.run(notifier.send(ev))
        assert result is True
        mock_run.assert_called_once()
        sys.platform = original_platform

    @pytest.mark.asyncio
    @patch("subprocess.run")
    def test_send_macos_failure(self, mock_run):
        import sys
        original_platform = sys.platform
        sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=1, stderr="error")

        from app.core.notification.channels.system import SystemNotifier

        notifier = SystemNotifier(enabled=True)
        ev = NotificationEvent(
            severity=NotificationSeverity.INFO,
            source="test",
            title="Test",
            body="Hello",
        )

        result = asyncio.run(notifier.send(ev))
        assert result is False
        sys.platform = original_platform


# ─────────────────────────────────────────────────────────────────────────────
# Batch Dispatch Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_batch(self, manager: NotificationManager, warning_event, info_event):
        events = [warning_event, info_event]
        await manager.dispatch_batch(events)
        assert len(manager._queue) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
