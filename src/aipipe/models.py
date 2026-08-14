from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    ROUTING = "ROUTING"
    PREPARING = "PREPARING"
    DISCOVERY = "DISCOVERY"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    REVIEWING = "REVIEWING"
    PR_OPEN = "PR_OPEN"
    CI = "CI"
    MERGING = "MERGING"
    POST_MERGE = "POST_MERGE"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskType(StrEnum):
    FEATURE = "FEATURE"
    BUG = "BUG"
    REFACTOR = "REFACTOR"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    TEST = "TEST"
    DOCS = "DOCS"
    INVESTIGATION = "INVESTIGATION"
    MAINTENANCE = "MAINTENANCE"


class Risk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContextClass(StrEnum):
    SMALL = "SMALL"
    NORMAL = "NORMAL"
    DEEP = "DEEP"


@dataclass
class Route:
    task_type: TaskType
    risk: Risk
    context_class: ContextClass
    scopes: list[str] = field(default_factory=list)
    gates: list[str] = field(default_factory=list)


@dataclass
class TaskContract:
    id: str
    goal: str
    source: str = "prompt"
    source_reference: str | None = None
    title: str | None = None
    body: str | None = None
    acceptance_criteria: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    route: Route | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
