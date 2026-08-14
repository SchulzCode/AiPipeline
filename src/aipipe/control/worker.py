from __future__ import annotations

import argparse
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import load_settings
from .db import Database
from .executor import TaskExecutor
from .models import ControlTask, Project
from .service import TERMINAL, add_event


class Worker:
    def __init__(self, database: Database, worker_id: str | None = None):
        self.database = database
        self.settings = database.settings
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.executor = TaskExecutor(database, self.settings)

    def recover_stale(self) -> int:
        """Fail tasks whose owning worker stopped heartbeating and release their project.

        V1 deliberately fails closed instead of guessing how to resume a partially-pushed
        Git/PR state. The operator can resubmit after inspecting the recorded event.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.settings.worker_stale_seconds)
        recovered = 0
        with self.database.session() as db:
            rows = list(db.scalars(
                select(ControlTask).where(
                    ControlTask.claimed_by.is_not(None),
                    ControlTask.status.notin_(TERMINAL),
                    ControlTask.heartbeat_at.is_not(None),
                    ControlTask.heartbeat_at < cutoff,
                )
            ).all())
            for task in rows:
                owner = task.claimed_by
                task.status = "FAILED"
                task.error = f"Worker heartbeat expired ({owner}); task was not auto-resumed to avoid duplicating Git/PR side effects."
                task.completed_at = datetime.now(timezone.utc)
                task.claimed_by = None
                add_event(db, task.id, "WORKER_LOST", task.error)
                project = db.get(Project, task.project_id)
                if project:
                    project.status = "IDLE"
                recovered += 1
        return recovered

    def claim(self) -> str | None:
        self.recover_stale()
        now = datetime.now(timezone.utc)
        with self.database.session() as db:
            stmt = select(ControlTask).where(ControlTask.status == "QUEUED").order_by(ControlTask.created_at).limit(25)
            if self.settings.database_url.startswith("postgresql"):
                stmt = stmt.with_for_update(skip_locked=True)
            candidates = list(db.scalars(stmt).all())
            for task in candidates:
                project_stmt = select(Project).where(Project.id == task.project_id)
                if self.settings.database_url.startswith("postgresql"):
                    project_stmt = project_stmt.with_for_update(skip_locked=True)
                project = db.scalar(project_stmt)
                if not project or project.status != "IDLE" or not project.enabled:
                    continue
                # Project row is locked in PostgreSQL. Marking it BUSY here prevents a
                # second worker from claiming another task for the same repository.
                project.status = "BUSY"
                task.status = "CLAIMED"
                task.claimed_by = self.worker_id
                task.started_at = task.started_at or now
                task.heartbeat_at = now
                add_event(db, task.id, "CLAIMED", self.worker_id)
                return task.id
        return None

    def _heartbeat(self, task_id: str, stop: threading.Event) -> None:
        interval = max(1.0, min(30.0, self.settings.worker_stale_seconds / 3.0))
        while not stop.wait(interval):
            with self.database.session() as db:
                task = db.get(ControlTask, task_id)
                if not task or task.status in TERMINAL or task.claimed_by != self.worker_id:
                    return
                task.heartbeat_at = datetime.now(timezone.utc)

    def run_once(self) -> bool:
        task_id = self.claim()
        if not task_id:
            return False
        stop = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(task_id, stop), daemon=True)
        heartbeat.start()
        try:
            self.executor.execute(task_id)
        except Exception:
            # Executor records a terminal state and diagnostic event.
            pass
        finally:
            stop.set()
            heartbeat.join(timeout=2.0)
        return True

    def run_forever(self) -> None:
        while True:
            if not self.run_once():
                time.sleep(self.settings.worker_poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aipipe-worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    settings = load_settings()
    db = Database(settings)
    db.create_all()
    worker = Worker(db)
    if args.once:
        worker.run_once()
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
