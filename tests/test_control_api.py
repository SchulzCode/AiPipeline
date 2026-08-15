import importlib
import json
import subprocess

from fastapi.testclient import TestClient


def test_control_api_project_and_task(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/auth/me").json()["login"] == "dev-user"
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"})
        assert project.status_code == 201, project.text
        # Backward compatibility: omitting `model` stores None (Default/Automatic).
        assert project.json()["model"] is None
        pid = project.json()["id"]
        task = client.post(f"/projects/{pid}/tasks", json={"prompt": "Add a small test"})
        assert task.status_code == 202, task.text
        tid = task.json()["id"]
        detail = client.get(f"/tasks/{tid}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "QUEUED"
        events = client.get(f"/tasks/{tid}/events").json()
        assert events[0]["kind"] == "QUEUED"


def test_control_api_task_activity_is_human_readable_and_events_stay_raw(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "claude", "model": "sonnet"})
        pid = project.json()["id"]
        task = client.post(f"/projects/{pid}/tasks", json={"prompt": "Add a small test"})
        tid = task.json()["id"]

        # Raw events remain exactly as recorded, for backward compatibility.
        events = client.get(f"/tasks/{tid}/events").json()
        assert events == [{"id": events[0]["id"], "task_id": tid, "kind": "QUEUED", "detail": "Prompt task queued", "created_at": events[0]["created_at"]}]

        activity = client.get(f"/tasks/{tid}/activity")
        assert activity.status_code == 200
        body = activity.json()
        assert body["items"][0]["title"] == "Queued"
        assert body["items"][0]["category"] == "QUEUED"
        assert body["current"]["title"] == "Queued"
        assert body["current"]["agent_label"] == "Claude · sonnet"
        assert body["blocker"] is None
        assert body["checks"] == {"checks": [], "review": None, "security_review": None, "ci": None}


def test_control_api_task_activity_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        assert client.get("/tasks/does-not-exist/activity").status_code == 404


def test_control_api_agent_models(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        response = client.get("/agents/models")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"codex", "claude"}
        for models in body.values():
            ids = {m["id"] for m in models}
            assert None in ids  # Default/Automatic present for every agent
        claude_ids = {m["id"] for m in body["claude"]}
        assert {"sonnet", "opus"} <= claude_ids


def test_control_api_project_persists_model_per_agent(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        created = client.post(
            "/projects",
            json={"name": "Demo", "local_path": str(repo), "agent": "claude", "model": "opus"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["model"] == "opus"
        pid = created.json()["id"]
        fetched = client.get(f"/projects/{pid}")
        assert fetched.json()["model"] == "opus"


def test_control_api_rejects_model_not_available_for_agent(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        response = client.post(
            "/projects",
            json={"name": "Demo", "local_path": str(repo), "agent": "codex", "model": "opus"},
        )
        assert response.status_code == 422


def test_control_api_discovery_task_requires_github_repository(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"})
        pid = project.json()["id"]
        response = client.post(f"/projects/{pid}/discovery-tasks", json={})
        assert response.status_code == 400


def test_control_api_discovery_task_is_created_queued_with_default_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        project = client.post("/projects", json={"name": "Demo", "repository_full_name": "octo/demo", "agent": "codex"})
        assert project.status_code == 201, project.text
        pid = project.json()["id"]

        response = client.post(f"/projects/{pid}/discovery-tasks", json={})
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["source"] == "discovery"
        assert body["status"] == "QUEUED"
        assert body["prompt"]

        discovery = client.get(f"/tasks/{body['id']}/discovery")
        assert discovery.status_code == 200
        assert discovery.json() == {
            "status": "pending",
            "candidates": [],
            "created": [],
            "duplicates": [],
            "failed": [],
            "handoff_issue_numbers": [],
            "updated_at": None,
        }


def test_control_api_discovery_endpoint_404_for_unknown_task(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        assert client.get("/tasks/does-not-exist/discovery").status_code == 404
        assert client.get("/tasks/does-not-exist/handoff-tasks").status_code == 404


def test_control_api_discovery_endpoint_parses_latest_summary_event(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    from aipipe.control.service import add_event
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        project = client.post("/projects", json={"name": "Demo", "repository_full_name": "octo/demo", "agent": "codex"})
        pid = project.json()["id"]
        task = client.post(f"/projects/{pid}/discovery-tasks", json={})
        tid = task.json()["id"]

        summary = {
            "candidates": [{
                "key": "abc123def456", "title": "Add dark mode", "summary": "s", "rationale": "r",
                "acceptance_criteria": ["a"], "task_type": "FEATURE", "risk": "LOW", "context_class": "SMALL",
                "labels": [], "score": 0.9, "rank": 1, "status": "created", "duplicate_of": None,
                "issue_number": 42, "issue_url": "https://example.invalid/issues/42", "error": None, "handoff": False,
            }],
            "created": ["abc123def456"],
            "duplicates": [],
            "failed": [],
            "handoff_issue_numbers": [],
        }
        with app_module.database.session() as db:
            add_event(
                db, tid, "core:event",
                json.dumps({"task_id": 1, "event": "DISCOVERY_SUMMARY", "detail": json.dumps(summary)}),
            )

        discovery = client.get(f"/tasks/{tid}/discovery")
        assert discovery.status_code == 200
        body = discovery.json()
        assert body["status"] == "ready"
        assert body["created"] == ["abc123def456"]
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["issue_number"] == 42
        assert body["candidates"][0]["status"] == "created"


def test_control_api_handoff_tasks_lists_linked_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    from aipipe.control.models import ControlTask
    app_module = importlib.reload(app_module)
    with TestClient(app_module.app) as client:
        project = client.post("/projects", json={"name": "Demo", "repository_full_name": "octo/demo", "agent": "codex"})
        pid = project.json()["id"]
        task = client.post(f"/projects/{pid}/discovery-tasks", json={})
        tid = task.json()["id"]

        with app_module.database.session() as db:
            handoff = ControlTask(
                project_id=pid,
                source="github_issue",
                source_reference="42",
                title="GitHub Issue #42",
                prompt="Implement GitHub Issue #42",
                discovery_task_id=tid,
            )
            db.add(handoff)
            db.flush()
            handoff_id = handoff.id

        response = client.get(f"/tasks/{tid}/handoff-tasks")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == handoff_id
        assert body[0]["source_reference"] == "42"
        assert body[0]["discovery_task_id"] == tid
