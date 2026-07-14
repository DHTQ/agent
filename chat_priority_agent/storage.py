from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Assessment, ChatMessage


class MessageStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                app TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                received_at TEXT NOT NULL,
                level TEXT NOT NULL,
                score INTEGER NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                summary TEXT NOT NULL,
                notice TEXT NOT NULL DEFAULT '',
                keywords_json TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                suggested_action TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_level_time ON messages(level, received_at DESC)"
        )
        self._ensure_column("confidence", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("notice", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("suggested_action", "TEXT NOT NULL DEFAULT ''")
        self._connection.commit()

    def contains(self, message_id: str) -> bool:
        row = self._connection.execute("SELECT 1 FROM messages WHERE id = ?", (message_id,)).fetchone()
        return row is not None

    def save(self, message: ChatMessage, assessment: Assessment) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO messages (
                id, app, sender, content, received_at, level, score,
                confidence, summary, notice, keywords_json, reasons_json, suggested_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.app,
                message.sender,
                message.content,
                message.received_at.isoformat(),
                assessment.level.name.lower(),
                assessment.score,
                assessment.confidence,
                assessment.summary,
                assessment.notice_text(),
                json.dumps(assessment.keywords, ensure_ascii=False),
                json.dumps(assessment.reasons, ensure_ascii=False),
                assessment.suggested_action,
            ),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def recent_context(self, app: str, sender: str, limit: int) -> list[dict[str, object]]:
        if limit <= 0:
            return []
        rows = self._connection.execute(
            """
            SELECT content, received_at, level, summary, notice
            FROM messages
            WHERE app = ? AND sender = ?
            ORDER BY julianday(received_at) DESC
            LIMIT ?
            """,
            (app, sender, limit),
        ).fetchall()
        return [
            {
                "content": content,
                "received_at": received_at,
                "previous_assessment": level,
                "previous_summary": summary,
                "previous_notice": notice,
            }
            for content, received_at, level, summary, notice in reversed(rows)
        ]

    def _ensure_column(self, name: str, definition: str) -> None:
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(messages)")}
        if name not in columns:
            self._connection.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MessageStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
