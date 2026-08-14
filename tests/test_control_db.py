from pathlib import Path

from sqlalchemy import select

from aipipe.control.config import ControlSettings
from aipipe.control.db import Database
from aipipe.control.models import ControlEvent, ControlTask, Project
from aipipe.control.service import add_event


def settings(tmp_path: Path) -> ControlSettings:
    return ControlSettings(
        database_url=f"sqlite:///{tmp_path / 'control.db'}",
        api_base_url="http://localhost:8000",
        web_base_url="http://localhost:3000",
        repos_root=tmp_path / "repos",
        worker_poll_seconds=0.01,
        worker_stale_seconds=1.0,
        github_app_id=None,
        github_app_client_id=None,
        github_app_private_key=None,
        github_app_client_secret=None,
        github_webhook_secret="secret",
        session_secret="x" * 40,
        dev_auth=True,
        cors_origins=["http://localhost:3000"],
        allowed_github_logins=[],
    )


def test_control_database_roundtrip(tmp_path):
    db = Database(settings(tmp_path))
    db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(tmp_path), agent="codex")
        s.add(project); s.flush()
        task = ControlTask(project_id=project.id, source="prompt", prompt="fix it", title="fix")
        s.add(task); s.flush()
        add_event(s, task.id, "QUEUED", "ready")
        task_id = task.id
    with db.session() as s:
        task = s.get(ControlTask, task_id)
        assert task and task.status == "QUEUED"
        events = list(s.scalars(select(ControlEvent).where(ControlEvent.task_id == task_id)))
        assert [e.kind for e in events] == ["QUEUED"]


def test_project_model_defaults_to_none_for_backward_compatibility(tmp_path):
    db = Database(settings(tmp_path))
    db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(tmp_path), agent="codex")
        s.add(project); s.flush()
        project_id = project.id
    with db.session() as s:
        assert s.get(Project, project_id).model is None


def test_project_model_roundtrip(tmp_path):
    db = Database(settings(tmp_path))
    db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(tmp_path), agent="claude", model="sonnet")
        s.add(project); s.flush()
        project_id = project.id
    with db.session() as s:
        assert s.get(Project, project_id).model == "sonnet"
