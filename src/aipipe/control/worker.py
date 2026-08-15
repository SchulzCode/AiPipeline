from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from aipipe.models import FailureCategory
from aipipe.reliability import build_identity

from .config import load_settings
from .db import Database
from .executor import TaskExecutor
from .models import ControlTask, Project
from .service import TERMINAL, add_event


logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, database: Database, worker_id: str | None = None):
        self.database = database
        self.settings = database.settings
        # PID 1 and the Docker hostname can both be reused after a container
        # restart. Include a short boot nonce so stale-task diagnostics can
        # distinguish the old worker process from its replacement.
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.build = build_identity()
        self.executor = TaskExecutor(database, self.settings)

    def recover_stale(self) -> int:
        """Pause tasks whose owning worker stopped heartbeating.

        The task is left BLOCKED rather than discarded or automatically
        restarted. Existing worktree/branch state is preserved for the
        resumable-task flow (#9), while duplicate Git/PR side effects are
        avoided until a safe checkpoint-aware resume implementation takes over.
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
                task.status = "BLOCKED"
                task.error = (
                    f"Worker heartbeat expired ({owner}); existing task state was preserved. "
                    "Resume from a safe checkpoint instead of creating a duplicate task."
                )
                task.failure_category = FailureCategory.ENVIRONMENT.value
                task.completed_at = datetime.now(timezone.utc)
                task.claimed_by = None
                task.heartbeat_at = None
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
                project.status = "BUSY"
                task.status = "CLAIMED"
                task.claimed_by = self.worker_id
                task.worker_build = self.build
                task.started_at = task.started_at or now
                task.heartbeat_at = now
                task.error = None
                task.failure_category = None
                add_event(db, task.id, "CLAIMED", f"{self.worker_id} build={self.build}")
                return task.id
        return None

    def _heartbeat_once(self, task_id: str) -> bool:
        """Refresh one task heartbeat.

        Returns False when the task is no longer owned by this worker and the
        heartbeat loop should stop. Database errors are intentionally allowed to
        propagate to the loop so they can be logged and retried on the next
        interval instead of silently killing the daemon thread forever.
        """

        with self.database.session() as db:
            task = db.get(ControlTask, task_id)
            if not task or task.status in TERMINAL or task.claimed_by != self.worker_id:
                return False
            task.heartbeat_at = datetime.now(timezone.utc)
            return True

    def _heartbeat(self, task_id: str, stop: threading.Event) -> None:
        interval = max(1.0, min(30.0, self.settings.worker_stale_seconds / 3.0))
        while not stop.wait(interval):
            try:
                if not self._heartbeat_once(task_id):
                    return
            except Exception as exc:  # noqa: BLE001 - heartbeat must self-heal
                # Previously one transient DB/session failure terminated this
                # daemon thread permanently. Five minutes later another worker
                # could then falsely classify an otherwise healthy long-running
                # agent invocation as WORKER_LOST. Keep the loop alive and let
                # the next bounded heartbeat interval retry the write.
                logger.warning(
                    "Heartbeat update failed for task %s; will retry on the next interval: %s",
                    task_id,
                    exc,
                    exc_info=True,
                )

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
            # Executor records a terminal/recoverable state and diagnostic event.
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
