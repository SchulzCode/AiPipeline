from __future__ import annotations

import json
from pathlib import Path


def infer_project_summary(repo: Path) -> str:
    stack: list[str] = []
    build: list[str] = []
    if (repo / "package.json").exists():
        stack.append("Node.js / JavaScript or TypeScript")
        try:
            pkg = json.loads((repo / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if scripts:
                build.append("package.json scripts: " + ", ".join(sorted(scripts)[:12]))
        except Exception:
            pass
    if (repo / "pyproject.toml").exists():
        stack.append("Python (pyproject.toml)")
    if (repo / "Cargo.toml").exists():
        stack.append("Rust / Cargo")
    if (repo / "go.mod").exists():
        stack.append("Go modules")
    if (repo / "pom.xml").exists():
        stack.append("Java / Maven")
    if (repo / "gradlew").exists() or (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        stack.append("Gradle")
    top_dirs = sorted(p.name for p in repo.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in {"node_modules", "vendor", "venv", ".venv"})[:16]
    ci = "GitHub Actions present" if (repo / ".github" / "workflows").exists() else "No GitHub Actions directory detected at initialization"
    return (
        "# Project\n\n"
        "## Purpose\n"
        "To be refined from repository evidence when durable project context is learned.\n\n"
        "## Stack\n"
        + ("\n".join(f"- {x}" for x in stack) if stack else "- Not inferred from top-level manifests")
        + "\n\n## Architecture\n"
        + ("Top-level directories: " + ", ".join(top_dirs) if top_dirs else "No non-hidden top-level directories detected")
        + "\n\n## Testing and Build\n"
        + ("\n".join(f"- {x}" for x in build) if build else "- Use project configuration/autodetection until refined")
        + f"\n- {ci}\n\n## Constraints\n- Add only durable, non-obvious constraints here.\n"
    )


def init_project_knowledge(repo: Path, *, main_branch: str = "main", agent: str = "codex",
                           auto_merge: bool = True, merge_method: str = "squash") -> None:
    ai = repo / ".ai"
    ai.mkdir(exist_ok=True)
    defaults = {
        "PROJECT.md": infer_project_summary(repo),
        "DECISIONS.md": "# Decisions\n\n<!-- Active decisions only are retrieved by default. -->\n",
        "LEARNINGS.md": "# Project Learnings\n\n<!-- Store only reusable future-facing knowledge. -->\n",
        "config.yml": (
            f"main_branch: {main_branch}\nagent: {agent}\n\n"
            f"git:\n  auto_merge: {'true' if auto_merge else 'false'}\n  merge_method: {merge_method}\n\n"
            "quality:\n  commands: {}\n\nsecurity:\n  commands: {}\n"
        ),
    }
    for name, content in defaults.items():
        p = ai / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
