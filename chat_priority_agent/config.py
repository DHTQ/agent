from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Importance


@dataclass(slots=True)
class SourceConfig:
    type: str = "windows_uia"
    apps: list[str] = field(default_factory=lambda: ["QQ", "微信", "WeChat"])
    exclude_apps: list[str] = field(default_factory=lambda: ["消息优先级助手"])
    poll_interval_seconds: float = 0.5
    include_existing: bool = False


@dataclass(slots=True)
class LLMConfig:
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str | None = None
    instructions_path: str = "prompts/message_triage.md"
    context_messages: int = 8
    timeout_seconds: float = 45.0
    max_retries: int = 2

    def resolved_provider(self) -> str:
        provider = self.provider.strip().casefold()
        if provider not in {"deepseek", "openai"}:
            raise ValueError("llm.provider must be 'deepseek' or 'openai'")
        return provider

    def resolved_model(self) -> str:
        provider = self.resolved_provider()
        env_name = "DEEPSEEK_MODEL" if provider == "deepseek" else "OPENAI_MODEL"
        model = self.model.strip() or os.getenv(env_name, "").strip()
        if not model:
            raise ValueError(f"Set llm.model in config.json or the {env_name} environment variable")
        return model

    def resolved_base_url(self) -> str | None:
        if self.base_url:
            return self.base_url
        if self.resolved_provider() == "deepseek":
            return "https://api.deepseek.com"
        return None


@dataclass(slots=True)
class UserContextConfig:
    owner_name: str = ""
    role: str = ""
    timezone: str = "Asia/Shanghai"
    preferences: list[str] = field(default_factory=list)
    contacts: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class NotificationConfig:
    console_min_level: str = "medium"
    desktop_min_level: str = "high"
    desktop_enabled: bool = True

    @property
    def console_min(self) -> Importance:
        return Importance.parse(self.console_min_level)

    @property
    def desktop_min(self) -> Importance:
        return Importance.parse(self.desktop_min_level)


@dataclass(slots=True)
class StorageConfig:
    path: str = "data/messages.db"


@dataclass(slots=True)
class AgentConfig:
    source: SourceConfig = field(default_factory=SourceConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    user: UserContextConfig = field(default_factory=UserContextConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    base_dir: Path = field(default_factory=Path.cwd, repr=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], base_dir: Path | None = None) -> "AgentConfig":
        allowed = {"source", "llm", "user", "notifications", "storage"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown config sections: {', '.join(sorted(unknown))}")
        try:
            config = cls(
                source=SourceConfig(**raw.get("source", {})),
                llm=LLMConfig(**raw.get("llm", {})),
                user=UserContextConfig(**raw.get("user", {})),
                notifications=NotificationConfig(**raw.get("notifications", {})),
                storage=StorageConfig(**raw.get("storage", {})),
                base_dir=base_dir or Path.cwd(),
            )
        except TypeError as exc:
            raise ValueError(f"Invalid config field: {exc}") from exc
        config.validate()
        return config

    def validate(self) -> None:
        if self.source.poll_interval_seconds <= 0:
            raise ValueError("source.poll_interval_seconds must be positive")
        self.llm.resolved_provider()
        if not 0 <= self.llm.context_messages <= 50:
            raise ValueError("llm.context_messages must be between 0 and 50")
        if self.llm.timeout_seconds <= 0 or self.llm.max_retries < 0:
            raise ValueError("LLM timeout must be positive and max_retries cannot be negative")
        self.notifications.console_min
        self.notifications.desktop_min


def load_config(path: str | Path | None) -> AgentConfig:
    if path is None:
        default_path = Path("config.json")
        if not default_path.exists():
            return AgentConfig()
        path = default_path
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("The root of the config file must be a JSON object")
    return AgentConfig.from_dict(raw, base_dir=config_path.parent)
