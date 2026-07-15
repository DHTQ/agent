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
        initial = await self._get_notifications(listener, notification_kinds)
        if not self.config.include_existing:
            for item in initial:
                app_name = self._app_name(item)
                lines = self._text_lines(item, known_bindings)
                if self._wanted_app(app_name) and lines:
                    self._remember(self._signature(item, app_name, lines))

        while True:
            notifications = await self._get_notifications(listener, notification_kinds)
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

    @staticmethod
    async def _get_notifications(listener: object, notification_kinds: object) -> object:
        try:
            return await listener.get_notifications_async(notification_kinds.TOAST)
        except ModuleNotFoundError as exc:
            missing = exc.name or "unknown"
            package = _winrt_package_name(missing)
            install_hint = 'python -m pip install -e ".[windows]"'
            if package:
                install_hint += f" or python -m pip install {package}"
            raise RuntimeError(
                f"Windows notification support is missing WinRT module '{missing}'. Run: {install_hint}"
            ) from exc
        except PermissionError as exc:
            raise PermissionError(
                "Windows 拒绝读取通知历史。若系统通知已经开启，原因通常是当前 Python 进程没有"
                "应用包身份和 userNotificationListener 能力；请先使用 --source stdin 测试 Agent，"
                "QQ 实时监听需要通过具备该能力的 Windows 打包桥接程序接入。"
            ) from exc
        except OSError as exc:
            if _is_not_implemented(exc):
                raise RuntimeError(_not_implemented_message()) from exc
            raise

    async def _create_listener(self):
        if sys_platform() != "win32":
            raise RuntimeError("windows_toast source can only run on Windows; use --source stdin elsewhere")
        if not _has_package_identity():
            raise RuntimeError(_unpackaged_process_message())
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

        listener = self._current_listener(UserNotificationListener)
        try:
            status = listener.get_access_status()
        except OSError as exc:
            if _is_not_implemented(exc):
                raise RuntimeError(_not_implemented_message()) from exc
            raise
        if status == UserNotificationListenerAccessStatus.UNSPECIFIED:
            raise PermissionError(
                "Windows 尚未授予通知历史访问权限。命令行 Agent 无法自动弹出授权窗口；"
                "请先为打包后的 Windows 通知桥接程序授予通知访问权限。"
            )
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            raise PermissionError(
                "Windows 已拒绝通知历史访问。请在 Windows 设置中为打包后的通知桥接程序开启权限。"
            )
        return listener, NotificationKinds, KnownNotificationBindings

    @staticmethod
    def _current_listener(listener_type: object) -> object:
        try:
            return listener_type.current
        except OSError as exc:
            if _is_not_implemented(exc):
                raise RuntimeError(_not_implemented_message()) from exc
            raise

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


def _winrt_package_name(module_name: str) -> str:
    prefix = "winrt.windows."
    if not module_name.startswith(prefix):
        return ""
    parts = module_name[len(prefix) :].split(".")
    formatted = ".".join("UI" if part == "ui" else part.capitalize() for part in parts)
    return f"winrt-Windows.{formatted}"


def _is_not_implemented(exc: OSError) -> bool:
    error_codes = (
        getattr(exc, "winerror", None),
        getattr(exc, "errno", None),
        getattr(exc, "hresult", None),
        exc.args[0] if exc.args else None,
    )
    for code in error_codes:
        if not isinstance(code, int):
            continue
        if code == -2147467263 or code & 0xFFFFFFFF == 0x80004001:
            return True
    return False


def _has_package_identity() -> bool:
    if sys_platform() != "win32":
        return False
    try:
        import ctypes

        length = ctypes.c_uint32()
        result = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
    except (AttributeError, OSError):
        return False
    return result in (0, 122)


def _unpackaged_process_message() -> str:
    return (
        "当前 python.exe 没有 Windows 应用包身份，无法使用 UserNotificationListener 读取 QQ/微信通知历史。"
        "这不是 DeepSeek API 或普通通知开关的问题，单独修改 Windows 设置无法解决。"
        "请先运行 python -m chat_priority_agent run --source stdin --config config.json 测试 Agent；"
        "QQ 实时监听需要通过声明 userNotificationListener 能力的 Windows 打包桥接程序接入。"
    )


def _not_implemented_message() -> str:
    return (
        "Windows 返回 UserNotificationListener 尚未实现。当前进程通常没有应用包身份或"
        "userNotificationListener 能力，普通命令行 Python 无法读取通知历史；"
        "请使用 --source stdin 测试 Agent，QQ 实时监听需要通过 Windows 打包桥接程序接入。"
    )
