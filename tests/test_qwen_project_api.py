import importlib
import subprocess

from fastapi.testclient import TestClient

from aipipe.control.schemas import ProjectConfigPatch, ProjectCreate, ProjectUpdate


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AIPIPE_DEV_AUTH", "true")
    monkeypatch.setenv("AIPIPE_REPOS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "x" * 40)
    # Local projects must not depend on cloud credentials merely to be created.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import aipipe.control.app as app_module
    app_module = importlib.reload(app_module)
    return TestClient(app_module.app)


def test_qwen_is_valid_in_project_and_config_schemas():
    created = ProjectCreate(name="Local", local_path="/tmp/local", agent="qwen", model="qwen-local")
    assert created.agent == "qwen"
    assert created.model == "qwen-local"
    updated = ProjectUpdate(agent="qwen", model="qwen-local")
    assert updated.agent == "qwen"
    assert ProjectConfigPatch(agent="qwen").agent == "qwen"


def test_qwen_rejects_invalid_or_cross_backend_model_combinations():
    try:
        ProjectCreate(name="Bad", local_path="/tmp/local", agent="qwen", model="opus")
        assert False, "expected validation failure"
    except ValueError:
        pass

    try:
        ProjectCreate(name="Bad", local_path="/tmp/local", agent="codex", model="qwen-local")
        assert False, "expected validation failure"
    except ValueError:
        pass


def test_agent_model_listing_exposes_local_qwen_alias(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/agents/models")
        assert response.status_code == 200
        models = response.json()["qwen"]
        by_id = {model["id"]: model["label"] for model in models}
        assert None in by_id
        assert "qwen-local" in by_id
        assert "Local Qwen" in by_id["qwen-local"]


def test_project_api_can_create_read_and_update_qwen_project_without_cloud_keys(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    with _client(monkeypatch, tmp_path) as client:
        created = client.post(
            "/projects",
            json={"name": "Local Qwen", "local_path": str(repo), "agent": "qwen", "model": "qwen-local"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["agent"] == "qwen"
        assert body["model"] == "qwen-local"
        pid = body["id"]

        fetched = client.get(f"/projects/{pid}")
        assert fetched.status_code == 200
        assert fetched.json()["agent"] == "qwen"
        assert fetched.json()["model"] == "qwen-local"

        switched = client.patch(f"/projects/{pid}", json={"agent": "codex", "model": "gpt-5-codex"})
        assert switched.status_code == 200, switched.text
        assert switched.json()["agent"] == "codex"

        switched_back = client.patch(f"/projects/{pid}", json={"agent": "qwen", "model": "qwen-local"})
        assert switched_back.status_code == 200, switched_back.text
        assert switched_back.json()["agent"] == "qwen"
        assert switched_back.json()["model"] == "qwen-local"


def test_project_api_rejects_unavailable_qwen_model(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/projects",
            json={"name": "Bad Local", "local_path": str(repo), "agent": "qwen", "model": "not-configured"},
        )
        assert response.status_code == 422
