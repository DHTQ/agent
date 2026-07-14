import asyncio
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from chat_priority_agent.agent import ChatPriorityAgent
from chat_priority_agent.config import LLMConfig
from chat_priority_agent.models import Assessment, ChatMessage, Importance
from chat_priority_agent.sources.base import MessageSource
from chat_priority_agent.storage import MessageStore


class FakeSource(MessageSource):
    def __init__(self, messages: list[ChatMessage]) -> None:
        self._messages = messages

    async def messages(self) -> AsyncIterator[ChatMessage]:
        for message in self._messages:
            yield message


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[ChatMessage, Assessment]] = []

    def notify(self, message: ChatMessage, assessment: Assessment) -> None:
        self.calls.append((message, assessment))


class FakeAnalyzer:
    def __init__(self, assessment: Assessment) -> None:
        self.assessment = assessment
        self.contexts: list[list[dict[str, object]]] = []

    async def analyze(self, message, recent_context=None):
        self.contexts.append(recent_context or [])
        return self.assessment


class AgentTests(unittest.TestCase):
    def test_agent_analyzes_stores_notifies_and_deduplicates(self):
        message = ChatMessage(
            app="QQ",
            sender="运维",
            content="紧急！服务器宕机，请立刻处理。",
            source_id="toast-1",
        )
        notifier = RecordingNotifier()
        assessment = Assessment(
            level=Importance.CRITICAL,
            score=88,
            confidence=0.9,
            summary="服务不可用，需要立即处理",
            keywords=("服务器", "故障"),
            reasons=("生产服务不可用",),
            suggested_action="立即联系运维",
        )

        with tempfile.TemporaryDirectory() as directory:
            with MessageStore(Path(directory) / "messages.db") as store:
                agent = ChatPriorityAgent(
                    source=FakeSource([message, message]),
                    analyzer=FakeAnalyzer(assessment),
                    notifier=notifier,
                    store=store,
                    llm_config=LLMConfig(model="test-model"),
                )
                asyncio.run(agent.run())

                self.assertTrue(store.contains("toast-1"))
                self.assertEqual(len(notifier.calls), 1)
                self.assertIs(notifier.calls[0][1].level, Importance.CRITICAL)


if __name__ == "__main__":
    unittest.main()
