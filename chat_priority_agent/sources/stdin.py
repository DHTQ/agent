from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from ..models import ChatMessage
from .base import MessageSource


class StdinSource(MessageSource):
    """Read JSON Lines, or convenient `sender: message` lines, from stdin."""

    def __init__(self, default_app: str = "stdin") -> None:
        self.default_app = default_app

    async def messages(self) -> AsyncIterator[ChatMessage]:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            yield self.parse_line(line)

    def parse_line(self, line: str) -> ChatMessage:
        if line.startswith("{"):
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError("Each JSON line must be an object")
            content = str(raw.get("content", "")).strip()
            if not content:
                raise ValueError("JSON message requires non-empty 'content'")
            received_at = self._parse_time(raw.get("received_at"))
            return ChatMessage(
                app=str(raw.get("app", self.default_app)),
                sender=str(raw.get("sender", "未知联系人")),
                content=content,
                received_at=received_at,
                source_id=str(raw.get("id", "")),
            )

        sender, separator, content = line.partition(":")
        if not separator:
            sender, separator, content = line.partition("：")
        if not separator:
            sender, content = "未知联系人", line
        return ChatMessage(app=self.default_app, sender=sender.strip(), content=content.strip())

    @staticmethod
    def _parse_time(value: object) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

