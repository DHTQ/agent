from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from ..config import SourceConfig
from ..models import ChatMessage
from .base import MessageSource


class WindowsUIANotificationSource(MessageSource):
    """Read new Windows notification banners through UI Automation."""

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self._active_signatures: set[str] = set()

    async def messages(self) -> AsyncIterator[ChatMessage]:
        automation = self._load_automation()
        initial = self._scan(automation)
        self._active_signatures = {signature for signature, _ in initial}

        queue: asyncio.Queue[ChatMessage | Exception] = asyncio.Queue()
        producer = asyncio.create_task(self._poll(automation, queue))
        try:
            if self.config.include_existing:
                for _, message in initial:
                    yield message

            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def _poll(
        self,
        automation: Any,
        queue: asyncio.Queue[ChatMessage | Exception],
    ) -> None:
        try:
            while True:
                current = self._scan(automation)
                current_signatures = {signature for signature, _ in current}
                for signature, message in current:
                    if signature not in self._active_signatures:
                        queue.put_nowait(message)
                self._active_signatures = current_signatures
                await asyncio.sleep(self.config.poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            queue.put_nowait(exc)

    def _scan(self, automation: Any) -> list[tuple[str, ChatMessage]]:
        try:
            top_level_controls = automation.GetRootControl().GetChildren()
        except Exception as exc:
            raise RuntimeError(
                "无法读取 Windows 桌面通知界面。请从当前登录用户的普通 CMD 窗口运行 Agent，"
                "不要从服务、计划任务或隔离桌面启动。"
            ) from exc

        messages: list[tuple[str, ChatMessage]] = []
        for top in top_level_controls:
            if self._property(top, "ClassName") != "Windows.UI.Core.CoreWindow":
                continue
            try:
                controls = automation.WalkControl(top, True, 3)
                for control, _ in controls:
                    if self._property(control, "ClassName") != "FlexibleToastView":
                        continue
                    parsed = self._parse_toast(control)
                    if parsed is not None:
                        messages.append(parsed)
            except Exception:
                # Notification banners can disappear while UI Automation is reading them.
                continue
        return messages

    def _parse_toast(self, toast: Any) -> tuple[str, ChatMessage] | None:
        try:
            children = toast.GetChildren()
        except Exception:
            return None

        lines = [
            self._property(child, "Name").strip()
            for child in children
            if self._property(child, "ControlTypeName") == "TextControl"
            and self._property(child, "Name").strip()
        ]
        return self._message_from_lines(lines)

    def _message_from_lines(self, lines: list[str]) -> tuple[str, ChatMessage] | None:
        if len(lines) < 3:
            return None
        app, sender, *content_lines = lines
        content = " ".join(content_lines).strip()
        if not self._wanted_app(app) or not sender.strip() or not content:
            return None

        signature = "\x1f".join((app.strip(), sender.strip(), content))
        received_at = datetime.now(timezone.utc)
        source_hash = sha256(
            f"{signature}\x1f{received_at.isoformat(timespec='milliseconds')}".encode("utf-8")
        ).hexdigest()
        return signature, ChatMessage(
            app=app.strip(),
            sender=sender.strip(),
            content=content,
            received_at=received_at,
            source_id=f"windows-uia:{source_hash}",
        )

    def _wanted_app(self, app_name: str) -> bool:
        folded = app_name.casefold()
        if any(blocked.casefold() in folded for blocked in self.config.exclude_apps):
            return False
        return any(name.casefold() in folded for name in self.config.apps)

    @staticmethod
    def _property(control: Any, name: str) -> str:
        try:
            value = getattr(control, name, "")
        except Exception:
            return ""
        return value if isinstance(value, str) else str(value or "")

    @staticmethod
    def _load_automation() -> Any:
        if sys_platform() != "win32":
            raise RuntimeError("windows_uia source can only run on Windows; use --source stdin elsewhere")
        try:
            import uiautomation
        except ImportError as exc:
            raise RuntimeError(
                'Windows UI Automation support is not installed. Run: python -m pip install -e ".[windows]"'
            ) from exc
        return uiautomation


def sys_platform() -> str:
    import sys

    return sys.platform
