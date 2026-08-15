import subprocess

import pytest
from sqlalchemy import select

from aipipe.control.db import Database
from aipipe.control.executor import TaskExecutor
from aipipe.control.models import ControlTask, Project
from aipipe.discovery import DiscoveryResult, FeatureCandidate
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


def test_executor_routes_discovery_source_to_run_discovery_and_creates_bounded_handoff_tasks(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(repo), agent="codex")
        s.add(project); s.flush()
        task = ControlTask(project_id=project.id, source="discovery", prompt="discover features")
        s.add(task); s.flush()
        task_id = task.id

    captured = {}

    class FakeOrchestrator:
        def __init__(self, repo, agent_override=None, model_override=None, state_observer=None, github_env_provider=None):
            captured["init"] = True

        def enqueue_discovery_task(self, prompt):
            captured["prompt"] = prompt
            return "core-discovery-1"

        def run_discovery(self, core_id):
            captured["run_discovery_core_id"] = core_id
            candidate = FeatureCandidate(key="k1", title="Add dark mode", summary="s", status="created", issue_number=101)
            candidate.handoff = True
            return DiscoveryResult(candidates=[candidate], created=[candidate], handoff_issue_numbers=[101])

        def run(self, core_id, labels=None):
            raise AssertionError("discovery must never call Orchestrator.run() itself")

    monkeypatch.setattr("aipipe.control.executor.Orchestrator", FakeOrchestrator)
    executor = TaskExecutor(db, db.settings)
    executor.execute(task_id)

    assert captured["run_discovery_core_id"] == "core-discovery-1"
    with db.session() as s:
        task = s.get(ControlTask, task_id)
        assert task.core_task_id == "core-discovery-1"
        handoff_tasks = list(s.scalars(select(ControlTask).where(ControlTask.discovery_task_id == task_id)))
        assert len(handoff_tasks) == 1
        assert handoff_tasks[0].source == "github_issue"
        assert handoff_tasks[0].source_reference == "101"
        assert handoff_tasks[0].status == "QUEUED"


def test_executor_discovery_with_no_handoff_creates_no_extra_tasks(monkeypatch, tmp_path):
    """Safe-default acceptance criterion mirrored at the control-plane layer."""
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    db = Database(settings(tmp_path)); db.create_all()
    with db.session() as s:
        project = Project(name="demo", local_path=str(repo), agent="codex")
        s.add(project); s.flush()
        task = ControlTask(project_id=project.id, source="discovery", prompt="discover features")
        s.add(task); s.flush()
        task_id = task.id

    class FakeOrchestrator:
        def __init__(self, repo, agent_override=None, model_override=None, state_observer=None, github_env_provider=None):
            pass

        def enqueue_discovery_task(self, prompt):
            return "core-discovery-2"

        def run_discovery(self, core_id):
            return DiscoveryResult()

    monkeypatch.setattr("aipipe.control.executor.Orchestrator", FakeOrchestrator)
    executor = TaskExecutor(db, db.settings)
    executor.execute(task_id)

    with db.session() as s:
        handoff_tasks = list(s.scalars(select(ControlTask).where(ControlTask.discovery_task_id == task_id)))
        assert handoff_tasks == []
