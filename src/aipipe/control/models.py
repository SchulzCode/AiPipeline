from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


def uid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "control_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    github_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    login: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "control_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255))
    repository_full_name: Mapped[str | None] = mapped_column(String(512), nullable=True, unique=True)
    repository_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    agent: Mapped[str] = mapped_column(String(32), default="codex")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="IDLE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tasks: Mapped[list["ControlTask"]] = relationship(back_populates="project", cascade="all,delete-orphan")


class ControlTask(Base):
    __tablename__ = "control_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("control_projects.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="prompt")
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    risk: Mapped[str | None] = mapped_column(String(32), nullable=True)
    context_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    core_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    project: Mapped[Project] = relationship(back_populates="tasks")
    events: Mapped[list["ControlEvent"]] = relationship(back_populates="task", cascade="all,delete-orphan")


class ControlEvent(Base):
    __tablename__ = "control_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("control_tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(128), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    task: Mapped[ControlTask] = relationship(back_populates="events")


class WebhookDelivery(Base):
    __tablename__ = "github_webhook_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(128))
    event: Mapped[str] = mapped_column(String(128))
    installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repository_full_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("delivery_id", name="uq_webhook_delivery"),)
