from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from ..config import SourceConfig
from ..models import ChatMessage
from .base import MessageSource


class WindowsToastSource(MessageSource):
    """Read chat previews exposed through the Windows notification center."""

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self._recent_signatures: deque[str] = deque(maxlen=4096)
        self._seen: set[str] = set()

    async def messages(self) -> AsyncIterator[ChatMessage]:
        listener, notification_kinds, known_bindings = await self._create_listener()
        initial = await listener.get_notifications_async(notification_kinds.TOAST)
        if not self.config.include_existing:
            for item in initial:
                app_name = self._app_name(item)
                lines = self._text_lines(item, known_bindings)
                if self._wanted_app(app_name) and lines:
                    self._remember(self._signature(item, app_name, lines))

        while True:
            notifications = await listener.get_notifications_async(notification_kinds.TOAST)
            for item in notifications:
                app_name = self._app_name(item)
                if not self._wanted_app(app_name):
                    continue
                lines = self._text_lines(item, known_bindings)
                if not lines:
                    continue
                signature = self._signature(item, app_name, lines)
                if signature in self._seen:
                    continue
                self._remember(signature)
                yield ChatMessage(
                    app=app_name,
                    sender=lines[0] if len(lines) > 1 else "未知联系人",
                    content=" ".join(lines[1:]) if len(lines) > 1 else lines[0],
                    received_at=self._creation_time(item),
                    source_id=f"windows-toast:{signature}",
                )
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _create_listener(self):
        if sys_platform() != "win32":
            raise RuntimeError("windows_toast source can only run on Windows; use --source stdin elsewhere")
        try:
            from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
            from winrt.windows.ui.notifications.management import (
                UserNotificationListener,
                UserNotificationListenerAccessStatus,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Windows notification support is not installed. Run: "
                "python -m pip install -e '.[windows]'"
            ) from exc

        listener = UserNotificationListener.current
        status = listener.get_access_status()
        if status == UserNotificationListenerAccessStatus.UNSPECIFIED:
            status = await listener.request_access_async()
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            raise PermissionError(
                "Windows notification access was denied. Enable notification access for Python/Codex "
                "in Windows Settings, then run again."
            )
        return listener, NotificationKinds, KnownNotificationBindings

    def _wanted_app(self, app_name: str) -> bool:
        folded = app_name.casefold()
        if any(blocked.casefold() in folded for blocked in self.config.exclude_apps):
            return False
        return any(name.casefold() in folded for name in self.config.apps)

    def _remember(self, signature: str) -> None:
        if len(self._recent_signatures) == self._recent_signatures.maxlen:
            oldest = self._recent_signatures.popleft()
            self._seen.discard(oldest)
        self._recent_signatures.append(signature)
        self._seen.add(signature)

    @staticmethod
    def _signature(item: object, app_name: str, lines: list[str]) -> str:
        return f"{getattr(item, 'id', 'unknown')}|{app_name}|{'|'.join(lines)}"

    @staticmethod
    def _app_name(item: object) -> str:
        try:
            return str(item.app_info.display_info.display_name)
        except (AttributeError, RuntimeError):
            return "未知应用"

    @staticmethod
    def _text_lines(item: object, known_bindings: object) -> list[str]:
        try:
            binding = item.notification.visual.get_binding(known_bindings.TOAST_GENERIC)
            if binding is None:
                return []
            return [element.text.strip() for element in binding.get_text_elements() if element.text.strip()]
        except (AttributeError, RuntimeError):
            return []

    @staticmethod
    def _creation_time(item: object) -> datetime:
        value = getattr(item, "creation_time", None)
        return value if isinstance(value, datetime) else datetime.now(timezone.utc)


def sys_platform() -> str:
    import sys

    return sys.platform
