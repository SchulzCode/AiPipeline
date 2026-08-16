from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .context_budget import budget_for
from .models import TaskContract
from .repo_index import RepoIndexCache, render_repo_index
from .util import truncate

TRUNCATION_NOTICE = (
    "# Context Truncation Notice\n"
    "Some optional context below (repository index, project knowledge, prior "
    "decisions/learnings, diffs, and/or logs) was shortened or omitted to fit "
    "this run's context budget. The task goal, acceptance criteria, "
    "out-of-scope constraints, and safety/quality rules above are complete "
    "and were never truncated. Use your file-inspection tools to read, grep, "
    "or glob the worktree directly for anything you need beyond what is "
    "shown here."
)


@dataclass
class _Section:
    text: str
    protected: bool
    # Lower drop_priority sections are truncated/dropped first when the
    # assembled context exceeds its total budget. Ignored for protected
    # sections, which are never touched.
    drop_priority: int = 0


class ContextBuilder:
    def __init__(self, global_root: Path, index_cache: RepoIndexCache | None = None):
        self.global_root = global_root
        self.index_cache = index_cache

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

    def build(
        self,
        repo: Path,
        task: TaskContract,
        role: str,
        diff: str = "",
        findings: str = "",
        plan: str = "",
        *,
        budget_role: str | None = None,
    ) -> str:
        scopes = task.route.scopes if task.route else ["general"]
        sections: list[_Section] = [
            _Section(f"# Role\n{role}\n", protected=True),
            _Section(f"# Task\nID: {task.id}\nGoal: {truncate(task.goal, 16000)}\n", protected=True),
            _Section(
                "# Acceptance Criteria\n" + "\n".join(f"- {x}" for x in task.acceptance_criteria),
                protected=True,
            ),
        ]
        if task.out_of_scope:
            sections.append(
                _Section(
                    "# Out of Scope\n" + "\n".join(f"- {x}" for x in task.out_of_scope),
                    protected=True,
                )
            )
        if plan:
            sections.append(_Section("# Implementation Plan\n" + truncate(plan, 10000), protected=True))
        agent_rules = self._read(self.global_root / "AGENT.md", 5000)
        project = self._read(repo / ".ai" / "PROJECT.md", 8000)
        if agent_rules:
            sections.append(_Section("# Global Agent Rules\n" + agent_rules, protected=True))
        if project:
            sections.append(_Section("# Project Context\n" + project, protected=False, drop_priority=2))
        if self.index_cache is not None:
            index = self.index_cache.get_or_build(repo)
            if index is not None:
                rendered = render_repo_index(index)
                if rendered:
                    sections.append(
                        _Section("# Repository Index\n" + rendered, protected=False, drop_priority=1)
                    )
        decisions = self._relevant_entries(repo / ".ai" / "DECISIONS.md", scopes)
        learnings = self._relevant_entries(repo / ".ai" / "LEARNINGS.md", scopes)
        global_learnings = self._relevant_entries(self.global_root / "LEARNINGS.md", scopes, 4000)
        if decisions:
            sections.append(_Section("# Relevant Decisions\n" + decisions, protected=False, drop_priority=0))
        if learnings or global_learnings:
            sections.append(
                _Section(
                    "# Relevant Learnings\n" + "\n".join(x for x in [learnings, global_learnings] if x),
                    protected=False,
                    drop_priority=0,
                )
            )
        if task.route and task.route.risk.value in {"MEDIUM", "HIGH"}:
            security = self._read(self.global_root / "SECURITY.md", 8000)
            if security:
                sections.append(_Section("# Security Rules\n" + security, protected=True))
        if diff:
            sections.append(
                _Section(
                    "# Current Diff\n```diff\n" + truncate(diff, 18000) + "\n```",
                    protected=False,
                    drop_priority=4,
                )
            )
        if findings:
            sections.append(
                _Section("# Findings To Address\n" + truncate(findings, 8000), protected=False, drop_priority=3)
            )

        budget = budget_for(budget_role or role, task.route.context_class if task.route else None)
        truncated = self._enforce_budget(sections, budget.total_chars)

        parts = [s.text for s in sections if s.text]
        if truncated:
            parts.append(TRUNCATION_NOTICE)
        return "\n\n".join(parts)

    @staticmethod
    def _enforce_budget(sections: list[_Section], total_chars: int) -> bool:
        def assembled_len() -> int:
            texts = [s.text for s in sections if s.text]
            if not texts:
                return 0
            return sum(len(t) for t in texts) + 2 * (len(texts) - 1)

        excess = assembled_len() - total_chars
        if excess <= 0:
            return False

        optional_indices = sorted(
            (i for i, s in enumerate(sections) if not s.protected),
            key=lambda i: sections[i].drop_priority,
        )
        truncated_any = False
        for i in optional_indices:
            if excess <= 0:
                break
            section = sections[i]
            text_len = len(section.text)
            if text_len == 0:
                continue
            if text_len <= excess:
                excess -= text_len
                section.text = ""
                truncated_any = True
                continue
            new_limit = max(0, text_len - excess)
            section.text = truncate(section.text, new_limit) if new_limit > 0 else ""
            excess = 0
            truncated_any = True
        return truncated_any
