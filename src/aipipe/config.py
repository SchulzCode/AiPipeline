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


def load_config(repo: Path | None = None) -> PipelineConfig:
    merged: dict[str, Any] = {}
    global_cfg = _load_yaml(home_dir() / "config" / "config.yml")
    merged.update(global_cfg)
    if repo:
        project_cfg = _load_yaml(repo / ".ai" / "config.yml")
        for key, value in project_cfg.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value

    retries = merged.get("retries", {})
    setup = merged.get("setup", {})
    quality = merged.get("quality", {})
    security = merged.get("security", {})
    git = merged.get("git", {})
    planning = merged.get("planning", {})
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
        codex=dict(merged.get("codex", {})),
        claude=dict(merged.get("claude", {})),
    )
