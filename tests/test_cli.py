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
