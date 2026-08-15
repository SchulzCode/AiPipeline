import json
from pathlib import Path

import aipipe.github as github_mod
from aipipe.github import GitHubAdapter
from aipipe.util import CommandResult


def _result(cmd, stdout="", returncode=0, stderr=""):
    return CommandResult(cmd, returncode, stdout, stderr)


def test_merge_never_uses_admin_delete_branch_or_bypass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    seen = []

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        seen.append(cmd)
        if cmd[:3] == ["gh", "pr", "view"]:
            return _result(cmd, json.dumps({
                "state": "OPEN",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "headRefOid": "abc123",
                "headRefName": "ai/test",
                "baseRefName": "main",
            }))
        return _result(cmd)

    monkeypatch.setattr(github_mod, "run", fake_run)
    gh = GitHubAdapter(tmp_path)
    gh.merge(tmp_path, 7, "squash", "abc123")

    merge_command = next(cmd for cmd in seen if cmd[:3] == ["gh", "pr", "merge"])
    assert "--admin" not in merge_command
    assert "--delete-branch" not in merge_command
    assert "--match-head-commit" in merge_command
    assert "abc123" in merge_command


def test_merge_is_idempotent_when_pr_already_merged(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    seen = []

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        seen.append(cmd)
        return _result(cmd, json.dumps({
            "state": "MERGED",
            "mergeable": "UNKNOWN",
            "mergeStateStatus": "CLEAN",
            "headRefOid": "abc123",
            "headRefName": "ai/test",
            "baseRefName": "main",
        }))

    monkeypatch.setattr(github_mod, "run", fake_run)
    gh = GitHubAdapter(tmp_path)
    gh.merge(tmp_path, 7, "squash", "abc123")
    assert not any(cmd[:3] == ["gh", "pr", "merge"] for cmd in seen)


def test_merge_failure_reconciles_remote_success(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    states = iter(["OPEN", "MERGED"])

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        if cmd[:3] == ["gh", "pr", "view"]:
            state = next(states)
            return _result(cmd, json.dumps({
                "state": state,
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "headRefOid": "abc123",
                "headRefName": "ai/test",
                "baseRefName": "main",
            }))
        if cmd[:3] == ["gh", "pr", "merge"]:
            return _result(cmd, returncode=1, stderr="connection reset by peer")
        return _result(cmd)

    monkeypatch.setattr(github_mod, "run", fake_run)
    GitHubAdapter(tmp_path).merge(tmp_path, 7, "squash", "abc123")


def test_create_pr_reuses_existing_open_pr(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    seen = []

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        seen.append(cmd)
        if cmd[:3] == ["git", "branch", "--show-current"]:
            return _result(cmd, "ai/task\n")
        if cmd[:3] == ["gh", "pr", "list"]:
            return _result(cmd, json.dumps([{
                "number": 42,
                "state": "OPEN",
                "headRefName": "ai/task",
                "baseRefName": "main",
            }]))
        return _result(cmd)

    monkeypatch.setattr(github_mod, "run", fake_run)
    pr = GitHubAdapter(tmp_path).create_pr(tmp_path, "title", "body", "main")
    assert pr == 42
    assert not any(cmd[:3] == ["gh", "pr", "create"] for cmd in seen)


def test_no_ci_checks_is_distinct_from_pass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        if cmd[:3] == ["gh", "pr", "checks"]:
            return _result(cmd, "[]")
        if cmd[:3] == ["gh", "pr", "view"]:
            return _result(cmd, json.dumps({
                "state": "OPEN",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "headRefOid": "abc123",
                "headRefName": "ai/task",
                "baseRefName": "main",
            }))
        if cmd[:3] == ["gh", "api", "--method"]:
            return _result(cmd, json.dumps({"check_runs": []}))
        return _result(cmd)

    monkeypatch.setattr(github_mod, "run", fake_run)
    state, checks = GitHubAdapter(tmp_path).checks(tmp_path, 9)
    assert state == "none"
    assert checks == []


def test_transient_read_is_retried_but_bounded(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(github_mod, "require_binary", lambda _: None)
    monkeypatch.setattr(github_mod.time, "sleep", lambda _: None)
    attempts = 0

    def fake_run(cmd, cwd, timeout=1200, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return _result(cmd, returncode=1, stderr="HTTP 503 temporarily unavailable")
        return _result(cmd, json.dumps({"nameWithOwner": "SchulzCode/AiPipeline"}))

    monkeypatch.setattr(github_mod, "run", fake_run)
    GitHubAdapter(tmp_path, read_attempts=3, backoff_seconds=0).preflight(tmp_path)
    assert attempts == 3
