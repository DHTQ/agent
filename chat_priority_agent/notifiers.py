from __future__ import annotations

import json
from dataclasses import asdict

from .config import NotificationConfig
from .models import Assessment, ChatMessage, Importance


class NotificationRouter:
    def __init__(self, config: NotificationConfig, json_output: bool = False) -> None:
        self.config = config
        self.json_output = json_output

    def notify(self, message: ChatMessage, assessment: Assessment) -> None:
        if assessment.level >= self.config.console_min:
            self._console(message, assessment)
        if self.config.desktop_enabled and assessment.level >= self.config.desktop_min:
            self._desktop(message, assessment)

    def _console(self, message: ChatMessage, assessment: Assessment) -> None:
        if self.json_output:
            payload = {
                "message": {
                    **asdict(message),
                    "received_at": message.received_at.isoformat(),
                    "id": message.id,
                },
                "notice": assessment.to_public_dict(),
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return

        print(
            f"[{assessment.level.label}] {message.app} · {message.sender}\n"
            f"  {assessment.notice_text()}",
            flush=True,
        )

    @staticmethod
    def _desktop(message: ChatMessage, assessment: Assessment) -> None:
        try:
            from winotify import Notification
        except ImportError:
            print(
                "桌面通知不可用：请安装 Windows 可选依赖 "
                "python -m pip install -e '.[windows]'",
                flush=True,
            )
            return
        toast = Notification(
            app_id="消息优先级助手",
            title=f"[{assessment.level.label}] {message.app} · {message.sender}",
            msg=assessment.notice_text(),
            duration="long" if assessment.level is Importance.CRITICAL else "short",
        )
        toast.show()
