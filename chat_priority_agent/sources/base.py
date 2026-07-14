from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..models import ChatMessage


class MessageSource(ABC):
    @abstractmethod
    def messages(self) -> AsyncIterator[ChatMessage]:
        """Yield new messages until the source is closed."""

