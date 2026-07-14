from __future__ import annotations

import logging
from typing import Protocol

from .analyzer import Analyzer
from .config import LLMConfig
from .models import Assessment, ChatMessage
from .sources.base import MessageSource
from .storage import MessageStore


logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, message: ChatMessage, assessment: Assessment) -> None: ...


class ChatPriorityAgent:
    def __init__(
        self,
        source: MessageSource,
        analyzer: Analyzer,
        notifier: Notifier,
        store: MessageStore,
        llm_config: LLMConfig,
    ) -> None:
        self.source = source
        self.analyzer = analyzer
        self.notifier = notifier
        self.store = store
        self.llm_config = llm_config

    async def run(self) -> None:
        async for message in self.source.messages():
            if self.store.contains(message.id):
                logger.debug("Skipping duplicate message %s", message.id)
                continue
            context = self.store.recent_context(
                message.app,
                message.sender,
                limit=self.llm_config.context_messages,
            )
            try:
                assessment = await self.analyzer.analyze(message, context)
            except Exception:
                logger.exception("Agent failed to assess message %s", message.id)
                continue
            if self.store.save(message, assessment):
                self.notifier.notify(message, assessment)
