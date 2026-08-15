from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from .config import home_dir, load_config
from .knowledge import init_project_knowledge


def initialize_global(force: bool = False) -> Path:
    root = home_dir()
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "global").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "worktrees").mkdir(parents=True, exist_ok=True)
    template_root = files("aipipe.templates")
    for name in ["AGENT.md", "WORKFLOW.md", "SECURITY.md", "QUALITY.md", "LEARNINGS.md"]:
        target = root / "global" / name
        if force or not target.exists():
            target.write_text((template_root / "global" / name).read_text(encoding="utf-8"), encoding="utf-8")
    cfg = root / "config" / "config.yml"
    if force or not cfg.exists():
        cfg.write_text((template_root / "global" / "config.yml").read_text(encoding="utf-8"), encoding="utf-8")
    return root


def initialize_project(repo: Path) -> None:
    cfg = load_config(repo)
    init_project_knowledge(repo, main_branch=cfg.main_branch, agent=cfg.agent, auto_merge=cfg.auto_merge, merge_method=cfg.merge_method)
