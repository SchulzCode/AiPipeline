import subprocess

import pytest

from aipipe.control.db import Database
from aipipe.control.executor import TaskExecutor
from aipipe.control.models import ControlTask, Project
from aipipe.models import FailureCategory
from aipipe.orchestrator import PipelineBlocked
from test_control_db import settings


def test_executor_passes_project_model_to_orchestrator(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(repo), agent="claude", model="opus")
        s.add(project); s.flush()
        task = ControlTask(project_id=project.id, source="prompt", prompt="do it")
        s.add(task); s.flush()
        task_id = task.id

    captured = {}

    class FakeOrchestrator:
        def __init__(self, repo, agent_override=None, model_override=None, state_observer=None, github_env_provider=None):
            captured["agent_override"] = agent_override
            captured["model_override"] = model_override

        def enqueue_prompt_task(self, prompt):
            return "core-1"

        def run(self, core_id, labels=None):
            return None

    monkeypatch.setattr("aipipe.control.executor.Orchestrator", FakeOrchestrator)
    executor = TaskExecutor(db, db.settings)
    executor.execute(task_id)

    assert captured["agent_override"] == "claude"
    assert captured["model_override"] == "opus"


def test_executor_passes_none_model_for_backward_compatible_projects(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(repo), agent="codex")
        s.add(project); s.flush()
        task = ControlTask(project_id=project.id, source="prompt", prompt="do it")
        s.add(task); s.flush()
        task_id = task.id

    captured = {}

    class FakeOrchestrator:
        def __init__(self, repo, agent_override=None, model_override=None, state_observer=None, github_env_provider=None):
            captured["model_override"] = model_override

        def enqueue_prompt_task(self, prompt):
            return "core-1"

        def run(self, core_id, labels=None):
            return None

    monkeypatch.setattr("aipipe.control.executor.Orchestrator", FakeOrchestrator)
    executor = TaskExecutor(db, db.settings)
    executor.execute(task_id)

    assert captured["model_override"] is None


def test_executor_refuses_to_create_second_core_task_for_existing_control_task(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(repo), agent="codex")
        s.add(project); s.flush()
        task = ControlTask(
            project_id=project.id,
            source="prompt",
            prompt="do it",
            core_task_id="T-0042",
        )
        s.add(task); s.flush()
        task_id = task.id

    executor = TaskExecutor(db, db.settings)
    with pytest.raises(PipelineBlocked) as exc:
        executor.execute(task_id)

    assert exc.value.category == FailureCategory.STATE_INCONSISTENCY
    with db.session() as s:
        task = s.get(ControlTask, task_id)
        assert task.core_task_id == "T-0042"
        assert task.status == "BLOCKED"
        assert task.failure_category == FailureCategory.STATE_INCONSISTENCY.value
