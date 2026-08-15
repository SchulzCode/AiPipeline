from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..config import PipelineConfig, config_from_merged, home_dir, merge_config_layers
from .config import ControlSettings
from .github_app import GitHubAppAuth
from .models import Project

CONFIG_REL_PATH = ".ai/config.yml"

# Maps a flat PipelineConfig/ProjectConfigPatch field name to the nested
# key path used in .ai/config.yml, mirroring aipipe.config.load_config's
# YAML -> dataclass mapping in reverse.
_PATCH_TO_YAML_PATH: dict[str, tuple[str, ...]] = {
    "main_branch": ("main_branch",),
    "agent": ("agent",),
    "auto_merge": ("git", "auto_merge"),
    "merge_method": ("git", "merge_method"),
    "ci_timeout_seconds": ("ci_timeout_seconds",),
    "ci_registration_grace_seconds": ("ci_registration_grace_seconds",),
    "command_timeout_seconds": ("command_timeout_seconds",),
    "implementation_attempts": ("retries", "implementation"),
    "verification_attempts": ("retries", "verification"),
    "review_attempts": ("retries", "review"),
    "ci_attempts": ("retries", "ci"),
    "external_attempts": ("retries", "external"),
    "external_backoff_seconds": ("retries", "external_backoff_seconds"),
    "planner_attempts": ("retries", "planner"),
    "planner_enabled": ("planning", "enabled"),
    "planner_context_classes": ("planning", "context_classes"),
    "setup_auto": ("setup", "auto"),
    "setup_commands": ("setup", "commands"),
    "quality_commands": ("quality", "commands"),
    "security_commands": ("security", "commands"),
    "discovery_max_candidates": ("discovery", "max_candidates"),
    "discovery_max_new_issues": ("discovery", "max_new_issues"),
    "discovery_max_auto_implement": ("discovery", "max_auto_implement"),
    "discovery_max_risk": ("discovery", "max_risk"),
    "discovery_max_context_class": ("discovery", "max_context_class"),
    "discovery_attempts": ("discovery", "attempts"),
}


def config_to_dict(cfg: PipelineConfig) -> dict[str, Any]:
    return {
        "main_branch": cfg.main_branch,
        "agent": cfg.agent,
        "auto_merge": cfg.auto_merge,
        "merge_method": cfg.merge_method,
        "ci_timeout_seconds": cfg.ci_timeout_seconds,
        "ci_registration_grace_seconds": cfg.ci_registration_grace_seconds,
        "command_timeout_seconds": cfg.command_timeout_seconds,
        "implementation_attempts": cfg.implementation_attempts,
        "verification_attempts": cfg.verification_attempts,
        "review_attempts": cfg.review_attempts,
        "ci_attempts": cfg.ci_attempts,
        "external_attempts": cfg.external_attempts,
        "external_backoff_seconds": cfg.external_backoff_seconds,
        "planner_attempts": cfg.planner_attempts,
        "planner_enabled": cfg.planner_enabled,
        "planner_context_classes": list(cfg.planner_context_classes),
        "setup_commands": dict(cfg.setup_commands),
        "setup_auto": cfg.setup_auto,
        "quality_commands": dict(cfg.quality_commands),
        "security_commands": dict(cfg.security_commands),
        "discovery_max_candidates": cfg.discovery_max_candidates,
        "discovery_max_new_issues": cfg.discovery_max_new_issues,
        "discovery_max_auto_implement": cfg.discovery_max_auto_implement,
        "discovery_max_risk": cfg.discovery_max_risk,
        "discovery_max_context_class": cfg.discovery_max_context_class,
        "discovery_attempts": cfg.discovery_attempts,
    }


def _set_nested(doc: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = doc
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def apply_patch_to_yaml(doc: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a flat field-name patch into a raw .ai/config.yml document,
    preserving every key the patch does not touch."""
    merged = dict(doc)
    for field_name, value in patch.items():
        if value is None:
            continue
        path = _PATCH_TO_YAML_PATH.get(field_name)
        if path is None:
            continue
        _set_nested(merged, path, value)
    return merged


class ProjectConfigError(RuntimeError):
    """Raised when a project's .ai/config.yml cannot be read or written."""


def read_project_config(project: Project, settings: ControlSettings) -> tuple[str, dict[str, Any], str | None]:
    """Read the raw .ai/config.yml document for a project.

    Returns (source, raw_document, warning). source is "local", "github", or
    "unavailable" (no local path and no GitHub repository configured).
    """
    if project.local_path:
        path = Path(project.local_path).expanduser().resolve() / CONFIG_REL_PATH
        if not path.exists():
            return "local", {}, None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return "local", {}, "Existing .ai/config.yml could not be parsed; showing defaults."
        return "local", data if isinstance(data, dict) else {}, None

    if project.repository_full_name and project.installation_id:
        auth = GitHubAppAuth(settings, project.installation_id)
        try:
            fetched = auth.get_contents(project.repository_full_name, CONFIG_REL_PATH, ref=project.default_branch)
        except Exception as exc:  # pragma: no cover - network/GitHub failures
            raise ProjectConfigError(f"Could not read .ai/config.yml from GitHub: {exc}") from exc
        if fetched is None:
            return "github", {}, None
        content, _sha = fetched
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            return "github", {}, "Existing .ai/config.yml could not be parsed; showing defaults."
        return "github", data if isinstance(data, dict) else {}, None

    return "unavailable", {}, "This project has no local path or GitHub repository to read configuration from."


def write_project_config(project: Project, settings: ControlSettings, doc: dict[str, Any]) -> None:
    """Write a raw .ai/config.yml document back to its source. GitHub-backed
    projects are committed directly to the project's default branch (no PR)."""
    yaml_text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)

    if project.local_path:
        path = Path(project.local_path).expanduser().resolve() / CONFIG_REL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml_text, encoding="utf-8")
        return

    if project.repository_full_name and project.installation_id:
        auth = GitHubAppAuth(settings, project.installation_id)
        try:
            existing = auth.get_contents(project.repository_full_name, CONFIG_REL_PATH, ref=project.default_branch)
            sha = existing[1] if existing else None
            auth.put_contents(
                project.repository_full_name,
                CONFIG_REL_PATH,
                yaml_text,
                message="chore: update AIpipe pipeline configuration",
                branch=project.default_branch,
                sha=sha,
            )
        except Exception as exc:  # pragma: no cover - network/GitHub failures
            raise ProjectConfigError(f"Could not write .ai/config.yml to GitHub: {exc}") from exc
        return

    raise ProjectConfigError("This project has no local path or GitHub repository to write configuration to.")


def resolved_config(raw_doc: dict[str, Any]) -> PipelineConfig:
    """Merge the AIpipe-home global config with a project's raw .ai/config.yml
    document, going through the canonical PipelineConfig mapping — this is
    the same effective config the pipeline itself would resolve for the
    project, without requiring a local checkout."""
    global_path = home_dir() / "config" / "config.yml"
    global_cfg: dict[str, Any] = {}
    if global_path.exists():
        try:
            loaded = yaml.safe_load(global_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                global_cfg = loaded
        except yaml.YAMLError:
            global_cfg = {}
    return config_from_merged(merge_config_layers(global_cfg, raw_doc))
