from pathlib import Path

from aistart.agents import AgentDefinition, AgentRuntime
from aistart.config import load_config
from aistart.launchers import launch_agents, shell_script


def runtime(name="claude"):
    return AgentRuntime(
        definition=AgentDefinition(name, name.title(), name),
        command=name,
        args=[],
        command_path=f"/bin/{name}",
        enabled=True,
    )


def test_shell_script_quotes_cwd_and_command():
    script = shell_script(["codex", "--cd", "/tmp/a b"], Path("/tmp/a b"))

    assert script == "cd '/tmp/a b' && exec codex --cd '/tmp/a b'"


def test_current_rejects_multiple_agents(tmp_path):
    results = launch_agents(
        [runtime("claude"), runtime("codex")],
        "current",
        tmp_path,
        load_config(tmp_path / "missing.json"),
    )

    assert results[0].ok is False
    assert "exactly one" in results[0].message


def test_tmux_starts_session_then_opens_terminal_attach(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stderr = ""
            stdout = "%1\n"

        return Result()

    monkeypatch.setattr("aistart.launchers.platform.system", lambda: "Darwin")
    monkeypatch.setattr("aistart.launchers.session_name", lambda prefix, agent: "aistart-claude-1")
    monkeypatch.setattr("aistart.launchers.subprocess.run", fake_run)

    results = launch_agents(
        [runtime("claude")],
        "tmux",
        tmp_path,
        load_config(tmp_path / "missing.json"),
    )

    assert results[0].ok is True
    assert calls[0][:6] == ["tmux", "new-session", "-d", "-s", "aistart-claude-1", "-c"]
    assert calls[1][0:2] == ["osascript", "-e"]
    assert "tmux attach -t aistart-claude-1" in calls[1][2]


def test_tmux_codex_sets_pale_blue_pane_background(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stderr = ""
            stdout = "%1\n"

        return Result()

    monkeypatch.setattr("aistart.launchers.platform.system", lambda: "Darwin")
    monkeypatch.setattr("aistart.launchers.session_name", lambda prefix, agent: "aistart-codex-1")
    monkeypatch.setattr("aistart.launchers.subprocess.run", fake_run)

    results = launch_agents(
        [runtime("codex")],
        "tmux",
        tmp_path,
        load_config(tmp_path / "missing.json"),
    )

    assert results[0].ok is True
    assert calls[1] == ["tmux", "select-pane", "-t", "aistart-codex-1:0.0", "-P", "bg=#dff3ff"]
    assert calls[2][0:2] == ["osascript", "-e"]


def test_tmux_multi_agent_uses_split_panes(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stderr = ""
            stdout = "%2\n"

        return Result()

    monkeypatch.setattr("aistart.launchers.platform.system", lambda: "Darwin")
    monkeypatch.setattr("aistart.launchers.session_name", lambda prefix, agent: "aistart-agents-1")
    monkeypatch.setattr("aistart.launchers.subprocess.run", fake_run)

    results = launch_agents(
        [runtime("claude"), runtime("codex")],
        "tmux",
        tmp_path,
        load_config(tmp_path / "missing.json"),
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert calls[0][:6] == ["tmux", "new-session", "-d", "-s", "aistart-agents-1", "-c"]
    assert calls[1][:6] == ["tmux", "split-window", "-h", "-P", "-F", "#{pane_id}"]
    assert "exec codex" in calls[1][-1]
    assert calls[2] == ["tmux", "select-pane", "-t", "%2", "-P", "bg=#dff3ff"]
    assert calls[3] == ["tmux", "select-layout", "-t", "aistart-agents-1", "even-horizontal"]
    assert calls[4][:7] == ["tmux", "split-window", "-v", "-f", "-P", "-F", "#{pane_id}"]
    assert calls[4][-1] == "bash -l"
    assert calls[5] == ["tmux", "select-pane", "-t", "%2", "-T", "Testing"]
    assert calls[6][0:2] == ["osascript", "-e"]
    assert "tmux attach -t aistart-agents-1" in calls[6][2]


def test_screen_starts_session_then_opens_terminal_attach(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("aistart.launchers.platform.system", lambda: "Darwin")
    monkeypatch.setattr("aistart.launchers.session_name", lambda prefix, agent: "aistart-claude-1")
    monkeypatch.setattr("aistart.launchers.subprocess.run", fake_run)

    results = launch_agents(
        [runtime("claude")],
        "screen",
        tmp_path,
        load_config(tmp_path / "missing.json"),
    )

    assert results[0].ok is True
    assert calls[0] == ["screen", "-dmS", "aistart-claude-1", "sh", "-lc", f"cd {tmp_path} && exec claude"]
    assert calls[1][0:2] == ["osascript", "-e"]
    assert "screen -r aistart-claude-1" in calls[1][2]
