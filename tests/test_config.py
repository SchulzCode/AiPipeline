from pathlib import Path

import pytest

from aipipe.config import load_config
from aipipe.models import FailureCategory
from aipipe.orchestrator import Orchestrator, PipelineBlocked


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


def test_discovery_config_defaults_are_safe(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("AIPIPE_HOME", str(home))
    cfg = load_config()
    assert cfg.discovery_max_candidates == 5
    assert cfg.discovery_max_new_issues == 5
    assert cfg.discovery_max_auto_implement == 0  # safe default
    assert cfg.discovery_max_risk == "MEDIUM"
    assert cfg.discovery_max_context_class == "NORMAL"
    assert cfg.discovery_attempts == 2


def test_discovery_config_can_be_overridden_per_project(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "config.yml").write_text(
        "discovery:\n"
        "  max_candidates: 8\n"
        "  max_new_issues: 3\n"
        "  max_auto_implement: 1\n"
        "  max_risk: HIGH\n"
        "  max_context_class: DEEP\n"
        "  attempts: 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIPIPE_HOME", str(home))
    cfg = load_config(repo)
    assert cfg.discovery_max_candidates == 8
    assert cfg.discovery_max_new_issues == 3
    assert cfg.discovery_max_auto_implement == 1
    assert cfg.discovery_max_risk == "HIGH"
    assert cfg.discovery_max_context_class == "DEEP"
    assert cfg.discovery_attempts == 4


def _validate(overrides):
    from types import SimpleNamespace

    orch = Orchestrator.__new__(Orchestrator)
    base = dict(
        merge_method="squash",
        implementation_attempts=3,
        verification_attempts=3,
        review_attempts=2,
        ci_attempts=2,
        external_attempts=3,
        ci_timeout_seconds=1800,
        ci_registration_grace_seconds=90,
        planner_attempts=2,
        planner_context_classes=("DEEP",),
        setup_commands={},
        quality_commands={},
        security_commands={},
        discovery_max_candidates=5,
        discovery_max_new_issues=5,
        discovery_max_auto_implement=0,
        discovery_max_risk="MEDIUM",
        discovery_max_context_class="NORMAL",
        discovery_attempts=2,
    )
    base.update(overrides)
    orch.config = SimpleNamespace(**base)
    orch._validate_config()


def test_validate_config_accepts_safe_defaults():
    _validate({})  # must not raise


def test_validate_config_rejects_zero_max_candidates():
    with pytest.raises(PipelineBlocked) as exc:
        _validate({"discovery_max_candidates": 0})
    assert exc.value.category == FailureCategory.CONFIGURATION


def test_validate_config_rejects_new_issues_above_max_candidates():
    with pytest.raises(PipelineBlocked) as exc:
        _validate({"discovery_max_candidates": 3, "discovery_max_new_issues": 4})
    assert exc.value.category == FailureCategory.CONFIGURATION


def test_validate_config_rejects_auto_implement_above_max_new_issues():
    with pytest.raises(PipelineBlocked) as exc:
        _validate({"discovery_max_new_issues": 2, "discovery_max_auto_implement": 3})
    assert exc.value.category == FailureCategory.CONFIGURATION


def test_validate_config_rejects_invalid_max_risk():
    with pytest.raises(PipelineBlocked) as exc:
        _validate({"discovery_max_risk": "EXTREME"})
    assert exc.value.category == FailureCategory.CONFIGURATION


def test_validate_config_rejects_invalid_max_context_class():
    with pytest.raises(PipelineBlocked) as exc:
        _validate({"discovery_max_context_class": "HUGE"})
    assert exc.value.category == FailureCategory.CONFIGURATION


def test_validate_config_rejects_zero_discovery_attempts():
    with pytest.raises(PipelineBlocked) as exc:
        _validate({"discovery_attempts": 0})
    assert exc.value.category == FailureCategory.CONFIGURATION
