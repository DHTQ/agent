from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from hashlib import sha256
from typing import Any


class Importance(IntEnum):
    LOW = 10
    MEDIUM = 20
    HIGH = 30
    CRITICAL = 40

    @classmethod
    def parse(cls, value: str) -> "Importance":
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            allowed = ", ".join(item.name.lower() for item in cls)
            raise ValueError(f"Unknown importance '{value}'; expected one of: {allowed}") from exc

    @property
    def label(self) -> str:
        return {
            Importance.LOW: "低",
            Importance.MEDIUM: "普通",
            Importance.HIGH: "重要",
            Importance.CRITICAL: "紧急",
        }[self]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    app: str
    sender: str
    content: str
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_id: str = ""

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None:
            object.__setattr__(self, "received_at", self.received_at.replace(tzinfo=timezone.utc))

    @property
    def id(self) -> str:
        if self.source_id:
            return self.source_id
        raw = "\x1f".join(
            (self.app, self.sender, self.content, self.received_at.isoformat(timespec="seconds"))
        )
        return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Assessment:
    level: Importance
    score: int
    confidence: float
    summary: str
    keywords: tuple[str, ...]
    reasons: tuple[str, ...]
    suggested_action: str
    notice: str = ""

    def notice_text(self) -> str:
        return self.notice.strip() or self.suggested_action.strip() or self.summary.strip()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.name.lower(),
            "level_label": self.level.label,
            "notice": self.notice_text(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.name.lower(),
            "level_label": self.level.label,
            "score": self.score,
            "confidence": self.confidence,
            "summary": self.summary,
            "notice": self.notice_text(),
            "keywords": list(self.keywords),
            "reasons": list(self.reasons),
            "suggested_action": self.suggested_action,
        }
