from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..agents import agent_models


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
    agent: Literal["codex", "claude"] = "codex"
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
    branch: str | None
    pr_number: int | None
    error: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


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
