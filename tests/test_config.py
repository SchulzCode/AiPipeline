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


def test_planner_config_defaults_to_deep_only_and_enabled(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("AIPIPE_HOME", str(home))
    cfg = load_config()
    assert cfg.planner_enabled is True
    assert cfg.planner_context_classes == ("DEEP",)
    assert cfg.planner_attempts == 2


def test_project_config_can_widen_or_disable_planner_threshold(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "config.yml").write_text(
        "planning:\n  enabled: true\n  context_classes: [NORMAL, DEEP]\nretries:\n  planner: 1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIPIPE_HOME", str(home))
    cfg = load_config(repo)
    assert cfg.planner_context_classes == ("NORMAL", "DEEP")
    assert cfg.planner_attempts == 1

    (repo / ".ai" / "config.yml").write_text("planning:\n  enabled: false\n", encoding="utf-8")
    cfg = load_config(repo)
    assert cfg.planner_enabled is False
