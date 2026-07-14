import tempfile
import unittest
from pathlib import Path

from chat_priority_agent.models import Assessment, ChatMessage, Importance
from chat_priority_agent.storage import MessageStore


class StorageTests(unittest.TestCase):
    def test_store_deduplicates_messages(self):
        message = ChatMessage(app="QQ", sender="张三", content="请确认", source_id="same-id")
        assessment = Assessment(
            level=Importance.HIGH,
            score=70,
            confidence=0.8,
            summary="需要确认",
            keywords=("确认",),
            reasons=("需要用户回复",),
            suggested_action="回复发送者",
            notice="这条消息需要你回复发送者。",
        )

        with tempfile.TemporaryDirectory() as directory:
            with MessageStore(Path(directory) / "messages.db") as store:
                self.assertTrue(store.save(message, assessment))
                self.assertTrue(store.contains(message.id))
                self.assertFalse(store.save(message, assessment))
                context = store.recent_context("QQ", "张三", 3)
                self.assertEqual(len(context), 1)
                self.assertEqual(context[0]["previous_assessment"], "high")
                self.assertEqual(context[0]["previous_notice"], "这条消息需要你回复发送者。")


if __name__ == "__main__":
    unittest.main()
