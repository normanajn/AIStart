from aistart.agents import resolve_agents
from aistart.config import load_config


def test_resolve_agents_uses_configured_command(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"agents":{"antigravity":{"command":"ag","args":["--project"],"enabled":true}}}\n'
    )
    monkeypatch.setattr("shutil.which", lambda cmd: f"/bin/{cmd}" if cmd != "missing" else None)

    runtimes = resolve_agents(load_config(config_path))

    assert runtimes["antigravity"].command == "ag"
    assert runtimes["antigravity"].args == ["--project"]
    assert runtimes["antigravity"].command_path == "/bin/ag"


def test_codex_argv_includes_cwd_flag(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda cmd: f"/bin/{cmd}")
    runtime = resolve_agents(load_config(tmp_path / "missing.json"))["codex"]

    assert runtime.argv(tmp_path) == ["codex", "--cd", str(tmp_path)]
