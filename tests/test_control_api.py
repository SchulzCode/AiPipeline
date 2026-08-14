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
        pid = project.json()["id"]
        task = client.post(f"/projects/{pid}/tasks", json={"prompt": "Add a small test"})
        assert task.status_code == 202, task.text
        tid = task.json()["id"]
        detail = client.get(f"/tasks/{tid}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "QUEUED"
        events = client.get(f"/tasks/{tid}/events").json()
        assert events[0]["kind"] == "QUEUED"
