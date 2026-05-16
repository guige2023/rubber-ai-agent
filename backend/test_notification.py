"""Test Feishu notification channel."""

import asyncio
import sys
sys.path.insert(0, "/Users/guige/my_project/RabAi Agent/backend")

from app.core.notification.events import NotificationEvent, NotificationSeverity
from app.core.notification.channels.feishu import FeishuNotifier


async def test_feishu_notification():
    """Test sending a Feishu notification."""
    notifier = FeishuNotifier()
    
    event = NotificationEvent(
        severity=NotificationSeverity.WARNING,
        source="test",
        title="通知通道测试",
        body="这是一条测试通知，用于验证 Feishu 主动推送功能是否正常工作。\n时间：{time}",
    )
    event = NotificationEvent(
        severity=NotificationSeverity.WARNING,
        source="test",
        title="通知通道测试",
        body="这是一条测试通知，用于验证 Feishu 主动推送功能是否正常工作。",
    )
    
    success = await notifier.send(event)
    print(f"Feishu notification {'✅ SUCCESS' if success else '❌ FAILED'}")
    return success


if __name__ == "__main__":
    result = asyncio.run(test_feishu_notification())
    sys.exit(0 if result else 1)
