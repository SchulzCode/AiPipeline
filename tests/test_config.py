from pathlib import Path

from aipipe.config import load_config


def test_project_config_overrides_global(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "config.yml").write_text("agent: codex\nretries:\n  ci: 2\n", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "config.yml").write_text("agent: claude\nretries:\n  ci: 4\n", encoding="utf-8")
    monkeypatch.setenv("AIPIPE_HOME", str(home))
    cfg = load_config(repo)
    assert cfg.agent == "claude"
    assert cfg.ci_attempts == 4
