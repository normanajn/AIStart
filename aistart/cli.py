from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .agents import AGENTS, AgentRuntime, resolve_agents
from .config import config_as_json, init_config, load_config
from .launchers import LAUNCH_ENVS, launch_agents
from .usage import collect_all_usage


console = Console()
err_console = Console(stderr=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aistart",
        description="Launch agentic coding frameworks against a directory.",
    )
    parser.add_argument("--version", action="version", version="aistart 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser("start", help="start one or more agents")
    start.add_argument("-a", "--agent", action="append", choices=sorted(AGENTS), help="agent to start")
    start.add_argument("--agents", help="comma-separated agents to start")
    start.add_argument(
        "-e",
        "--env",
        choices=LAUNCH_ENVS,
        help="launch environment; defaults to config default_env",
    )
    start.add_argument("-C", "--cwd", default=".", help="working directory")

    usage = subparsers.add_parser("usage", help="show usage for all agents")
    usage.add_argument("--json", action="store_true", help="emit JSON")

    agents = subparsers.add_parser("agents", help="show agent installation status")
    agents.add_argument("--json", action="store_true", help="emit JSON")

    config = subparsers.add_parser("config", help="manage configuration")
    config.add_argument("--init", action="store_true", help="create default config if missing")
    config.add_argument("--show", action="store_true", help="print effective config JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        from .tui import run_tui

        return run_tui()

    config = load_config()
    runtimes = resolve_agents(config)

    if args.command == "start":
        return _cmd_start(args, config, runtimes)
    if args.command == "usage":
        return _cmd_usage(args, config, runtimes)
    if args.command == "agents":
        return _cmd_agents(args, runtimes)
    if args.command == "config":
        return _cmd_config(args)
    return 1


def _selected_agents(args: argparse.Namespace, runtimes: dict[str, AgentRuntime]) -> list[AgentRuntime]:
    names: list[str] = []
    if args.agent:
        names.extend(args.agent)
    if args.agents:
        names.extend(name.strip() for name in args.agents.split(",") if name.strip())
    unknown = sorted(set(names) - set(AGENTS))
    if unknown:
        raise ValueError("unknown agent(s): " + ", ".join(unknown))
    if not names:
        raise ValueError("select at least one agent with --agent or --agents")
    deduped = list(dict.fromkeys(names))
    return [runtimes[name] for name in deduped]


def _cmd_start(args: argparse.Namespace, config, runtimes: dict[str, AgentRuntime]) -> int:
    try:
        selected = _selected_agents(args, runtimes)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        return 2
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        err_console.print(f"[red]not a directory: {cwd}[/red]")
        return 2
    env = args.env or config.default_env
    results = launch_agents(selected, env, cwd, config)
    for result in results:
        style = "green" if result.ok else "red"
        console.print(f"[{style}]{result.agent}: {result.message}[/{style}]")
        if result.attach_command:
            console.print(f"  attach: {result.attach_command}")
    return 0 if all(result.ok for result in results) else 1


def _cmd_usage(args: argparse.Namespace, config, runtimes: dict[str, AgentRuntime]) -> int:
    usage = collect_all_usage(runtimes, config)
    if args.json:
        print(json.dumps({name: stats.to_dict() for name, stats in usage.items()}, indent=2))
        return 0

    table = Table(title="AI Agent Usage")
    table.add_column("Agent", no_wrap=True)
    table.add_column("5h limit", no_wrap=True)
    table.add_column("5h reset", no_wrap=True)
    table.add_column("Weekly limit", no_wrap=True)
    table.add_column("Weekly reset", no_wrap=True)
    table.add_column("Session usage")
    table.add_column("Notes")
    for name, stats in usage.items():
        table.add_row(
            name,
            stats.limit_5h,
            stats.reset_5h,
            stats.limit_weekly,
            stats.reset_weekly,
            stats.session_usage,
            stats.error or "",
        )
    console.print(table)
    return 0


def _cmd_agents(args: argparse.Namespace, runtimes: dict[str, AgentRuntime]) -> int:
    data = {
        name: {
            "label": runtime.definition.label,
            "command": runtime.command,
            "command_path": runtime.command_path,
            "installed": runtime.installed,
            "enabled": runtime.enabled,
        }
        for name, runtime in runtimes.items()
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    table = Table(title="AI Agents")
    table.add_column("Agent")
    table.add_column("Command")
    table.add_column("Status")
    for name, info in data.items():
        status = "installed" if info["installed"] else "missing"
        if not info["enabled"]:
            status = "disabled"
        table.add_row(name, str(info["command"]), status)
    console.print(table)
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    if args.init:
        path = init_config()
        console.print(f"Config ready: {path}")
        return 0
    if args.show:
        print(config_as_json(), end="")
        return 0
    err_console.print("Use --init or --show")
    return 2


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
