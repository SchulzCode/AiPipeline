from __future__ import annotations

import re
from pathlib import Path

from .models import TaskContract
from .util import truncate


class ContextBuilder:
    def __init__(self, global_root: Path):
        self.global_root = global_root

    @staticmethod
    def _read(path: Path, limit: int = 10000) -> str:
        if not path.exists():
            return ""
        return truncate(path.read_text(encoding="utf-8", errors="replace"), limit)

    @staticmethod
    def _relevant_entries(path: Path, scopes: list[str], limit: int = 7000) -> str:
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks = re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)
        needles = [s.lower() for s in scopes]
        active = []
        for c in chunks:
            lc = c.lower()
            if "status: obsolete" in lc or "status: superseded" in lc:
                continue
            if any(n in lc for n in needles):
                active.append(c.strip())
        return truncate("\n\n".join(active), limit)

    def build(self, repo: Path, task: TaskContract, role: str, diff: str = "", findings: str = "") -> str:
        scopes = task.route.scopes if task.route else ["general"]
        parts = [
            f"# Role\n{role}\n",
            f"# Task\nID: {task.id}\nGoal: {truncate(task.goal, 16000)}\n",
            "# Acceptance Criteria\n" + "\n".join(f"- {x}" for x in task.acceptance_criteria),
        ]
        agent_rules = self._read(self.global_root / "AGENT.md", 5000)
        project = self._read(repo / ".ai" / "PROJECT.md", 8000)
        if agent_rules:
            parts.append("# Global Agent Rules\n" + agent_rules)
        if project:
            parts.append("# Project Context\n" + project)
        decisions = self._relevant_entries(repo / ".ai" / "DECISIONS.md", scopes)
        learnings = self._relevant_entries(repo / ".ai" / "LEARNINGS.md", scopes)
        global_learnings = self._relevant_entries(self.global_root / "LEARNINGS.md", scopes, 4000)
        if decisions:
            parts.append("# Relevant Decisions\n" + decisions)
        if learnings or global_learnings:
            parts.append("# Relevant Learnings\n" + "\n".join(x for x in [learnings, global_learnings] if x))
        if task.route and task.route.risk.value in {"MEDIUM", "HIGH"}:
            security = self._read(self.global_root / "SECURITY.md", 8000)
            if security:
                parts.append("# Security Rules\n" + security)
        if diff:
            parts.append("# Current Diff\n```diff\n" + truncate(diff, 18000) + "\n```")
        if findings:
            parts.append("# Findings To Address\n" + truncate(findings, 8000))
        return "\n\n".join(parts)
