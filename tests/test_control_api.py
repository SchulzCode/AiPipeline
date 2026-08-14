import importlib
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
