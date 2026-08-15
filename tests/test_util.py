from pathlib import Path

from aipipe.util import execute_commands


def test_execute_commands_runs_in_order(tmp_path: Path):
    results = execute_commands(
        {"first": "echo one", "second": "echo two"},
        tmp_path,
        30,
    )
    assert [name for name, _ in results] == ["first", "second"]
    assert results[0][1].stdout.strip() == "one"
    assert results[1][1].stdout.strip() == "two"


def test_execute_commands_stops_at_first_failure(tmp_path: Path):
    results = execute_commands(
        {"broken": "exit 1", "never-runs": "echo two"},
        tmp_path,
        30,
    )
    assert [name for name, _ in results] == ["broken"]
    assert not results[0][1].ok


def test_execute_commands_truncates_output(tmp_path: Path):
    results = execute_commands(
        {"noisy": "python3 -c \"print('x' * 100)\""},
        tmp_path,
        30,
        output_limit=20,
    )
    assert len(results[0][1].stdout) <= 20 + len("\n...<truncated>...\n")


def test_execute_commands_scrubs_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "do-not-leak")
    command = "python3 -c \"import os; assert os.getenv('SOME_SECRET') is None\""
    results = execute_commands({"check-env": command}, tmp_path, 30)
    assert results[0][1].ok
