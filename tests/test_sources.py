import json
import unittest

from chat_priority_agent.sources.stdin import StdinSource
from chat_priority_agent.sources.windows_toast import (
    WindowsToastSource,
    _is_not_implemented,
    _unpackaged_process_message,
)
from chat_priority_agent.sources.windows_uia import WindowsUIANotificationSource
from chat_priority_agent.config import SourceConfig


class StdinSourceTests(unittest.TestCase):
    def test_stdin_json_line(self):
        source = StdinSource(default_app="test")
        message = source.parse_line(
            json.dumps({"id": "m-1", "app": "QQ", "sender": "张三", "content": "请确认"})
        )

        self.assertEqual(message.id, "m-1")
        self.assertEqual(message.app, "QQ")
        self.assertEqual(message.sender, "张三")
        self.assertEqual(message.content, "请确认")

    def test_stdin_convenience_line(self):
        message = StdinSource().parse_line("张三：明天回复")

        self.assertEqual(message.sender, "张三")
        self.assertEqual(message.content, "明天回复")


class WindowsToastSourceTests(unittest.TestCase):
    def test_not_implemented_recognizes_errno_form(self):
        error = OSError(-2147467263, "尚未实现")

        self.assertTrue(_is_not_implemented(error))

    def test_current_listener_translates_not_implemented(self):
        class ListenerType:
            @property
            def current(self):
                raise OSError(-2147467263, "尚未实现")

        with self.assertRaisesRegex(RuntimeError, "UserNotificationListener 尚未实现"):
            WindowsToastSource._current_listener(ListenerType())

    def test_unpacked_process_message_explains_working_fallback(self):
        message = _unpackaged_process_message()

        self.assertIn("没有 Windows 应用包身份", message)
        self.assertIn("--source stdin", message)


class WindowsUIANotificationSourceTests(unittest.TestCase):
    def test_qq_toast_becomes_chat_message(self):
        source = WindowsUIANotificationSource(SourceConfig(apps=["QQ"]))

        parsed = source._message_from_lines(["QQ", "张三", "把表格发给我"])

        self.assertIsNotNone(parsed)
        signature, message = parsed
        self.assertEqual(signature, "QQ\x1f张三\x1f把表格发给我")
        self.assertEqual(message.app, "QQ")
        self.assertEqual(message.sender, "张三")
        self.assertEqual(message.content, "把表格发给我")
        self.assertTrue(message.source_id.startswith("windows-uia:"))

    def test_unwanted_app_toast_is_ignored(self):
        source = WindowsUIANotificationSource(SourceConfig(apps=["QQ"]))

        parsed = source._message_from_lines(["邮件", "系统", "新邮件"])

        self.assertIsNone(parsed)

    def test_agent_notification_is_ignored(self):
        source = WindowsUIANotificationSource(
            SourceConfig(apps=["消息"], exclude_apps=["消息优先级助手"])
        )

        parsed = source._message_from_lines(["消息优先级助手", "重要", "请处理"])

        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()
