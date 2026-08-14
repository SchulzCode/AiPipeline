from pathlib import Path

from aipipe.models import TaskStatus
from aipipe.state import StateStore


def test_task_lifecycle_and_usage(tmp_path: Path):
    store = StateStore(tmp_path / "state.db")
    project = store.project_id(tmp_path)
    task = store.create_task(project, "prompt", "Do thing", title="Thing")
    assert task["public_id"] == "T-0001"
    store.set_status("T-0001", TaskStatus.IMPLEMENTING)
    assert store.task("T-0001")["status"] == "IMPLEMENTING"
    run_id = store.start_run(1, "IMPLEMENTER", "codex", 1)
    store.finish_run(run_id, "PASS", "ok")
    store.record_usage(1, run_id, "codex", 100, 20)
    assert store.task_usage("T-0001") == {"input_tokens": 100, "output_tokens": 20}
