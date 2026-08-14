import json
from pathlib import Path

import aipipe.github as github_mod
from aipipe.github import GitHubAdapter
from aipipe.util import CommandResult


def test_merge_never_uses_admin_or_bypass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    seen = []

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        seen.append(cmd)
        return CommandResult(cmd, 0, "", "")

    monkeypatch.setattr(github_mod, "run", fake_run)
    gh = GitHubAdapter(tmp_path)
    gh.merge(tmp_path, 7, "squash", "abc123")
    command = seen[-1]
    assert "--admin" not in command
    assert "--match-head-commit" in command
    assert "abc123" in command


def test_no_ci_checks_is_distinct_from_pass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    monkeypatch.setattr(
        github_mod,
        "run",
        lambda *a, **k: CommandResult(a[0], 0, "", ""),
    )
    gh = GitHubAdapter(tmp_path)
    state, checks = gh.checks(tmp_path, 9)
    assert state == "none"
    assert checks == []
