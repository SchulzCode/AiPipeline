from pathlib import Path

from aipipe.control.db import Database
from aipipe.control.models import ControlTask, Project
from aipipe.control.worker import Worker
from aipipe.models import FailureCategory
from test_control_db import settings


def test_worker_claims_oldest_task(tmp_path):
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        p = Project(name="demo", local_path=str(tmp_path)); s.add(p); s.flush()
        first = ControlTask(project_id=p.id, prompt="one", source="prompt"); s.add(first); s.flush()
        second = ControlTask(project_id=p.id, prompt="two", source="prompt"); s.add(second); s.flush()
        first_id, second_id = first.id, second.id
    worker = Worker(db, worker_id="test-worker")
    claimed = worker.claim()
    assert claimed == first_id
    with db.session() as s:
        claimed_task = s.get(ControlTask, first_id)
        assert claimed_task.status == "CLAIMED"
        assert claimed_task.worker_build == worker.build
        assert s.get(ControlTask, second_id).status == "QUEUED"


def test_worker_serializes_tasks_per_project(tmp_path):
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        p = Project(name="demo", local_path=str(tmp_path)); s.add(p); s.flush()
        first = ControlTask(project_id=p.id, prompt="one", source="prompt"); s.add(first); s.flush()
        second = ControlTask(project_id=p.id, prompt="two", source="prompt"); s.add(second); s.flush()
        first_id, second_id, project_id = first.id, second.id, p.id
    w1 = Worker(db, worker_id="w1")
    w2 = Worker(db, worker_id="w2")
    assert w1.claim() == first_id
    assert w2.claim() is None
    with db.session() as s:
        assert s.get(Project, project_id).status == "BUSY"
        assert s.get(ControlTask, second_id).status == "QUEUED"


def test_stale_worker_is_blocked_and_project_released_without_discarding_state(tmp_path):
    from datetime import datetime, timedelta, timezone

    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        p = Project(name="demo", local_path=str(tmp_path), status="BUSY"); s.add(p); s.flush()
        task = ControlTask(
            project_id=p.id,
            prompt="one",
            source="prompt",
            status="IMPLEMENTING",
            claimed_by="dead-worker",
            branch="ai/T-0042-example",
            core_task_id="T-0042",
            heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        s.add(task); s.flush(); task_id, project_id = task.id, p.id

    worker = Worker(db, worker_id="new-worker")
    assert worker.recover_stale() == 1

    with db.session() as s:
        task = s.get(ControlTask, task_id)
        assert task.status == "BLOCKED"
        assert task.failure_category == FailureCategory.ENVIRONMENT.value
        assert task.claimed_by is None
        assert task.heartbeat_at is None
        assert task.branch == "ai/T-0042-example"
        assert task.core_task_id == "T-0042"
        assert "preserved" in task.error
        assert s.get(Project, project_id).status == "IDLE"


def test_heartbeat_once_refreshes_active_claim(tmp_path):
    from datetime import datetime, timedelta, timezone

    db = Database(settings(tmp_path)); db.create_all()
    old_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=1)
    with db.session() as s:
        project = Project(name="demo", local_path=str(tmp_path), status="BUSY")
        s.add(project); s.flush()
        task = ControlTask(
            project_id=project.id,
            prompt="one",
            source="prompt",
            status="IMPLEMENTING",
            claimed_by="test-worker",
            heartbeat_at=old_heartbeat,
        )
        s.add(task); s.flush(); task_id = task.id

    worker = Worker(db, worker_id="test-worker")
    assert worker._heartbeat_once(task_id) is True

    with db.session() as s:
        refreshed = s.get(ControlTask, task_id)
        assert refreshed.heartbeat_at is not None
        assert refreshed.heartbeat_at != old_heartbeat


def test_heartbeat_loop_survives_one_transient_update_failure(monkeypatch, tmp_path):
    db = Database(settings(tmp_path)); db.create_all()
    worker = Worker(db, worker_id="test-worker")
    attempts = 0

    def heartbeat_once(_task_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary database failure")
        return False

    class StopAfterTwoTicks:
        def __init__(self):
            self.calls = 0

        def wait(self, _interval):
            self.calls += 1
            return self.calls > 2

    monkeypatch.setattr(worker, "_heartbeat_once", heartbeat_once)
    worker._heartbeat("task-id", StopAfterTwoTicks())

    # The old implementation died after the first exception. The resilient
    # loop must reach a second heartbeat attempt instead.
    assert attempts == 2
