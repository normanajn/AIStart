from __future__ import annotations

import os
import platform
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .agents import AgentRuntime
from .config import AppConfig


LAUNCH_ENVS = ("terminal-tab", "terminal-window", "tmux", "screen", "current")
CODEX_TMUX_BACKGROUND = "bg=#dff3ff"
TESTING_TMUX_PANE_TITLE = "Testing"


@dataclass(frozen=True)
class LaunchResult:
    agent: str
    ok: bool
    message: str
    attach_command: str | None = None


def shell_script(argv: list[str], cwd: Path) -> str:
    cd = "cd " + shlex.quote(str(cwd))
    command = " ".join(shlex.quote(part) for part in argv)
    return f"{cd} && exec {command}"


def session_name(prefix: str, agent: str) -> str:
    safe_agent = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in agent)
    return f"{prefix}-{safe_agent}-{int(time.time())}"


def launch_agents(
    agents: list[AgentRuntime],
    env: str,
    cwd: Path,
    config: AppConfig,
) -> list[LaunchResult]:
    if env not in LAUNCH_ENVS:
        return [LaunchResult("all", False, f"unknown environment: {env}")]
    if env == "current" and len(agents) != 1:
        return [LaunchResult("all", False, "current environment supports exactly one agent")]
    if env == "tmux" and len(agents) > 1:
        return [_launch_tmux_split(agents, cwd, config)]
    return [launch_agent(agent, env, cwd, config) for agent in agents]


def launch_agent(
    agent: AgentRuntime,
    env: str,
    cwd: Path,
    config: AppConfig,
) -> LaunchResult:
    if not agent.enabled:
        return LaunchResult(agent.definition.name, False, "agent disabled")
    if not agent.installed:
        return LaunchResult(agent.definition.name, False, f"command not found: {agent.command}")

    argv = agent.argv(cwd)
    script = shell_script(argv, cwd)
    if env == "terminal-tab":
        return _launch_terminal(agent.definition.name, script, config, new_tab=True)
    if env == "terminal-window":
        return _launch_terminal(agent.definition.name, script, config, new_tab=False)
    if env == "tmux":
        return _launch_tmux(agent.definition.name, script, cwd, config)
    if env == "screen":
        return _launch_screen(agent.definition.name, script, config)
    if env == "current":
        return _launch_current(agent.definition.name, argv, cwd)
    return LaunchResult(agent.definition.name, False, f"unknown environment: {env}")


def _launch_terminal(agent: str, script: str, config: AppConfig, new_tab: bool) -> LaunchResult:
    if platform.system() != "Darwin":
        return LaunchResult(agent, False, "terminal tabs/windows are only supported on macOS")
    if config.terminal_app != "Terminal":
        return LaunchResult(agent, False, f"unsupported terminal_app: {config.terminal_app}")
    ok, message = _open_terminal_script(script, config, new_tab=new_tab)
    if not ok:
        return LaunchResult(agent, False, message)
    return LaunchResult(agent, True, "started in Terminal")


def _launch_tmux(agent: str, script: str, cwd: Path, config: AppConfig) -> LaunchResult:
    name = session_name(config.session_prefix, agent)
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd), script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return LaunchResult(agent, False, result.stderr.strip() or "tmux failed")
    _style_tmux_pane_for_agent(agent, f"{name}:0.0")
    attach_command = f"tmux attach -t {shlex.quote(name)}"
    attach_ok, attach_message = _open_terminal_script(attach_command, config, new_tab=False)
    if attach_ok:
        return LaunchResult(
            agent,
            True,
            f"started tmux session {name}; opened Terminal attachment",
            attach_command,
        )
    return LaunchResult(agent, True, f"started tmux session {name}; {attach_message}", attach_command)


def _launch_tmux_split(agents: list[AgentRuntime], cwd: Path, config: AppConfig) -> LaunchResult:
    missing = [agent.command for agent in agents if not agent.installed]
    if missing:
        return LaunchResult("tmux", False, "command not found: " + ", ".join(missing))
    disabled = [agent.definition.name for agent in agents if not agent.enabled]
    if disabled:
        return LaunchResult("tmux", False, "agent disabled: " + ", ".join(disabled))

    name = session_name(config.session_prefix, "agents")
    scripts = [shell_script(agent.argv(cwd), cwd) for agent in agents]
    first = subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd), scripts[0]],
        check=False,
        capture_output=True,
        text=True,
    )
    if first.returncode != 0:
        return LaunchResult("tmux", False, first.stderr.strip() or "tmux failed")
    _style_tmux_pane_for_agent(agents[0].definition.name, f"{name}:0.0")

    for agent, script in zip(agents[1:], scripts[1:]):
        split = subprocess.run(
            [
                "tmux",
                "split-window",
                "-h",
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                name,
                "-c",
                str(cwd),
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if split.returncode != 0:
            return LaunchResult("tmux", False, split.stderr.strip() or "tmux split failed")
        pane_id = split.stdout.strip() if split.stdout else ""
        _style_tmux_pane_for_agent(agent.definition.name, pane_id or name)
        subprocess.run(
            ["tmux", "select-layout", "-t", name, "even-horizontal"],
            check=False,
            capture_output=True,
            text=True,
        )

    testing = subprocess.run(
        [
            "tmux",
            "split-window",
            "-v",
            "-f",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            name,
            "-c",
            str(cwd),
            "bash -l",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if testing.returncode != 0:
        return LaunchResult("tmux", False, testing.stderr.strip() or "tmux testing pane failed")
    testing_pane_id = testing.stdout.strip() if testing.stdout else ""
    _set_tmux_pane_title(testing_pane_id or name, TESTING_TMUX_PANE_TITLE)

    attach_command = f"tmux attach -t {shlex.quote(name)}"
    attach_ok, attach_message = _open_terminal_script(attach_command, config, new_tab=False)
    agent_names = ", ".join(agent.definition.name for agent in agents)
    if attach_ok:
        return LaunchResult(
            "tmux",
            True,
            f"started tmux session {name} with panes for {agent_names}; opened Terminal attachment",
            attach_command,
        )
    return LaunchResult(
        "tmux",
        True,
        f"started tmux session {name} with panes for {agent_names}; {attach_message}",
        attach_command,
    )


def _style_tmux_pane_for_agent(agent: str, target: str) -> None:
    if agent != "codex":
        return
    subprocess.run(
        ["tmux", "select-pane", "-t", target, "-P", CODEX_TMUX_BACKGROUND],
        check=False,
        capture_output=True,
        text=True,
    )


def _set_tmux_pane_title(target: str, title: str) -> None:
    subprocess.run(
        ["tmux", "select-pane", "-t", target, "-T", title],
        check=False,
        capture_output=True,
        text=True,
    )


def _launch_screen(agent: str, script: str, config: AppConfig) -> LaunchResult:
    name = session_name(config.session_prefix, agent)
    result = subprocess.run(
        ["screen", "-dmS", name, "sh", "-lc", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return LaunchResult(agent, False, result.stderr.strip() or "screen failed")
    attach_command = f"screen -r {shlex.quote(name)}"
    attach_ok, attach_message = _open_terminal_script(attach_command, config, new_tab=False)
    if attach_ok:
        return LaunchResult(
            agent,
            True,
            f"started screen session {name}; opened Terminal attachment",
            attach_command,
        )
    return LaunchResult(agent, True, f"started screen session {name}; {attach_message}", attach_command)


def _open_terminal_script(script: str, config: AppConfig, new_tab: bool) -> tuple[bool, str]:
    if platform.system() != "Darwin":
        return False, "terminal attachment is only supported on macOS"
    if config.terminal_app != "Terminal":
        return False, f"unsupported terminal_app: {config.terminal_app}"

    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    if new_tab:
        apple_script = f'''
tell application "Terminal"
    activate
    if (count of windows) = 0 then
        do script "{escaped}"
    else
        tell application "System Events" to keystroke "t" using command down
        delay 0.2
        do script "{escaped}" in selected tab of front window
    end if
end tell
'''
    else:
        apple_script = f'tell application "Terminal" to do script "{escaped}"'
    result = subprocess.run(["osascript", "-e", apple_script], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr.strip() or "failed to open Terminal"
    return True, "opened Terminal attachment"


def _launch_current(agent: str, argv: list[str], cwd: Path) -> LaunchResult:
    try:
        os.chdir(cwd)
        os.execvp(argv[0], argv)
    except OSError as exc:
        return LaunchResult(agent, False, str(exc))
