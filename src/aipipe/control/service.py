from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ControlEvent, ControlTask, Project


TERMINAL = {"DONE", "BLOCKED", "FAILED", "CANCELLED"}


def add_event(db: Session, task_id: str, kind: str, detail: str | None = None) -> ControlEvent:
    event = ControlEvent(task_id=task_id, kind=kind, detail=detail)
    db.add(event)
    db.flush()
    return event


def task_to_dict(task: ControlTask) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "source": task.source,
        "source_reference": task.source_reference,
        "title": task.title,
        "prompt": task.prompt,
        "status": task.status,
        "risk": task.risk,
        "context_class": task.context_class,
        "core_task_id": task.core_task_id,
        "branch": task.branch,
        "pr_number": task.pr_number,
        "error": task.error,
    }


def apply_core_observation(database, control_task_id: str):
    """Return a callback that mirrors core pipeline state into the control database."""
    def observer(kind: str, payload: dict) -> None:
        with database.session() as db:
            task = db.get(ControlTask, control_task_id)
            if not task:
                return
            if kind == "status":
                status = str(payload.get("status") or "")
                task.status = status
                if status in TERMINAL:
                    task.completed_at = datetime.now(timezone.utc)
                if status in {"BLOCKED", "FAILED"}:
                    task.error = payload.get("detail")
            elif kind == "usage":
                task.input_tokens += int(payload.get("input_tokens", 0) or 0)
                task.output_tokens += int(payload.get("output_tokens", 0) or 0)
            elif kind == "task_updated":
                fields = payload.get("fields") or {}
                if fields.get("risk"):
                    task.risk = fields["risk"]
                if fields.get("context_class"):
                    task.context_class = fields["context_class"]
                if fields.get("branch"):
                    task.branch = fields["branch"]
                if fields.get("pr_number") is not None:
                    task.pr_number = int(fields["pr_number"])
            detail = json.dumps(payload, ensure_ascii=False, default=str)
            add_event(db, control_task_id, f"core:{kind}", detail[:16000])
    return observer
