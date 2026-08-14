from pathlib import Path

from aipipe.setup_engine import SetupEngine


def test_setup_noop_for_unknown_project(tmp_path: Path):
    outcome = SetupEngine({}, True, 30, tmp_path / "runtime").execute(tmp_path)
    assert outcome.results == []
    assert outcome.runtime_env == {}


def test_explicit_setup_runs_with_scrubbed_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "do-not-leak")
    command = "python -c \"import os; assert os.getenv('DATABASE_URL') is None\""
    outcome = SetupEngine({"check-env": command}, False, 30, tmp_path / "runtime").execute(tmp_path)
    assert len(outcome.results) == 1
    assert outcome.results[0][1].ok
