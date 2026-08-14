from aipipe.models import TaskStatus
from aipipe.state import StateStore


def test_state_store_observer_receives_status_and_usage(tmp_path):
    seen = []
    store = StateStore(tmp_path / "state.db", observer=lambda kind, payload: seen.append((kind, payload)))
    project = store.project_id(tmp_path)
    task = store.create_task(project, "prompt", "do something")
    store.set_status(task["public_id"], TaskStatus.ROUTING)
    run_id = store.start_run(task["id"], "IMPLEMENTER", "codex", 1)
    store.record_usage(task["id"], run_id, "codex", 10, 20)
    assert any(k == "status" and p["status"] == "ROUTING" for k, p in seen)
    assert any(k == "usage" and p["output_tokens"] == 20 for k, p in seen)
