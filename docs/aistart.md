# AIStart User Guide

AIStart is a small launcher for running coding agents in the directory where
you are working. It supports Claude Code, Codex, and Antigravity through the
configurable `agy` adapter.

## Quick Start

```bash
cd AIStart
python3 -m venv venv
source venv/bin/activate
pip install -e ".[test]"
aistart
aistart --theme amber
```

Running `aistart` without arguments opens the TUI. Select one or more agents,
choose a launch environment, press `t` to choose `dark`, `light`, or `amber`
from the theme page, and press `s` to start.

## Command Line Examples

Launch Claude and Codex in new Terminal tabs:

```bash
aistart start --agents claude,codex
```

Launch Claude in tmux:

```bash
aistart start --agent claude --env tmux
```

Launch Codex against another directory:

```bash
aistart start --agent codex --env terminal-tab --cwd ~/Git-Repositories/project
```

Print usage as JSON:

```bash
aistart usage --json
```

## Launch Environments

`terminal-tab` is the default and opens a new macOS Terminal tab. `terminal-window`
opens a new macOS Terminal window. `tmux` and `screen` create detached sessions,
then open a new Terminal window attached to the session. When multiple agents
are selected with `tmux`, AIStart creates one tmux session and starts each agent
in its own top-row pane, then adds a full-width `Testing` shell pane below them.
Both tmux and screen still print the manual attach command. `current` replaces
the current process and only works with one selected agent.

## Configuration

Create the default config:

```bash
aistart config --init
```

The default path is `~/.config/aistart/config.json`. You can override it with
`AISTART_CONFIG=/path/to/config.json`.

Antigravity support is intentionally command-based. If your executable has a
different name or needs arguments, configure it:

```json
{
  "agents": {
    "antigravity": {
      "command": "agy",
      "args": ["--some-option"],
      "enabled": true
    }
  }
}
```

## Usage Data

Usage values are local and best-effort. Claude monthly totals are read from
`~/.claude/stats-cache.json`; the live Claude 5h and weekly windows are fetched
from the Anthropic API `anthropic-ratelimit-unified-*` response headers (the
same data Claude Code `/status` shows) using the Claude Code OAuth token from
the macOS keychain or `~/.claude/.credentials.json`. This issues a minimal
`max_tokens` probe request. When no token is available, any cached policy-limit
JSON is used as a fallback. Codex token/session totals
are read from `~/.codex/state_5.sqlite`. Codex 5h and weekly limits are fetched
through `codex app-server --stdio` using the same `account/rateLimits/read` data
that backs Codex `/status`. Fields that are not exposed by a local agent are
`unknown` unless you configure a helper command.

Helper commands are configured per agent with `usage_command`. The helper should
print JSON:

```json
{
  "session_usage": "42 messages this month",
  "remaining_usage": "unknown",
  "reset_time": "unknown",
  "monthly_limit": "unknown",
  "limit_5h": "34% used",
  "reset_5h": "Jun 12 18:43",
  "limit_weekly": "5% used",
  "reset_weekly": "Jun 19 13:43",
  "rate_limits": {
    "five_hour": { "used_percentage": 34, "resets_at": 1781307799 },
    "seven_day": { "used_percentage": 5, "resets_at": 1781894599 }
  },
  "details": {}
}
```
