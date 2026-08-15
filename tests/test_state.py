import sqlite3
from pathlib import Path

from aipipe.models import FailureCategory, TaskStatus
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


def test_failure_category_is_persisted_and_cleared_on_done(tmp_path: Path):
    store = StateStore(tmp_path / "state.db")
    project = store.project_id(tmp_path)
    store.create_task(project, "prompt", "Do thing", title="Thing")

    store.set_status(
        "T-0001",
        TaskStatus.BLOCKED,
        "review failed",
        failure_category=FailureCategory.REVIEW_FAILURE,
    )
    assert store.task("T-0001")["failure_category"] == FailureCategory.REVIEW_FAILURE.value

    store.set_status("T-0001", TaskStatus.DONE)
    assert store.task("T-0001")["failure_category"] is None


def test_existing_core_state_database_gets_failure_category_column(tmp_path: Path):
    path = tmp_path / "state.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          public_id TEXT UNIQUE,
          project_id INTEGER NOT NULL,
          source TEXT NOT NULL,
          source_reference TEXT,
          title TEXT,
          goal TEXT NOT NULL,
          body TEXT,
          status TEXT NOT NULL,
          task_type TEXT,
          risk TEXT,
          context_class TEXT,
          scopes_json TEXT,
          gates_json TEXT,
          acceptance_json TEXT,
          branch TEXT,
          worktree TEXT,
          pr_number INTEGER,
          created_at TEXT NOT NULL,
          completed_at TEXT
        );
        """
    )
    connection.commit()
    connection.close()

    store = StateStore(path)
    columns = {
        row["name"]
        for row in store.db.execute("PRAGMA table_info(tasks)").fetchall()
    }
    assert "failure_category" in columns
