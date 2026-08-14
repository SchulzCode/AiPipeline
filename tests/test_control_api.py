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
