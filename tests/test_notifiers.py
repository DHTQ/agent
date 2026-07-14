import io
import json
import unittest
from contextlib import redirect_stdout

from chat_priority_agent.config import NotificationConfig
from chat_priority_agent.models import Assessment, ChatMessage, Importance
from chat_priority_agent.notifiers import NotificationRouter


def assessment() -> Assessment:
    return Assessment(
        level=Importance.HIGH,
        score=82,
        confidence=0.9,
        summary="客户要求确认上线窗口",
        keywords=("上线窗口", "客户"),
        reasons=("客户接口人提出了明确时限",),
        suggested_action="今天内回复客户",
        notice="张三在等你确认今晚的上线窗口，建议今天内回复他。",
    )


class NotificationRouterTests(unittest.TestCase):
    def test_console_output_uses_natural_notice_only(self):
        router = NotificationRouter(
            NotificationConfig(console_min_level="high", desktop_enabled=False)
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            router.notify(ChatMessage(app="QQ", sender="张三", content="今晚窗口确认下？"), assessment())

        output = buffer.getvalue()
        self.assertIn("张三在等你确认今晚的上线窗口", output)
        self.assertNotIn("关键词", output)
        self.assertNotIn("原因", output)
        self.assertNotIn("上线窗口, 客户", output)

    def test_low_importance_message_is_quiet(self):
        router = NotificationRouter(NotificationConfig(desktop_enabled=False))
        quiet = Assessment(
            level=Importance.LOW,
            score=10,
            confidence=0.95,
            summary="普通告别",
            keywords=("告别",),
            reasons=("无需用户处理",),
            suggested_action="无需回复",
            notice="这条消息无需特别关注。",
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            router.notify(ChatMessage(app="QQ", sender="张三", content="再见"), quiet)

        self.assertEqual(buffer.getvalue(), "")

    def test_medium_actionable_message_is_notified_by_default(self):
        router = NotificationRouter(NotificationConfig(desktop_enabled=False))
        actionable = Assessment(
            level=Importance.MEDIUM,
            score=55,
            confidence=0.85,
            summary="对方要求发送表格",
            keywords=("表格",),
            reasons=("发送者提出了明确行动请求",),
            suggested_action="发送表格给对方",
            notice="张三要你把表格发给他，记得处理一下。",
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            router.notify(ChatMessage(app="QQ", sender="张三", content="把表格发给我"), actionable)

        self.assertIn("张三要你把表格发给他", buffer.getvalue())

    def test_json_output_hides_internal_analysis_fields(self):
        router = NotificationRouter(
            NotificationConfig(console_min_level="high", desktop_enabled=False),
            json_output=True,
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            router.notify(ChatMessage(app="QQ", sender="张三", content="今晚窗口确认下？"), assessment())

        payload = json.loads(buffer.getvalue())
        self.assertEqual(
            payload["notice"]["notice"],
            "张三在等你确认今晚的上线窗口，建议今天内回复他。",
        )
        self.assertNotIn("keywords", payload["notice"])
        self.assertNotIn("reasons", payload["notice"])


if __name__ == "__main__":
    unittest.main()
