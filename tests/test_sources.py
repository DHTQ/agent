import json
import unittest

from chat_priority_agent.sources.stdin import StdinSource


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


if __name__ == "__main__":
    unittest.main()
