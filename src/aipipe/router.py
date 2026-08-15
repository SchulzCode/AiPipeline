from __future__ import annotations

import re

from .models import ContextClass, Risk, Route, TaskType


HIGH = {
    "auth", "authentication", "authorization", "oauth", "password", "permission", "admin",
    "payment", "billing", "crypto", "cryptography", "secret", "token", "credential",
    "private key", "personal data", "pii", "upload", "infrastructure", "production"
}
MEDIUM = {
    "api", "database", "migration", "filesystem", "file system", "dependency", "queue",
    "worker", "background job", "webhook", "serialization", "cache", "state", "email"
}
DEEP = {"rewrite", "architecture", "entire", "whole", "cross-cutting", "migration", "redesign", "refactor all"}


def _has(text: str, words: set[str]) -> list[str]:
    return sorted({w for w in words if w in text})


def route_task(text: str, labels: list[str] | None = None) -> Route:
    lower = " ".join([text, *(labels or [])]).lower()
    if any(w in lower for w in ["security", "vulnerability", "cve", "xss", "csrf", "injection"]):
        task_type = TaskType.SECURITY
    elif any(w in lower for w in ["docs", "documentation", "readme", "typo"]):
        task_type = TaskType.DOCS
    elif any(w in lower for w in ["bug", "fix", "broken", "crash", "fails", "failure"]):
        task_type = TaskType.BUG
    elif any(w in lower for w in ["refactor", "cleanup", "restructure"]):
        task_type = TaskType.REFACTOR
    elif any(w in lower for w in ["performance", "slow", "latency", "optimize"]):
        task_type = TaskType.PERFORMANCE
    elif any(w in lower for w in ["test", "coverage"]):
        task_type = TaskType.TEST
    elif any(w in lower for w in ["investigate", "research", "analyze", "analyse"]):
        task_type = TaskType.INVESTIGATION
    elif any(w in lower for w in ["upgrade", "update dependency", "maintenance", "chore"]):
        task_type = TaskType.MAINTENANCE
    else:
        task_type = TaskType.FEATURE

    high_hits = _has(lower, HIGH)
    med_hits = _has(lower, MEDIUM)
    if task_type == TaskType.SECURITY or high_hits:
        risk = Risk.HIGH
    elif med_hits or task_type in {TaskType.FEATURE, TaskType.BUG, TaskType.PERFORMANCE, TaskType.MAINTENANCE}:
        risk = Risk.MEDIUM
    else:
        risk = Risk.LOW

    if _has(lower, DEEP) or len(lower) > 1800:
        context = ContextClass.DEEP
    elif risk == Risk.LOW and len(lower) < 300:
        context = ContextClass.SMALL
    else:
        context = ContextClass.NORMAL

    scopes = high_hits + med_hits
    generic_scopes = {
        "frontend": ["frontend", "ui", "css", "react", "vue", "button"],
        "backend": ["backend", "server"],
        "testing": ["test", "coverage"],
        "docs": ["docs", "documentation", "readme"],
    }
    for scope, terms in generic_scopes.items():
        if any(t in lower for t in terms):
            scopes.append(scope)
    scopes = sorted(set(scopes)) or ["general"]

    gates = ["targeted_tests", "diff_review", "ci"]
    if risk in {Risk.MEDIUM, Risk.HIGH}:
        gates += ["quality", "security_sanity", "review"]
    if risk == Risk.HIGH:
        gates += ["security_review", "full_tests"]
    return Route(task_type, risk, context, scopes, list(dict.fromkeys(gates)))


def planner_required(context_class: ContextClass | str, config) -> bool:
    """Decide whether the Planner stage should run for a routed task.

    Kept independent of Risk: an architecturally complex but low-risk task
    can still benefit from planning, while a high-risk small change may need
    security review without needing a Planner. Gated purely on the routed
    ContextClass and the project's configured threshold, so it stays cheap
    (no LLM call) and unit-testable without a real PipelineConfig.
    """
    if not getattr(config, "planner_enabled", True):
        return False
    allowed = {str(c).upper() for c in getattr(config, "planner_context_classes", ("DEEP",))}
    return str(context_class).upper() in allowed


def acceptance_from_text(text: str) -> list[str]:
    lines = [re.sub(r"^[-*\d.\s]+", "", line).strip() for line in text.splitlines()]
    explicit = [l for l in lines if l and any(k in l.lower() for k in ["must ", "should ", "accept", "expected", "when "])]
    return explicit[:8] or ["Requested behavior is implemented without unrelated regressions."]
