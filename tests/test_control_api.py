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
        assert body["checks"] == {"checks": [], "review": None, "security_review": None, "ci": None, "plan": None}


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


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    return app_module, TestClient(app_module.app)


def test_control_api_project_patch_updates_agent_and_model(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"}).json()
        pid = project["id"]

        renamed = client.patch(f"/projects/{pid}", json={"name": "Renamed"})
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Renamed"
        assert renamed.json()["agent"] == "codex"

        switched = client.patch(f"/projects/{pid}", json={"agent": "claude", "model": "sonnet"})
        assert switched.status_code == 200
        assert switched.json()["agent"] == "claude"
        assert switched.json()["model"] == "sonnet"

        rejected = client.patch(f"/projects/{pid}", json={"model": "not-a-real-model"})
        assert rejected.status_code == 422

        missing = client.patch("/projects/does-not-exist", json={"name": "x"})
        assert missing.status_code == 404


def test_control_api_global_tasks_lists_across_projects_with_project_context(monkeypatch, tmp_path):
    repo_a = tmp_path / "repo-a"; repo_a.mkdir()
    repo_b = tmp_path / "repo-b"; repo_b.mkdir()
    subprocess.run(["git", "init"], cwd=repo_a, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=repo_b, check=True, capture_output=True)
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        pa = client.post("/projects", json={"name": "Alpha", "local_path": str(repo_a), "agent": "codex"}).json()["id"]
        pb = client.post("/projects", json={"name": "Beta", "local_path": str(repo_b), "agent": "claude", "model": "sonnet"}).json()["id"]
        ta = client.post(f"/projects/{pa}/tasks", json={"prompt": "Task in Alpha"}).json()["id"]
        tb = client.post(f"/projects/{pb}/tasks", json={"prompt": "Task in Beta"}).json()["id"]

        all_tasks = client.get("/tasks").json()
        ids = {t["id"] for t in all_tasks}
        assert {ta, tb} <= ids
        by_id = {t["id"]: t for t in all_tasks}
        assert by_id[ta]["project_name"] == "Alpha"
        assert by_id[tb]["project_name"] == "Beta"
        assert by_id[tb]["project_agent"] == "claude"
        assert by_id[tb]["project_model"] == "sonnet"

        scoped = client.get("/tasks", params={"project_id": pa}).json()
        assert {t["id"] for t in scoped} == {ta}

        by_status = client.get("/tasks", params={"status": "queued"}).json()
        assert {ta, tb} <= {t["id"] for t in by_status}

        none_match = client.get("/tasks", params={"status": "done"}).json()
        assert none_match == []


def test_control_api_system_health_reports_counts_and_no_fabricated_workers(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"}).json()
        client.post(f"/projects/{project['id']}/tasks", json={"prompt": "Do a thing"})

        health = client.get("/system/health")
        assert health.status_code == 200
        body = health.json()
        assert body["projects_total"] == 1
        assert body["projects_by_status"] == {"IDLE": 1}
        assert body["tasks_by_status"] == {"QUEUED": 1}
        assert body["active_tasks"] == 1
        # Nothing has claimed the task yet, so no workers should be reported.
        assert body["active_workers"] == 0
        assert body["stale_tasks"] == 0
        assert body["dev_auth"] is True
        assert body["database"] == "sqlite"


def test_control_api_system_health_counts_fresh_and_stale_claims(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    from aipipe.control.models import ControlTask

    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("AIPIPE_WORKER_STALE_SECONDS", "60")
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"}).json()
        fresh = client.post(f"/projects/{project['id']}/tasks", json={"prompt": "Fresh"}).json()["id"]
        stale = client.post(f"/projects/{project['id']}/tasks", json={"prompt": "Stale"}).json()["id"]

        with app_module.database.session() as db:
            db.get(ControlTask, fresh).claimed_by = "worker-1"
            db.get(ControlTask, fresh).heartbeat_at = datetime.now(timezone.utc)
            db.get(ControlTask, stale).claimed_by = "worker-2"
            db.get(ControlTask, stale).heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=600)

        body = client.get("/system/health").json()
        assert body["active_workers"] == 1
        assert body["stale_tasks"] == 1


def test_control_api_project_config_round_trips_for_local_project(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"}).json()
        pid = project["id"]

        config = client.get(f"/projects/{pid}/config")
        assert config.status_code == 200
        body = config.json()
        assert body["source"] == "local"
        assert body["editable"] is True
        assert body["config"]["auto_merge"] is True
        assert body["config"]["discovery_max_auto_implement"] == 0

        patched = client.patch(f"/projects/{pid}/config", json={"auto_merge": False, "ci_attempts": 5})
        assert patched.status_code == 200
        patched_body = patched.json()
        assert patched_body["config"]["auto_merge"] is False
        assert patched_body["config"]["ci_attempts"] == 5
        # Untouched fields survive the patch.
        assert patched_body["config"]["agent"] == "codex"

        on_disk = (repo / ".ai" / "config.yml").read_text(encoding="utf-8")
        assert "auto_merge: false" in on_disk

        refetched = client.get(f"/projects/{pid}/config").json()
        assert refetched["config"]["auto_merge"] is False
        assert refetched["config"]["ci_attempts"] == 5


def test_control_api_project_config_rejects_invalid_values(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        project = client.post("/projects", json={"name": "Demo", "local_path": str(repo), "agent": "codex"}).json()
        pid = project["id"]

        bad = client.patch(f"/projects/{pid}/config", json={"discovery_max_risk": "EXTREME"})
        assert bad.status_code == 422

        bad_attempts = client.patch(f"/projects/{pid}/config", json={"ci_attempts": 0})
        assert bad_attempts.status_code == 422


def test_control_api_project_config_unavailable_without_local_path_or_repo(monkeypatch, tmp_path):
    app_module, client = _client(monkeypatch, tmp_path)
    with client:
        project = client.post("/projects", json={"name": "GH Demo", "repository_full_name": "octo/demo", "agent": "codex"}).json()
        pid = project["id"]

        config = client.get(f"/projects/{pid}/config")
        assert config.status_code == 200
        body = config.json()
        # No installation_id was set, so GitHub-backed config reads are unavailable.
        assert body["source"] == "unavailable"
        assert body["editable"] is False
        assert body["warning"]

        patch = client.patch(f"/projects/{pid}/config", json={"auto_merge": False})
        assert patch.status_code == 400
