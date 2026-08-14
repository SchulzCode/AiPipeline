from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable

from .util import require_binary, run, safe_process_env


class GitHubAdapter:
    def __init__(self, repo: Path, timeout: int = 1200, env_provider: Callable[[], dict[str, str]] | None = None):
        require_binary("gh")
        self.repo = repo
        self.timeout = timeout
        self.env_provider = env_provider

    def _env(self) -> dict[str, str] | None:
        return self.env_provider() if self.env_provider else None

    def _run(self, cmd: list[str], cwd: Path):
        auth = self._env()
        if auth is None:
            return run(cmd, cwd, self.timeout)
        return run(cmd, cwd, self.timeout, env=safe_process_env(auth), inherit_env=False)

    def issue(self, number: int) -> dict:
        r = self._run(["gh", "issue", "view", str(number), "--json", "number,title,body,labels,comments,url"], self.repo)
        if not r.ok:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def create_pr(self, worktree: Path, title: str, body: str, base: str) -> int:
        r = self._run(["gh", "pr", "create", "--title", title, "--body", body, "--base", base], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr)
        view = self._run(["gh", "pr", "view", "--json", "number", "--jq", ".number"], worktree)
        if not view.ok:
            raise RuntimeError(view.stderr)
        return int(view.stdout.strip())

    def checks(self, worktree: Path, pr: int) -> tuple[str, list[dict]]:
        r = self._run(["gh", "pr", "checks", str(pr), "--json", "name,state,bucket,link"], worktree)
        data = json.loads(r.stdout or "[]") if r.stdout.strip() else []
        buckets = {x.get("bucket") for x in data}
        if "fail" in buckets:
            return "fail", data
        if "pending" in buckets or r.returncode == 8:
            return "pending", data
        if data and buckets <= {"pass", "skipping"}:
            return "pass", data
        # Repositories with no CI checks are not silently treated as green.
        return "none", data


    def failed_run_logs(self, worktree: Path, branch: str, head_sha: str, max_runs: int = 3) -> str:
        r = self._run([
            "gh", "run", "list", "--branch", branch, "--commit", head_sha, "--status", "failure",
            "--json", "databaseId,headSha,workflowName,conclusion", "--limit", str(max_runs)
        ], worktree)
        if not r.ok or not r.stdout.strip():
            return ""
        try:
            runs = json.loads(r.stdout)
        except json.JSONDecodeError:
            return ""
        chunks = []
        for item in runs[:max_runs]:
            run_id = item.get("databaseId")
            if not run_id:
                continue
            logs = self._run(["gh", "run", "view", str(run_id), "--log-failed"], worktree)
            if logs.stdout.strip():
                chunks.append(f"Workflow: {item.get('workflowName') or run_id}\n{logs.stdout}")
        return "\n\n".join(chunks)

    def pr_state(self, worktree: Path, pr: int) -> dict:
        r = self._run(["gh", "pr", "view", str(pr), "--json", "mergeable,mergeStateStatus,state,headRefOid"], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def merge(self, worktree: Path, pr: int, method: str, head_sha: str) -> None:
        flag = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}.get(method, "--squash")
        r = self._run(["gh", "pr", "merge", str(pr), flag, "--delete-branch", "--match-head-commit", head_sha], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr)
