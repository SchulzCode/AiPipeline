from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PipelineConfig:
    main_branch: str = "main"
    agent: str = "codex"
    auto_merge: bool = True
    merge_method: str = "squash"
    ci_timeout_seconds: int = 1800
    ci_registration_grace_seconds: int = 90
    command_timeout_seconds: int = 1200
    implementation_attempts: int = 3
    verification_attempts: int = 3
    review_attempts: int = 2
    ci_attempts: int = 2
    external_attempts: int = 3
    external_backoff_seconds: float = 2.0
    planner_attempts: int = 2
    planner_enabled: bool = True
    planner_context_classes: tuple[str, ...] = ("DEEP",)
    setup_commands: dict[str, str] = field(default_factory=dict)
    setup_auto: bool = True
    quality_commands: dict[str, str] = field(default_factory=dict)
    security_commands: dict[str, str] = field(default_factory=dict)
    discovery_max_candidates: int = 5
    discovery_max_new_issues: int = 5
    discovery_max_auto_implement: int = 0
    discovery_max_risk: str = "MEDIUM"
    discovery_max_context_class: str = "NORMAL"
    discovery_attempts: int = 2
    codex: dict[str, Any] = field(default_factory=dict)
    claude: dict[str, Any] = field(default_factory=dict)


def home_dir() -> Path:
    return Path(os.environ.get("AIPIPE_HOME", Path.home() / ".aipipeline")).expanduser().resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must be a mapping: {path}")
    return data


def merge_config_layers(*layers: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge raw YAML config documents, later layers winning per
    top-level key (nested dicts are merged one level deep)."""
    merged: dict[str, Any] = {}
    for layer in layers:
        for key, value in layer.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    return merged


def config_from_merged(merged: dict[str, Any]) -> PipelineConfig:
    """Build a PipelineConfig from an already-merged raw YAML document. This
    is the single source of truth for the YAML shape <-> dataclass field
    mapping; load_config() and any caller with an in-memory document (e.g.
    the control-plane project-settings API, which may not have a local
    checkout for GitHub-backed projects) both go through this function."""
    retries = merged.get("retries", {})
    setup = merged.get("setup", {})
    quality = merged.get("quality", {})
    security = merged.get("security", {})
    git = merged.get("git", {})
    planning = merged.get("planning", {})
    discovery = merged.get("discovery", {})
    return PipelineConfig(
        main_branch=merged.get("main_branch", "main"),
        agent=merged.get("agent", "codex"),
        auto_merge=git.get("auto_merge", merged.get("auto_merge", True)),
        merge_method=git.get("merge_method", merged.get("merge_method", "squash")),
        ci_timeout_seconds=int(merged.get("ci_timeout_seconds", 1800)),
        ci_registration_grace_seconds=int(merged.get("ci_registration_grace_seconds", 90)),
        command_timeout_seconds=int(merged.get("command_timeout_seconds", 1200)),
        implementation_attempts=int(retries.get("implementation", 3)),
        verification_attempts=int(retries.get("verification", 3)),
        review_attempts=int(retries.get("review", 2)),
        ci_attempts=int(retries.get("ci", 2)),
        external_attempts=int(retries.get("external", 3)),
        external_backoff_seconds=float(retries.get("external_backoff_seconds", 2.0)),
        planner_attempts=int(retries.get("planner", 2)),
        planner_enabled=bool(planning.get("enabled", True)),
        planner_context_classes=tuple(
            str(c).upper() for c in planning.get("context_classes", ["DEEP"])
        ),
        setup_commands=dict(setup.get("commands", {})),
        setup_auto=bool(setup.get("auto", True)),
        quality_commands=dict(quality.get("commands", {})),
        security_commands=dict(security.get("commands", {})),
        discovery_max_candidates=int(discovery.get("max_candidates", 5)),
        discovery_max_new_issues=int(discovery.get("max_new_issues", 5)),
        discovery_max_auto_implement=int(discovery.get("max_auto_implement", 0)),
        discovery_max_risk=str(discovery.get("max_risk", "MEDIUM")).upper(),
        discovery_max_context_class=str(discovery.get("max_context_class", "NORMAL")).upper(),
        discovery_attempts=int(discovery.get("attempts", 2)),
        codex=dict(merged.get("codex", {})),
        claude=dict(merged.get("claude", {})),
    )


def load_config(repo: Path | None = None) -> PipelineConfig:
    global_cfg = _load_yaml(home_dir() / "config" / "config.yml")
    project_cfg = _load_yaml(repo / ".ai" / "config.yml") if repo else {}
    return config_from_merged(merge_config_layers(global_cfg, project_cfg))
