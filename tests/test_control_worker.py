from pathlib import Path

from aipipe.control.db import Database
from aipipe.control.models import ControlTask, Project
from aipipe.control.worker import Worker
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
        assert s.get(ControlTask, first_id).status == "CLAIMED"
        assert s.get(ControlTask, second_id).status == "QUEUED"


def test_worker_serializes_tasks_per_project(tmp_path):
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        p = Project(name="demo", local_path=str(tmp_path)); s.add(p); s.flush()
        first = ControlTask(project_id=p.id, prompt="one", source="prompt"); s.add(first); s.flush()
        second = ControlTask(project_id=p.id, prompt="two", source="prompt"); s.add(second); s.flush()
    w1 = Worker(db, worker_id="w1")
    w2 = Worker(db, worker_id="w2")
    assert w1.claim() == first.id
    assert w2.claim() is None
    with db.session() as s:
        assert s.get(Project, p.id).status == "BUSY"
        assert s.get(ControlTask, second.id).status == "QUEUED"


def test_stale_worker_is_failed_and_project_released(tmp_path):
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
            heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        s.add(task); s.flush(); task_id, project_id = task.id, p.id
    worker = Worker(db, worker_id="new-worker")
    assert worker.recover_stale() == 1
    with db.session() as s:
        task = s.get(ControlTask, task_id)
        assert task.status == "FAILED"
        assert task.claimed_by is None
        assert s.get(Project, project_id).status == "IDLE"
