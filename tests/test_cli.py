import json

from aistart import cli


def test_agents_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AISTART_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setattr("shutil.which", lambda cmd: f"/bin/{cmd}" if cmd != "agy" else None)

    assert cli.main(["agents", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["claude"]["installed"] is True
    assert data["antigravity"]["installed"] is False


def test_start_requires_agent(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AISTART_CONFIG", str(tmp_path / "missing.json"))

    assert cli.main(["start", "--env", "tmux"]) == 2

    captured = capsys.readouterr()
    assert "select at least one agent" in captured.err


def test_config_show_prints_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AISTART_CONFIG", str(tmp_path / "missing.json"))

    assert cli.main(["config", "--show"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["default_env"] == "terminal-tab"


def test_theme_option_passes_initial_tui_theme(monkeypatch):
    seen = {}

    def fake_run_tui(theme="dark"):
        seen["theme"] = theme
        return 0

    monkeypatch.setattr("aistart.tui.run_tui", fake_run_tui)

    assert cli.main(["--theme", "light"]) == 0
    assert seen["theme"] == "light"


def test_theme_option_rejects_unknown_theme():
    try:
        cli.main(["--theme", "blue"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
