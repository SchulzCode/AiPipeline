from pathlib import Path

from sqlalchemy import inspect, select, text

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


def test_create_all_upgrades_existing_control_schema(tmp_path):
    db = Database(settings(tmp_path))

    # Schema immediately before the hardening fields were introduced. It is
    # deliberately complete apart from columns with an explicit upgrade path;
    # create_all is not expected to invent arbitrary historical migrations.
    with db.engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE control_projects (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                repository_full_name VARCHAR(512),
                repository_url TEXT,
                local_path TEXT,
                installation_id INTEGER,
                default_branch VARCHAR(255) NOT NULL,
                agent VARCHAR(32) NOT NULL,
                enabled BOOLEAN NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE control_tasks (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NOT NULL,
                source VARCHAR(32) NOT NULL,
                source_reference VARCHAR(255),
                title VARCHAR(512),
                prompt TEXT NOT NULL,
                status VARCHAR(32) NOT NULL,
                risk VARCHAR(32),
                context_class VARCHAR(32),
                core_task_id VARCHAR(32),
                branch TEXT,
                pr_number INTEGER,
                error TEXT,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                claimed_by VARCHAR(255),
                heartbeat_at DATETIME,
                created_at DATETIME NOT NULL,
                started_at DATETIME,
                completed_at DATETIME
            )
            """
        ))

    db.create_all()

    project_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("control_projects")
    }
    task_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("control_tasks")
    }

    assert "model" in project_columns
    assert "failure_category" in task_columns
    assert "worker_build" in task_columns
    assert db.schema_status()["ok"] is True


def test_create_all_is_idempotent_after_migrations(tmp_path):
    db = Database(settings(tmp_path))
    db.create_all()
    db.create_all()
    assert db.ping() is True
    assert db.schema_status() == {"ok": True, "missing": []}
