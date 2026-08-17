from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..agents import agent_models


AgentName = Literal["codex", "claude", "qwen"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: str
    login: str
    avatar_url: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    repository_full_name: str | None = None
    repository_url: str | None = None
    local_path: str | None = None
    installation_id: int | None = None
    default_branch: str = "main"
    agent: AgentName = "codex"
    model: str | None = None

    @model_validator(mode="after")
    def source_present(self):
        if not self.local_path and not self.repository_full_name and not self.repository_url:
            raise ValueError("Provide local_path or a GitHub repository")
        if self.repository_full_name and not self.repository_url:
            self.repository_url = f"https://github.com/{self.repository_full_name}.git"
        return self

    @model_validator(mode="after")
    def model_matches_agent(self):
        if self.model is None:
            return self
        valid_ids = {m.id for m in agent_models(self.agent) if m.id}
        if self.model not in valid_ids:
            raise ValueError(f"Model '{self.model}' is not available for agent '{self.agent}'")
        return self


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    agent: AgentName | None = None
    model: str | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def model_matches_agent(self):
        if self.model is None or self.agent is None:
            return self
        valid_ids = {m.id for m in agent_models(self.agent) if m.id}
        if self.model not in valid_ids:
            raise ValueError(f"Model '{self.model}' is not available for agent '{self.agent}'")
        return self


class ProjectOut(ORMModel):
    id: str
    name: str
    repository_full_name: str | None
    repository_url: str | None
    local_path: str | None
    installation_id: int | None
    default_branch: str
    agent: str
    model: str | None = None
    enabled: bool
    status: str
    created_at: datetime


class TaskCreate(BaseModel):
    prompt: str = Field(min_length=2, max_length=50000)


class IssueTaskCreate(BaseModel):
    issue_number: int = Field(gt=0)


class DiscoveryTaskCreate(BaseModel):
    prompt: str | None = Field(default=None, max_length=50000)


class TaskOut(ORMModel):
    id: str
    project_id: str
    source: str
    source_reference: str | None
    title: str | None
    prompt: str
    status: str
    risk: str | None
    context_class: str | None
    core_task_id: str | None
    discovery_task_id: str | None = None
    branch: str | None
    pr_number: int | None
    error: str | None
    failure_category: str | None = None
    worker_build: str | None = None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TaskWithProjectOut(TaskOut):
    project_name: str
    project_agent: str
    project_model: str | None = None


class EventOut(ORMModel):
    id: int
    task_id: str
    kind: str
    detail: str | None
    created_at: datetime


class IssueOut(BaseModel):
    number: int
    title: str
    state: str
    url: str
    labels: list[str] = []


class ActivityItemOut(BaseModel):
    category: str
    title: str
    summary: str
    result: str | None = None
    next_step: str | None = None
    status: str
    timestamp: datetime
    duration_seconds: float | None = None
    technical_event_id: int | None = None


class CurrentActivityOut(BaseModel):
    title: str
    summary: str
    phase: str
    started_at: datetime
    next_step: str | None = None
    agent_label: str


class BlockerOut(BaseModel):
    reason: str
    last_phase: str | None = None
    category: str | None = None


class CheckStatusOut(BaseModel):
    type: str
    name: str
    status: str
    updated_at: datetime


class ReviewSummaryOut(BaseModel):
    status: str
    result: str
    updated_at: datetime


class CiSummaryOut(BaseModel):
    total: int
    passed: int
    failed: int


class PlanSummaryOut(BaseModel):
    status: str
    plan: str
    updated_at: datetime


class ChecksSummaryOut(BaseModel):
    checks: list[CheckStatusOut] = []
    review: ReviewSummaryOut | None = None
    security_review: ReviewSummaryOut | None = None
    ci: CiSummaryOut | None = None
    plan: PlanSummaryOut | None = None


class ActivityFeedOut(BaseModel):
    items: list[ActivityItemOut]
    current: CurrentActivityOut | None = None
    blocker: BlockerOut | None = None
    checks: ChecksSummaryOut


class FeatureCandidateOut(BaseModel):
    key: str
    title: str
    summary: str
    rationale: str = ""
    acceptance_criteria: list[str] = []
    task_type: str
    risk: str
    context_class: str
    labels: list[str] = []
    score: float
    rank: int | None = None
    status: str
    duplicate_of: str | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    error: str | None = None
    handoff: bool = False


class DiscoverySummaryOut(BaseModel):
    status: str
    candidates: list[FeatureCandidateOut] = []
    created: list[str] = []
    duplicates: list[str] = []
    failed: list[str] = []
    handoff_issue_numbers: list[int] = []
    updated_at: datetime | None = None


class SystemHealthOut(BaseModel):
    projects_total: int
    projects_by_status: dict[str, int] = {}
    tasks_by_status: dict[str, int] = {}
    active_tasks: int
    active_workers: int
    stale_tasks: int
    worker_stale_seconds: float
    dev_auth: bool
    github_app_configured: bool
    github_login_configured: bool
    database: str


class ProjectPipelineConfigOut(BaseModel):
    main_branch: str
    agent: str
    auto_merge: bool
    merge_method: str
    ci_timeout_seconds: int
    ci_registration_grace_seconds: int
    command_timeout_seconds: int
    implementation_attempts: int
    verification_attempts: int
    review_attempts: int
    ci_attempts: int
    external_attempts: int
    external_backoff_seconds: float
    planner_attempts: int
    planner_enabled: bool
    planner_context_classes: list[str]
    setup_commands: dict[str, str] = {}
    setup_auto: bool
    quality_commands: dict[str, str] = {}
    security_commands: dict[str, str] = {}
    discovery_max_candidates: int
    discovery_max_new_issues: int
    discovery_max_auto_implement: int
    discovery_max_risk: str
    discovery_max_context_class: str
    discovery_attempts: int


class ProjectConfigOut(BaseModel):
    source: Literal["local", "github", "unavailable"]
    editable: bool
    config: ProjectPipelineConfigOut
    warning: str | None = None


class ProjectConfigPatch(BaseModel):
    main_branch: str | None = Field(default=None, min_length=1, max_length=255)
    agent: AgentName | None = None
    auto_merge: bool | None = None
    merge_method: Literal["squash", "merge", "rebase"] | None = None
    ci_timeout_seconds: int | None = Field(default=None, ge=60, le=21600)
    ci_registration_grace_seconds: int | None = Field(default=None, ge=0, le=3600)
    command_timeout_seconds: int | None = Field(default=None, ge=30, le=21600)
    implementation_attempts: int | None = Field(default=None, ge=1, le=10)
    verification_attempts: int | None = Field(default=None, ge=1, le=10)
    review_attempts: int | None = Field(default=None, ge=1, le=10)
    ci_attempts: int | None = Field(default=None, ge=1, le=10)
    external_attempts: int | None = Field(default=None, ge=1, le=10)
    external_backoff_seconds: float | None = Field(default=None, ge=0, le=60)
    planner_attempts: int | None = Field(default=None, ge=1, le=10)
    planner_enabled: bool | None = None
    planner_context_classes: list[Literal["SHALLOW", "NORMAL", "DEEP"]] | None = None
    setup_auto: bool | None = None
    setup_commands: dict[str, str] | None = None
    quality_commands: dict[str, str] | None = None
    security_commands: dict[str, str] | None = None
    discovery_max_candidates: int | None = Field(default=None, ge=0, le=50)
    discovery_max_new_issues: int | None = Field(default=None, ge=0, le=50)
    discovery_max_auto_implement: int | None = Field(default=None, ge=0, le=20)
    discovery_max_risk: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    discovery_max_context_class: Literal["SHALLOW", "NORMAL", "DEEP"] | None = None
    discovery_attempts: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def reject_command_secrets(self):
        for commands in (self.setup_commands, self.quality_commands, self.security_commands):
            if not commands:
                continue
            for name, command in commands.items():
                if len(name) > 100 or len(command) > 2000:
                    raise ValueError("Command name/body exceeds the allowed length")
        return self
