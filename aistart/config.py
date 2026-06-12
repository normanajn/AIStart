from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "default_env": "terminal-tab",
    "terminal_app": "Terminal",
    "session_prefix": "aistart",
    "agents": {
        "claude": {"command": "claude", "args": [], "enabled": True},
        "codex": {"command": "codex", "args": [], "enabled": True},
        "antigravity": {"command": "agy", "args": [], "enabled": True},
    },
}


@dataclass(frozen=True)
class AgentConfig:
    command: str
    args: list[str] = field(default_factory=list)
    enabled: bool = True
    usage_command: list[str] | None = None


@dataclass(frozen=True)
class AppConfig:
    default_env: str
    terminal_app: str
    session_prefix: str
    agents: dict[str, AgentConfig]


def config_path() -> Path:
    override = os.environ.get("AISTART_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "aistart" / "config.json"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or config_path()
    data = DEFAULT_CONFIG
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = _merge(DEFAULT_CONFIG, json.load(fh))

    agents = {}
    for name, raw in data.get("agents", {}).items():
        agents[name] = AgentConfig(
            command=str(raw.get("command") or name),
            args=[str(arg) for arg in raw.get("args", [])],
            enabled=bool(raw.get("enabled", True)),
            usage_command=(
                [str(arg) for arg in raw["usage_command"]]
                if isinstance(raw.get("usage_command"), list)
                else None
            ),
        )

    return AppConfig(
        default_env=str(data.get("default_env", "terminal-tab")),
        terminal_app=str(data.get("terminal_app", "Terminal")),
        session_prefix=str(data.get("session_prefix", "aistart")),
        agents=agents,
    )


def init_config(path: Path | None = None) -> Path:
    cfg_path = path or config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    return cfg_path


def config_as_json(path: Path | None = None) -> str:
    cfg_path = path or config_path()
    if cfg_path.exists():
        return cfg_path.read_text(encoding="utf-8")
    return json.dumps(DEFAULT_CONFIG, indent=2) + "\n"
