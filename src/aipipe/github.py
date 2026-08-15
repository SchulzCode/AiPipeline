from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from .reliability import looks_transient
from .util import require_binary, run, safe_process_env


class GitHubAdapter:
    def __init__(
        self,
        repo: Path,
        timeout: int = 1200,
        env_provider: Callable[[], dict[str, str]] | None = None,
        read_attempts: int = 3,
        backoff_seconds: float = 2.0,
    ):
        require_binary("gh")
        self.repo = repo
        self.timeout = timeout
        self.env_provider = env_provider
        self.read_attempts = max(1, int(read_attempts))
        self.backoff_seconds = max(0.0, float(backoff_seconds))

    def _env(self) -> dict[str, str] | None:
        return self.env_provider() if self.env_provider else None

    def _run(self, cmd: list[str], cwd: Path):
        auth = self._env()
        if auth is None:
            return run(cmd, cwd, self.timeout)
        return run(
            cmd,
            cwd,
            self.timeout,
            env=safe_process_env(auth),
            inherit_env=False,
        )

    def _run_read(
        self,
        cmd: list[str],
        cwd: Path,
        accepted_returncodes: set[int] | None = None,
    ):
        accepted = accepted_returncodes or {0}
        delay = self.backoff_seconds
        result = None
        for attempt in range(1, self.read_attempts + 1):
            result = self._run(cmd, cwd)
            if result.returncode in accepted:
                return result
            detail = (result.stderr or result.stdout or "").strip()
            if attempt >= self.read_attempts or not looks_transient(detail):
                return result
            time.sleep(delay)
            delay = max(delay * 2, 0.1)
        assert result is not None
        return result

    @staticmethod
    def _parse_json_object(raw: str, context: str) -> dict:
        if not raw.strip():
            raise RuntimeError(f"{context} returned an empty response.")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{context} returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"{context} returned unexpected JSON type: {type(data).__name__}"
            )
        return data

    @staticmethod
    def _parse_json_list(raw: str, context: str) -> list[dict]:
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{context} returned invalid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise RuntimeError(
                f"{context} returned unexpected JSON type: {type(data).__name__}"
            )
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _command_error(prefix: str, result) -> RuntimeError:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        return RuntimeError(f"{prefix}: {detail}")

    def preflight(self, cwd: Path | None = None) -> None:
        target = cwd or self.repo
        result = self._run_read(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            target,
        )
        if not result.ok:
            raise self._command_error("GitHub repository/auth preflight failed", result)
        payload = self._parse_json_object(result.stdout, "gh repo view")
        if not payload.get("nameWithOwner"):
            raise RuntimeError("GitHub preflight did not resolve a repository.")

    def issue(self, number: int) -> dict:
        r = self._run_read(
            [
                "gh", "issue", "view", str(number), "--json",
                "number,title,body,labels,comments,url",
            ],
            self.repo,
        )
        if not r.ok:
            raise self._command_error("Failed to read GitHub issue", r)
        return self._parse_json_object(r.stdout, "gh issue view")

    def _current_branch(self, worktree: Path) -> str:
        result = run(["git", "branch", "--show-current"], worktree, self.timeout)
        if not result.ok or not result.stdout.strip():
            raise RuntimeError("Unable to resolve current task branch.")
        return result.stdout.strip()

    def find_pr_for_branch(self, worktree: Path, branch: str, base: str) -> int | None:
        result = self._run_read(
            [
                "gh", "pr", "list",
                "--head", branch,
                "--base", base,
                "--state", "all",
                "--limit", "20",
                "--json", "number,state,headRefName,baseRefName",
            ],
            worktree,
        )
        if not result.ok:
            raise self._command_error("Failed to reconcile existing pull requests", result)
        items = self._parse_json_list(result.stdout, "gh pr list")
        matches = [
            item for item in items
            if item.get("headRefName") == branch
            and item.get("baseRefName") == base
            and str(item.get("state") or "").upper() in {"OPEN", "MERGED"}
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: int(item.get("number") or 0), reverse=True)
        return int(matches[0]["number"])

    def create_pr(self, worktree: Path, title: str, body: str, base: str) -> int:
        branch = self._current_branch(worktree)
        existing = self.find_pr_for_branch(worktree, branch, base)
        if existing is not None:
            return existing

        r = self._run(
            [
                "gh", "pr", "create",
                "--title", title,
                "--body", body,
                "--base", base,
                "--head", branch,
            ],
            worktree,
        )

        if not r.ok:
            # Creation may have succeeded remotely while the response was lost.
            # Reconcile before deciding this operation failed.
            existing = self.find_pr_for_branch(worktree, branch, base)
            if existing is not None:
                return existing
            raise self._command_error("Failed to create GitHub pull request", r)

        existing = self.find_pr_for_branch(worktree, branch, base)
        if existing is None:
            raise RuntimeError(
                "GitHub reported PR creation success but no matching PR can be resolved."
            )
        return existing

    @staticmethod
    def _state_from_check_records(data: list[dict], returncode: int = 0) -> str:
        buckets = {
            str(item.get("bucket") or "").lower()
            for item in data
        }
        buckets.discard("")
        if "fail" in buckets or "cancel" in buckets:
            return "fail"
        if "pending" in buckets:
            return "pending"
        if data and buckets <= {"pass", "skipping"}:
            return "pass"
        if returncode == 8:
            return "pending"
        return "none"

    @staticmethod
    def _check_run_bucket(check_run: dict) -> str:
        status = str(check_run.get("status") or "").lower()
        conclusion = str(check_run.get("conclusion") or "").lower()
        if status in {"queued", "in_progress", "pending", "requested", "waiting"}:
            return "pending"
        if conclusion == "success":
            return "pass"
        if conclusion in {"skipped", "neutral"}:
            return "skipping"
        if conclusion in {
            "failure", "cancelled", "timed_out", "action_required",
            "stale", "startup_failure",
        }:
            return "fail"
        if status == "completed":
            return "fail"
        return "pending"

    def _pr_head_sha(self, worktree: Path, pr: int) -> str:
        state = self.pr_state(worktree, pr)
        return str(state.get("headRefOid") or "").strip()

    def _api_check_runs_for_ref(self, worktree: Path, head_sha: str, pr: int) -> list[dict]:
        r = self._run_read(
            [
                "gh", "api", "--method", "GET",
                f"repos/{{owner}}/{{repo}}/commits/{head_sha}/check-runs",
                "-H", "Accept: application/vnd.github+json",
                "-H", "X-GitHub-Api-Version: 2026-03-10",
                "-f", "per_page=100",
                "-f", "filter=latest",
            ],
            worktree,
        )
        if not r.ok:
            raise self._command_error(
                f"GitHub Checks API query failed for PR #{pr} ({head_sha})",
                r,
            )
        payload = self._parse_json_object(r.stdout, "GitHub Checks API")
        raw_runs = payload.get("check_runs", [])
        if not isinstance(raw_runs, list):
            raise RuntimeError("GitHub Checks API response has invalid check_runs data.")

        records: list[dict] = []
        for item in raw_runs:
            if not isinstance(item, dict):
                continue
            pull_requests = item.get("pull_requests")
            if isinstance(pull_requests, list) and pull_requests:
                associated = {
                    p.get("number") for p in pull_requests if isinstance(p, dict)
                }
                if pr not in associated:
                    continue
            app = item.get("app")
            app_slug = app.get("slug") if isinstance(app, dict) else None
            records.append(
                {
                    "name": item.get("name") or f"check-run-{item.get('id', 'unknown')}",
                    "state": item.get("conclusion") or item.get("status") or "unknown",
                    "bucket": self._check_run_bucket(item),
                    "link": item.get("html_url") or item.get("details_url") or "",
                    "source": "checks_api",
                    "databaseId": item.get("id"),
                    "headSha": item.get("head_sha") or head_sha,
                    "app": app_slug,
                }
            )
        return records

    def checks(self, worktree: Path, pr: int) -> tuple[str, list[dict]]:
        primary_result = self._run_read(
            [
                "gh", "pr", "checks", str(pr),
                "--json", "name,state,bucket,link",
            ],
            worktree,
            accepted_returncodes={0, 8},
        )
        primary = self._parse_json_list(primary_result.stdout, "gh pr checks")
        if primary:
            return self._state_from_check_records(primary, primary_result.returncode), primary

        head_sha = self._pr_head_sha(worktree, pr)
        if not head_sha:
            if primary_result.returncode == 8:
                return "pending", []
            return "none", []

        fallback = self._api_check_runs_for_ref(worktree, head_sha, pr)
        if fallback:
            return self._state_from_check_records(fallback), fallback
        if primary_result.returncode == 8:
            return "pending", []
        return "none", []

    def _api_workflow_runs_for_head(
        self,
        worktree: Path,
        head_sha: str,
        event: str = "pull_request",
        per_page: int = 100,
    ) -> list[dict]:
        r = self._run_read(
            [
                "gh", "api", "--method", "GET",
                "repos/{owner}/{repo}/actions/runs",
                "-H", "Accept: application/vnd.github+json",
                "-H", "X-GitHub-Api-Version: 2026-03-10",
                "-f", f"head_sha={head_sha}",
                "-f", f"event={event}",
                "-f", f"per_page={per_page}",
            ],
            worktree,
        )
        if not r.ok:
            raise self._command_error(
                f"GitHub Actions API query failed for commit {head_sha}",
                r,
            )
        payload = self._parse_json_object(r.stdout, "GitHub Actions API")
        runs = payload.get("workflow_runs", [])
        if not isinstance(runs, list):
            raise RuntimeError("GitHub Actions API response has invalid workflow_runs data.")
        return [item for item in runs if isinstance(item, dict)]

    def failed_run_logs(
        self,
        worktree: Path,
        branch: str,
        head_sha: str,
        max_runs: int = 3,
    ) -> str:
        _ = branch
        try:
            runs = self._api_workflow_runs_for_head(
                worktree,
                head_sha,
                event="pull_request",
            )
        except RuntimeError as exc:
            return f"Unable to retrieve GitHub Actions run metadata: {exc}"

        failed_runs = [
            item for item in runs
            if str(item.get("conclusion") or "").lower()
            in {
                "failure", "cancelled", "timed_out", "action_required",
                "stale", "startup_failure",
            }
        ]
        failed_runs.sort(
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )

        chunks: list[str] = []
        for item in failed_runs[:max_runs]:
            run_id = item.get("id")
            if not run_id:
                continue
            logs = self._run_read(
                ["gh", "run", "view", str(run_id), "--log-failed"],
                worktree,
            )
            workflow_name = item.get("name") or f"workflow-run-{run_id}"
            if logs.stdout.strip():
                chunks.append(f"Workflow: {workflow_name}\n{logs.stdout}")
            elif not logs.ok:
                detail = (logs.stderr or "no failed-step logs returned").strip()
                chunks.append(
                    f"Workflow: {workflow_name}\nUnable to retrieve failed-step logs: {detail}"
                )
        return "\n\n".join(chunks)

    def pr_state(self, worktree: Path, pr: int) -> dict:
        r = self._run_read(
            [
                "gh", "pr", "view", str(pr), "--json",
                "mergeable,mergeStateStatus,state,headRefOid,headRefName,baseRefName",
            ],
            worktree,
        )
        if not r.ok:
            raise self._command_error(f"Failed to read state for PR #{pr}", r)
        return self._parse_json_object(r.stdout, "gh pr view")

    def merge(
        self,
        worktree: Path,
        pr: int,
        method: str,
        head_sha: str,
    ) -> None:
        before = self.pr_state(worktree, pr)
        if str(before.get("state") or "").upper() == "MERGED":
            return
        remote_head = str(before.get("headRefOid") or "")
        if remote_head and remote_head != head_sha:
            raise RuntimeError(
                f"PR #{pr} head moved from expected {head_sha} to {remote_head}; refusing stale merge."
            )

        flag = {
            "squash": "--squash",
            "merge": "--merge",
            "rebase": "--rebase",
        }.get(method, "--squash")

        # Never use --delete-branch here. AIpipe worktrees own local cleanup.
        r = self._run(
            [
                "gh", "pr", "merge", str(pr), flag,
                "--match-head-commit", head_sha,
            ],
            worktree,
        )
        if r.ok:
            return

        # A network failure can happen after GitHub accepted the merge. Re-read
        # remote state before retrying or reporting failure.
        after = self.pr_state(worktree, pr)
        if str(after.get("state") or "").upper() == "MERGED":
            return
        raise self._command_error(f"Failed to merge PR #{pr}", r)
