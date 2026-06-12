from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    label: str
    default_command: str
    cwd_flag: str | None = None


@dataclass(frozen=True)
class AgentRuntime:
    definition: AgentDefinition
    command: str
    args: list[str]
    command_path: str | None
    enabled: bool

    @property
    def installed(self) -> bool:
        return self.command_path is not None

    def argv(self, cwd: Path) -> list[str]:
        argv = [self.command, *self.args]
        if self.definition.cwd_flag:
            argv.extend([self.definition.cwd_flag, str(cwd)])
        return argv


AGENTS: dict[str, AgentDefinition] = {
    "claude": AgentDefinition("claude", "Claude Code", "claude"),
    "codex": AgentDefinition("codex", "Codex", "codex", cwd_flag="--cd"),
    "antigravity": AgentDefinition("antigravity", "Antigravity", "agy"),
}


def resolve_agents(config: AppConfig) -> dict[str, AgentRuntime]:
    runtimes = {}
    for name, definition in AGENTS.items():
        agent_config = config.agents.get(name)
        command = agent_config.command if agent_config else definition.default_command
        args = agent_config.args if agent_config else []
        enabled = agent_config.enabled if agent_config else True
        runtimes[name] = AgentRuntime(
            definition=definition,
            command=command,
            args=args,
            command_path=shutil.which(command),
            enabled=enabled,
        )
    return runtimes
