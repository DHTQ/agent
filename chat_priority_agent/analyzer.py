from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from .config import LLMConfig, UserContextConfig
from .models import Assessment, ChatMessage, Importance


ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
            "description": "The message's overall importance and notification urgency.",
        },
        "score": {
            "type": "integer",
            "description": "A model-assigned importance score; this is not computed by code rules.",
        },
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "notice": {
            "type": "string",
            "description": "A natural, user-facing notification. It should not expose analysis, keywords, or scoring.",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
        },
        "suggested_action": {"type": "string"},
    },
    "required": [
        "level",
        "score",
        "confidence",
        "summary",
        "notice",
        "keywords",
        "reasons",
        "suggested_action",
    ],
    "additionalProperties": False,
}


class Analyzer(Protocol):
    async def analyze(
        self,
        message: ChatMessage,
        recent_context: list[dict[str, Any]] | None = None,
    ) -> Assessment: ...


class LLMMessageAnalyzer:
    """Ask an LLM Agent to understand and triage a message semantically."""

    def __init__(
        self,
        config: LLMConfig,
        user_context: UserContextConfig,
        base_dir: Path,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self.user_context = user_context
        self.instructions = self._load_instructions(base_dir / config.instructions_path)
        self.client = client or self._create_client()

    async def analyze(
        self,
        message: ChatMessage,
        recent_context: list[dict[str, Any]] | None = None,
    ) -> Assessment:
        payload = {
            "user_context": asdict(self.user_context),
            "current_message": {
                "app": message.app,
                "sender": message.sender,
                "content": message.content,
                "received_at": message.received_at.isoformat(),
            },
            "recent_conversation_with_sender": recent_context or [],
        }
        try:
            if self.config.resolved_provider() == "deepseek":
                output_text = await self._analyze_with_chat_completions(payload)
            else:
                output_text = await self._analyze_with_responses(payload)
        except Exception as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        try:
            return self._parse_output_text(output_text)
        except RuntimeError as exc:
            if self.config.resolved_provider() != "deepseek":
                raise
            try:
                repaired_text = await self._repair_chat_completion_output(payload, output_text, str(exc))
            except Exception as repair_exc:
                raise RuntimeError(
                    f"DeepSeek returned an incomplete assessment and repair failed: {repair_exc}"
                ) from repair_exc
            return self._parse_output_text(repaired_text)

    def _parse_output_text(self, output_text: str) -> Assessment:
        if not output_text:
            raise RuntimeError("The model returned no structured assessment")
        try:
            raw = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The model returned invalid JSON") from exc
        return self._parse_assessment(raw)

    async def _analyze_with_responses(self, payload: dict[str, Any]) -> str:
        response = await self.client.responses.create(
            model=self.config.resolved_model(),
            instructions=self.instructions,
            input=json.dumps(payload, ensure_ascii=False),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "message_priority_assessment",
                    "strict": True,
                    "schema": ASSESSMENT_SCHEMA,
                }
            },
        )
        return str(getattr(response, "output_text", ""))

    async def _analyze_with_chat_completions(self, payload: dict[str, Any]) -> str:
        response = await self.client.chat.completions.create(
            model=self.config.resolved_model(),
            messages=[
                {"role": "system", "content": self._deepseek_system_message()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return str(response.choices[0].message.content or "")

    async def _repair_chat_completion_output(
        self,
        payload: dict[str, Any],
        invalid_output: str,
        validation_error: str,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.config.resolved_model(),
            messages=[
                {"role": "system", "content": self._deepseek_system_message()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Repair the previous output. Return only one complete JSON object matching the schema.",
                            "validation_error": validation_error,
                            "original_input": payload,
                            "previous_output": invalid_output,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return str(response.choices[0].message.content or "")

    def _deepseek_system_message(self) -> str:
        return (
            f"{self.instructions}\n\n"
            "Return only one valid JSON object. Do not wrap it in Markdown. "
            "The API response must contain all internal fields even though only notice is shown to the user. "
            "The object must contain exactly these fields: level, score, confidence, summary, notice, "
            "keywords, reasons, suggested_action. "
            "notice is the only user-facing text and must sound natural; do not put keywords, scoring, "
            "confidence, or analysis wording in notice. "
            "keywords and reasons are internal fields and are still required. "
            "level must be one of low, medium, high, critical; score must be 0-100; confidence must be 0-1. "
            "JSON schema: "
            f"{json.dumps(ASSESSMENT_SCHEMA, ensure_ascii=False)}"
        )

    def _create_client(self) -> Any:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The OpenAI-compatible Python SDK is not installed. Run: python -m pip install -e ."
            ) from exc

        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Environment variable {self.config.api_key_env} is not set")
        options: dict[str, Any] = {
            "api_key": api_key,
            "timeout": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
        }
        base_url = self.config.resolved_base_url()
        if base_url:
            options["base_url"] = base_url
        return AsyncOpenAI(**options)

    @staticmethod
    def _load_instructions(path: Path) -> str:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read Agent instructions: {path}") from exc
        if not content:
            raise ValueError(f"Agent instructions file is empty: {path}")
        return content

    @staticmethod
    def _parse_assessment(raw: Any) -> Assessment:
        if not isinstance(raw, dict):
            raise RuntimeError("The model assessment must be a JSON object")
        try:
            score = int(raw["score"])
            confidence = float(raw["confidence"])
            summary = str(raw["summary"]).strip()
            notice = str(raw["notice"]).strip()
            suggested_action = str(raw["suggested_action"]).strip()
            keywords = _clean_string_list(raw["keywords"], 8)
            reasons = _clean_string_list(raw["reasons"], 5)
            level = Importance.parse(str(raw["level"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid model assessment: {exc}") from exc
        if not 0 <= score <= 100 or not 0 <= confidence <= 1:
            raise RuntimeError("Model score/confidence is outside the accepted range")
        if not summary or not notice or not reasons:
            raise RuntimeError("Model assessment requires a summary, notice, and at least one reason")
        return Assessment(
            level=level,
            score=score,
            confidence=confidence,
            summary=summary,
            notice=notice,
            keywords=tuple(keywords),
            reasons=tuple(reasons),
            suggested_action=suggested_action,
        )


def _clean_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("expected a list")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) >= limit:
            break
    return result
