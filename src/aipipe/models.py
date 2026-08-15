from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    ROUTING = "ROUTING"
    PREPARING = "PREPARING"
    DISCOVERY = "DISCOVERY"
    DISCOVERING = "DISCOVERING"
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
    DISCOVERY = "DISCOVERY"


class Risk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContextClass(StrEnum):
    SMALL = "SMALL"
    NORMAL = "NORMAL"
    DEEP = "DEEP"


class FailureCategory(StrEnum):
    TRANSIENT_EXTERNAL = "TRANSIENT_EXTERNAL"
    CONFIGURATION = "CONFIGURATION"
    ENVIRONMENT = "ENVIRONMENT"
    AGENT_PROTOCOL = "AGENT_PROTOCOL"
    QUALITY_FAILURE = "QUALITY_FAILURE"
    SECURITY_FAILURE = "SECURITY_FAILURE"
    REVIEW_FAILURE = "REVIEW_FAILURE"
    PLANNING_FAILURE = "PLANNING_FAILURE"
    STATE_INCONSISTENCY = "STATE_INCONSISTENCY"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    REMOTE_STATE_MISMATCH = "REMOTE_STATE_MISMATCH"
    TERMINAL_INTERNAL = "TERMINAL_INTERNAL"


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
