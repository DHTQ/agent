from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .agent import ChatPriorityAgent
from .analyzer import LLMMessageAnalyzer
from .config import AgentConfig, load_config
from .models import ChatMessage
from .notifiers import NotificationRouter
from .sources import StdinSource, WindowsToastSource, WindowsUIANotificationSource
from .storage import MessageStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chat-priority-agent",
        description="监控聊天通知，评估消息重要性并分级通知。",
    )
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="持续监控消息")
    run.add_argument("--config", help="JSON 配置文件；默认读取当前目录 config.json")
    run.add_argument(
        "--source",
        choices=("windows_uia", "windows_toast", "stdin"),
        help="覆盖配置中的消息源",
    )
    run.add_argument("--json-output", action="store_true", help="控制台使用 JSON Lines 输出")
    run.add_argument("--verbose", action="store_true", help="输出调试日志")

    analyze = subparsers.add_parser("analyze", help="分析一条消息，不写数据库")
    analyze.add_argument("text", help="消息正文")
    analyze.add_argument("--sender", default="未知联系人")
    analyze.add_argument("--app", default="手动测试")
    analyze.add_argument("--config", help="JSON 配置文件")
    return parser


def _source(config: AgentConfig):
    if config.source.type == "stdin":
        return StdinSource(default_app="stdin")
    if config.source.type == "windows_uia":
        return WindowsUIANotificationSource(config.source)
    if config.source.type == "windows_toast":
        return WindowsToastSource(config.source)
    raise ValueError(f"Unsupported source type: {config.source.type}")


async def _run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.source:
        config.source.type = args.source
    config.llm.resolved_model()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    store = MessageStore(config.storage.path)
    try:
        agent = ChatPriorityAgent(
            source=_source(config),
            analyzer=LLMMessageAnalyzer(config.llm, config.user, config.base_dir),
            notifier=NotificationRouter(config.notifications, json_output=args.json_output),
            store=store,
            llm_config=config.llm,
        )
        await agent.run()
    finally:
        store.close()


async def _analyze(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    config.llm.resolved_model()
    assessment = await LLMMessageAnalyzer(config.llm, config.user, config.base_dir).analyze(
        ChatMessage(app=args.app, sender=args.sender, content=args.text),
        recent_context=[],
    )
    if assessment.level >= config.notifications.console_min:
        print(assessment.notice_text())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    try:
        if command == "analyze":
            asyncio.run(_analyze(args))
        else:
            if args.command is None:
                args.config = None
                args.source = None
                args.json_output = False
                args.verbose = False
            asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, PermissionError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
