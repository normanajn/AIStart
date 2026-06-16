# AIStart

AIStart launches one or more agentic coding tools against the current directory
from either a command line interface or a terminal UI.

Supported agents in this version:

- Claude Code (`claude`)
- Codex (`codex`)
- Antigravity (`agy`, configurable and optional)

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[test]"
```

## Usage

Open the TUI:

```bash
aistart
aistart --theme light
```

In the TUI, press `s` to start selected agents and `t` to open the theme page
with `dark`, `light`, and `amber` themes.

Start Claude and Codex in new macOS Terminal tabs:

```bash
aistart start --agents claude,codex --env terminal-tab
```

Start Codex in tmux:

```bash
aistart start --agent codex --env tmux --cwd /path/to/project
```

Show usage:

```bash
aistart usage
aistart usage --json
```

Show agent installation status:

```bash
aistart agents
```

Create or print configuration:

```bash
aistart config --init
aistart config --show
```

## Launch Environments

- `terminal-tab`: open a new tab in macOS Terminal.app. This is the default.
- `terminal-window`: open a new macOS Terminal.app window.
- `tmux`: create a detached tmux session, then open a Terminal window attached to it. Multiple selected agents share one tmux session with split panes.
- `screen`: create a detached screen session, then open a Terminal window attached to it.
- `current`: replace the current process with one selected agent.

The `current` environment only supports one selected agent.

## Usage Statistics

Usage reporting is best-effort local telemetry plus live agent rate limits:

- Claude reads `~/.claude/stats-cache.json` for monthly totals and fetches the
  live 5h and weekly windows shown by Claude Code `/status` from the Anthropic
  API `anthropic-ratelimit-unified-*` response headers, authenticating with the
  Claude Code OAuth token (macOS keychain or `~/.claude/.credentials.json`) via
  a minimal probe request. Cached policy-limit JSON is used as a fallback when
  no token is available.
- Codex reads `~/.codex/state_5.sqlite` for local token/session totals and queries
  `codex app-server --stdio` for the live 5h and weekly rate-limit windows shown
  by Codex `/status`.
- Antigravity reports installed status unless a usage helper is configured.

Authoritative quota fields that are not exposed by a local agent are shown as
`unknown` unless a configured helper provides them.

## Configuration

Config lives at `~/.config/aistart/config.json` by default. Set
`AISTART_CONFIG` to use another path.

```json
{
  "default_env": "terminal-tab",
  "terminal_app": "Terminal",
  "session_prefix": "aistart",
  "agents": {
    "claude": { "command": "claude", "args": [], "enabled": true },
    "codex": { "command": "codex", "args": [], "enabled": true },
    "antigravity": { "command": "agy", "args": [], "enabled": true }
  }
}
```

Each agent can also define `usage_command` as a list of command arguments. The
helper should print JSON with any of these keys:

```json
{
  "session_usage": "10 messages this month",
  "remaining_usage": "unknown",
  "reset_time": "unknown",
  "monthly_limit": "unknown",
  "rate_limits": {
    "five_hour": { "used_percentage": 34, "resets_at": 1781307799 },
    "seven_day": { "used_percentage": 5, "resets_at": 1781894599 }
  },
  "details": {}
}
```
