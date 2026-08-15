from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import FailureCategory, TaskStatus


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE NOT NULL,
  remote TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  public_id TEXT UNIQUE,
  project_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  source_reference TEXT,
  title TEXT,
  goal TEXT NOT NULL,
  body TEXT,
  status TEXT NOT NULL,
  task_type TEXT,
  risk TEXT,
  context_class TEXT,
  scopes_json TEXT,
  gates_json TEXT,
  acceptance_json TEXT,
  branch TEXT,
  worktree TEXT,
  pr_number INTEGER,
  failure_category TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  FOREIGN KEY(project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  backend TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL,
  summary TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  check_type TEXT NOT NULL,
  name TEXT NOT NULL,
  command TEXT,
  status TEXT NOT NULL,
  exit_code INTEGER,
  summary TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  event TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  run_id INTEGER,
  agent TEXT NOT NULL,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path: Path, observer: Callable[[str, dict[str, Any]], None] | None = None):
        self.path = path
        self.observer = observer
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._ensure_column("tasks", "failure_category", "TEXT")
        self.db.commit()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        columns = {
            str(row["name"])
            for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in columns:
            return
        try:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError:
            # A second process may have applied the same idempotent migration.
            columns = {
                str(row["name"])
                for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in columns:
                raise

    def _notify(self, kind: str, payload: dict[str, Any]) -> None:
        if self.observer:
            try:
                self.observer(kind, payload)
            except Exception:
                # Observability must never be able to break the engineering pipeline.
                pass

    def project_id(self, path: Path, remote: str | None = None) -> int:
        p = str(path.resolve())
        self.db.execute("INSERT OR IGNORE INTO projects(path, remote, created_at) VALUES(?,?,?)", (p, remote, now()))
        if remote:
            self.db.execute("UPDATE projects SET remote=? WHERE path=?", (remote, p))
        self.db.commit()
        row = self.db.execute("SELECT id FROM projects WHERE path=?", (p,)).fetchone()
        return int(row["id"])

    def create_task(self, project_id: int, source: str, goal: str, title: str | None = None,
                    body: str | None = None, source_reference: str | None = None) -> dict[str, Any]:
        cur = self.db.execute(
            "INSERT INTO tasks(project_id,source,source_reference,title,goal,body,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (project_id, source, source_reference, title, goal, body, TaskStatus.QUEUED, now()),
        )
        task_id = int(cur.lastrowid)
        public_id = f"T-{task_id:04d}"
        self.db.execute("UPDATE tasks SET public_id=? WHERE id=?", (public_id, task_id))
        self.db.commit()
        task = self.task(public_id)
        self._notify("task_created", {"task": task})
        return task

    def task(self, public_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM tasks WHERE public_id=?", (public_id,)).fetchone()
        if row is None:
            raise KeyError(public_id)
        return dict(row)

    def update_task(self, public_id: str, **fields: Any) -> None:
        allowed = {
            "status", "task_type", "risk", "context_class", "scopes_json", "gates_json",
            "acceptance_json", "branch", "worktree", "pr_number", "failure_category",
            "completed_at", "title", "goal", "body"
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        sql = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {sql} WHERE public_id=?", (*fields.values(), public_id))
        self.db.commit()
        self._notify("task_updated", {"public_id": public_id, "fields": fields})

    def set_status(
        self,
        public_id: str,
        status: TaskStatus,
        detail: str | None = None,
        failure_category: FailureCategory | str | None = None,
    ) -> None:
        fields: dict[str, Any] = {"status": str(status)}
        if status == TaskStatus.DONE:
            fields["completed_at"] = now()
            fields["failure_category"] = None
        elif failure_category is not None:
            fields["failure_category"] = str(failure_category)
        self.update_task(public_id, **fields)
        task = self.task(public_id)
        self.event(int(task["id"]), f"STATUS:{status}", detail)
        self._notify(
            "status",
            {
                "public_id": public_id,
                "status": str(status),
                "detail": detail,
                "failure_category": str(failure_category) if failure_category is not None else None,
            },
        )

    def event(self, task_id: int, event: str, detail: str | None = None) -> None:
        self.db.execute("INSERT INTO events(task_id,event,detail,created_at) VALUES(?,?,?,?)", (task_id, event, detail, now()))
        self.db.commit()
        self._notify("event", {"task_id": task_id, "event": event, "detail": detail})

    def check(self, task_id: int, check_type: str, name: str, status: str, command: str | None = None,
              exit_code: int | None = None, summary: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO checks(task_id,check_type,name,command,status,exit_code,summary,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (task_id, check_type, name, command, status, exit_code, summary, now()),
        )
        self.db.commit()
        self._notify("check", {"task_id": task_id, "check_type": check_type, "name": name, "status": status, "command": command, "exit_code": exit_code, "summary": summary})

    def finding(self, task_id: int, source: str, severity: str, description: str, status: str = "OPEN") -> None:
        self.db.execute(
            "INSERT INTO findings(task_id,source,severity,status,description,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, source, severity, status, description, now()),
        )
        self.db.commit()
        self._notify("finding", {"task_id": task_id, "source": source, "severity": severity, "status": status, "description": description})

    def start_run(self, task_id: int, role: str, backend: str, attempt: int) -> int:
        cur = self.db.execute(
            "INSERT INTO runs(task_id,role,backend,attempt,status,started_at) VALUES(?,?,?,?,?,?)",
            (task_id, role, backend, attempt, "RUNNING", now()),
        )
        self.db.commit()
        run_id = int(cur.lastrowid)
        self._notify("run_started", {"task_id": task_id, "run_id": run_id, "role": role, "backend": backend, "attempt": attempt})
        return run_id

    def finish_run(self, run_id: int, status: str, summary: str | None = None) -> None:
        self.db.execute(
            "UPDATE runs SET status=?, summary=?, finished_at=? WHERE id=?",
            (status, summary, now(), run_id),
        )
        self.db.commit()
        self._notify("run_finished", {"run_id": run_id, "status": status, "summary": summary})

    def record_usage(self, task_id: int, run_id: int, agent: str, input_tokens: int, output_tokens: int) -> None:
        self.db.execute(
            "INSERT INTO usage(task_id,run_id,agent,input_tokens,output_tokens,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, run_id, agent, input_tokens, output_tokens, now()),
        )
        self.db.commit()
        self._notify("usage", {"task_id": task_id, "run_id": run_id, "agent": agent, "input_tokens": input_tokens, "output_tokens": output_tokens})

    def task_usage(self, public_id: str) -> dict[str, int]:
        row = self.db.execute(
            "SELECT COALESCE(SUM(u.input_tokens),0) AS input_tokens, COALESCE(SUM(u.output_tokens),0) AS output_tokens "
            "FROM usage u JOIN tasks t ON t.id=u.task_id WHERE t.public_id=?",
            (public_id,),
        ).fetchone()
        return {"input_tokens": int(row["input_tokens"]), "output_tokens": int(row["output_tokens"])}

    def list_tasks(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT public_id,title,goal,status,risk,failure_category,created_at FROM tasks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
