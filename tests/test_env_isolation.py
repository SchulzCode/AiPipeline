from __future__ import annotations

import os
from pathlib import Path

from aipipe.util import safe_process_env, run


def test_safe_process_env_drops_control_plane_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://super-secret")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", "private-key")
    monkeypatch.setenv("AIPIPE_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "agent-key")
    env = safe_process_env({"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]})
    assert env["OPENAI_API_KEY"] == "agent-key"
    assert "DATABASE_URL" not in env
    assert "GITHUB_APP_PRIVATE_KEY_B64" not in env
    assert "AIPIPE_SESSION_SECRET" not in env


def test_run_can_use_strict_environment(tmp_path: Path):
    env = safe_process_env({"ONLY_THIS": "yes"})
    result = run(
        ["python", "-c", "import os; print(os.getenv('ONLY_THIS')); print(os.getenv('DATABASE_URL'))"],
        tmp_path,
        env=env,
        inherit_env=False,
    )
    assert result.ok
    assert result.stdout.splitlines() == ["yes", "None"]
