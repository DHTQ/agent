import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from chat_priority_agent.analyzer import LLMMessageAnalyzer
from chat_priority_agent.config import LLMConfig, UserContextConfig
from chat_priority_agent.models import ChatMessage, Importance


class FakeResponses:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.output if isinstance(self.output, str) else json.dumps(self.output, ensure_ascii=False)
        return SimpleNamespace(output_text=text)


class FakeChatCompletions:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        output = self.output
        if isinstance(output, list):
            output = output[min(len(self.calls) - 1, len(output) - 1)]
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeClient:
    def __init__(self, output: object) -> None:
        self.responses = FakeResponses(output)
        self.chat = SimpleNamespace(completions=FakeChatCompletions(output))


class FailingResponses:
    async def create(self, **kwargs):
        raise ConnectionError("offline")


class FailingChatCompletions:
    async def create(self, **kwargs):
        raise ConnectionError("offline")


class FailingClient:
    responses = FailingResponses()
    chat = SimpleNamespace(completions=FailingChatCompletions())


def valid_output():
    return {
        "level": "high",
        "score": 72,
        "confidence": 0.91,
        "summary": "客户项目需要今天确认上线窗口",
        "notice": "张三在问今晚的上线窗口，最好今天给他一个确认答复。",
        "keywords": ["客户项目", "上线窗口", "今天", "今天"],
        "reasons": ["客户接口人提出了有截止时间的明确请求"],
        "suggested_action": "今天内回复并确认上线窗口",
    }


class LLMAnalyzerTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_model_output_becomes_assessment(self):
        client = FakeClient(valid_output())
        analyzer = LLMMessageAnalyzer(
            config=LLMConfig(model="deepseek-v4-flash"),
            user_context=UserContextConfig(
                owner_name="小李",
                role="项目经理",
                contacts={"张三": "客户接口人"},
            ),
            base_dir=Path.cwd(),
            client=client,
        )

        result = await analyzer.analyze(
            ChatMessage(app="QQ", sender="张三", content="今天能确认上线窗口吗？"),
            [{"content": "窗口暂定今晚", "previous_assessment": "medium"}],
        )

        self.assertIs(result.level, Importance.HIGH)
        self.assertEqual(result.score, 72)
        self.assertEqual(result.confidence, 0.91)
        self.assertEqual(result.notice_text(), "张三在问今晚的上线窗口，最好今天给他一个确认答复。")
        self.assertEqual(result.keywords.count("今天"), 1)
        call = client.chat.completions.calls[0]
        payload = json.loads(str(call["messages"][1]["content"]))
        self.assertEqual(payload["user_context"]["contacts"]["张三"], "客户接口人")
        self.assertEqual(len(payload["recent_conversation_with_sender"]), 1)
        self.assertEqual(call["model"], "deepseek-v4-flash")
        self.assertEqual(call["response_format"]["type"], "json_object")

    async def test_openai_provider_uses_responses_schema(self):
        client = FakeClient(valid_output())
        analyzer = LLMMessageAnalyzer(
            config=LLMConfig(provider="openai", model="test-model"),
            user_context=UserContextConfig(),
            base_dir=Path.cwd(),
            client=client,
        )

        await analyzer.analyze(ChatMessage(app="QQ", sender="sender", content="test"))

        call = client.responses.calls[0]
        self.assertEqual(call["text"]["format"]["type"], "json_schema")

    async def test_deepseek_incomplete_output_is_repaired_once(self):
        client = FakeClient([{"notice": "先给了一句提示"}, valid_output()])
        analyzer = LLMMessageAnalyzer(
            config=LLMConfig(model="deepseek-v4-flash"),
            user_context=UserContextConfig(),
            base_dir=Path.cwd(),
            client=client,
        )

        result = await analyzer.analyze(ChatMessage(app="QQ", sender="张三", content="把表格发给我"))

        self.assertIs(result.level, Importance.HIGH)
        self.assertEqual(len(client.chat.completions.calls), 2)
        repair_payload = json.loads(str(client.chat.completions.calls[1]["messages"][1]["content"]))
        self.assertIn("validation_error", repair_payload)

    async def test_invalid_model_output_is_rejected(self):
        output = valid_output()
        output["confidence"] = 2
        analyzer = LLMMessageAnalyzer(
            LLMConfig(model="test-model"),
            UserContextConfig(),
            Path.cwd(),
            client=FakeClient(output),
        )

        with self.assertRaisesRegex(RuntimeError, "outside"):
            await analyzer.analyze(ChatMessage(app="QQ", sender="张三", content="测试"))

    async def test_api_error_is_wrapped(self):
        analyzer = LLMMessageAnalyzer(
            LLMConfig(model="test-model"),
            UserContextConfig(),
            Path.cwd(),
            client=FailingClient(),
        )

        with self.assertRaisesRegex(RuntimeError, "LLM request failed: offline"):
            await analyzer.analyze(ChatMessage(app="QQ", sender="张三", content="测试"))


if __name__ == "__main__":
    unittest.main()
