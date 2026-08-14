from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .util import require_binary, run, safe_process_env


class GitHubAdapter:
    def __init__(
        self,
        repo: Path,
        timeout: int = 1200,
        env_provider: Callable[[], dict[str, str]] | None = None,
    ):
        require_binary("gh")
        self.repo = repo
        self.timeout = timeout
        self.env_provider = env_provider

    def _env(self) -> dict[str, str] | None:
        return self.env_provider() if self.env_provider else None

    def _run(self, cmd: list[str], cwd: Path):
        auth = self._env()

        if auth is None:
            return run(
                cmd,
                cwd,
                self.timeout,
            )

        return run(
            cmd,
            cwd,
            self.timeout,
            env=safe_process_env(auth),
            inherit_env=False,
        )

    def issue(
        self,
        number: int,
    ) -> dict:
        r = self._run(
            [
                "gh",
                "issue",
                "view",
                str(number),
                "--json",
                "number,title,body,labels,comments,url",
            ],
            self.repo,
        )

        if not r.ok:
            raise RuntimeError(r.stderr)

        return json.loads(r.stdout)

    def create_pr(
        self,
        worktree: Path,
        title: str,
        body: str,
        base: str,
    ) -> int:
        r = self._run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base,
            ],
            worktree,
        )

        if not r.ok:
            raise RuntimeError(r.stderr)

        view = self._run(
            [
                "gh",
                "pr",
                "view",
                "--json",
                "number",
                "--jq",
                ".number",
            ],
            worktree,
        )

        if not view.ok:
            raise RuntimeError(view.stderr)

        return int(
            view.stdout.strip()
        )

    @staticmethod
    def _json_list(
        raw: str,
    ) -> list[dict]:
        if not raw.strip():
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []

        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    @staticmethod
    def _state_from_check_records(
        data: list[dict],
        returncode: int = 0,
    ) -> str:
        buckets = {
            str(
                item.get("bucket") or ""
            ).lower()
            for item in data
        }

        buckets.discard("")

        # Failed or cancelled checks must
        # never be treated as green.
        if (
            "fail" in buckets
            or "cancel" in buckets
        ):
            return "fail"

        if "pending" in buckets:
            return "pending"

        if (
            data
            and buckets
            <= {
                "pass",
                "skipping",
            }
        ):
            return "pass"

        # gh pr checks uses exit code 8
        # while checks are still pending.
        if returncode == 8:
            return "pending"

        return "none"

    @staticmethod
    def _workflow_run_bucket(
        run_data: dict,
    ) -> str:
        status = str(
            run_data.get("status")
            or ""
        ).lower()

        conclusion = str(
            run_data.get("conclusion")
            or ""
        ).lower()

        if status in {
            "queued",
            "in_progress",
            "pending",
            "requested",
            "waiting",
        }:
            return "pending"

        if conclusion == "success":
            return "pass"

        if conclusion in {
            "skipped",
            "neutral",
        }:
            return "skipping"

        if conclusion in {
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "stale",
            "startup_failure",
        }:
            return "fail"

        if (
            status == "completed"
            and not conclusion
        ):
            # A completed workflow without
            # a successful known conclusion
            # is insufficient evidence to
            # auto-merge.
            return "fail"

        # Unknown non-terminal states are
        # treated as pending so the
        # orchestrator waits rather than
        # merging without evidence.
        return "pending"

    def _pr_head_sha(
        self,
        worktree: Path,
        pr: int,
    ) -> str:
        r = self._run(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                "headRefOid",
                "--jq",
                ".headRefOid",
            ],
            worktree,
        )

        if not r.ok:
            return ""

        return r.stdout.strip()

    def _workflow_runs_for_pr_head(
        self,
        worktree: Path,
        head_sha: str,
        limit: int = 100,
    ) -> list[dict]:
        if not head_sha:
            return []

        r = self._run(
            [
                "gh",
                "run",
                "list",
                "--commit",
                head_sha,
                "--event",
                "pull_request",
                "--json",
                (
                    "databaseId,headSha,"
                    "workflowName,status,"
                    "conclusion,url,event"
                ),
                "--limit",
                str(limit),
            ],
            worktree,
        )

        if (
            not r.ok
            and not r.stdout.strip()
        ):
            return []

        runs = self._json_list(
            r.stdout
        )

        records: list[dict] = []

        for item in runs:
            bucket = (
                self._workflow_run_bucket(
                    item
                )
            )

            workflow_name = (
                item.get("workflowName")
                or (
                    "workflow-run-"
                    f"{item.get('databaseId', 'unknown')}"
                )
            )

            records.append(
                {
                    "name": workflow_name,
                    "state": (
                        item.get(
                            "conclusion"
                        )
                        or item.get(
                            "status"
                        )
                        or "unknown"
                    ),
                    "bucket": bucket,
                    "link": (
                        item.get("url")
                        or ""
                    ),
                    "source": (
                        "workflow_run_fallback"
                    ),
                    "databaseId": (
                        item.get(
                            "databaseId"
                        )
                    ),
                    "headSha": (
                        item.get(
                            "headSha"
                        )
                    ),
                    "event": (
                        item.get(
                            "event"
                        )
                    ),
                }
            )

        return records

    def checks(
        self,
        worktree: Path,
        pr: int,
    ) -> tuple[str, list[dict]]:
        # -------------------------------------------------
        # Primary source
        # -------------------------------------------------
        #
        # Prefer gh pr checks because it directly reports
        # checks associated with the pull request.
        r = self._run(
            [
                "gh",
                "pr",
                "checks",
                str(pr),
                "--json",
                "name,state,bucket,link",
            ],
            worktree,
        )

        primary = self._json_list(
            r.stdout
        )

        if primary:
            return (
                self._state_from_check_records(
                    primary,
                    r.returncode,
                ),
                primary,
            )

        # -------------------------------------------------
        # GitHub Actions fallback
        # -------------------------------------------------
        #
        # Some GitHub App/API combinations can return an
        # empty gh pr checks result even while an Actions
        # workflow exists for the PR.
        #
        # Resolve the exact PR head SHA and query Actions
        # runs for that commit instead.
        head_sha = self._pr_head_sha(
            worktree,
            pr,
        )

        fallback = (
            self._workflow_runs_for_pr_head(
                worktree,
                head_sha,
            )
        )

        if fallback:
            return (
                self._state_from_check_records(
                    fallback
                ),
                fallback,
            )

        # If gh itself explicitly reports pending but
        # neither source has visible records yet, preserve
        # that pending state.
        if r.returncode == 8:
            return "pending", []

        # No discoverable CI evidence must never be treated
        # as green.
        return "none", []

    def failed_run_logs(
        self,
        worktree: Path,
        branch: str,
        head_sha: str,
        max_runs: int = 3,
    ) -> str:
        # Prefer pull-request-triggered failures so a
        # separate push workflow for the same commit does
        # not accidentally provide unrelated logs.
        r = self._run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                branch,
                "--commit",
                head_sha,
                "--event",
                "pull_request",
                "--status",
                "failure",
                "--json",
                (
                    "databaseId,headSha,"
                    "workflowName,conclusion"
                ),
                "--limit",
                str(max_runs),
            ],
            worktree,
        )

        if (
            not r.ok
            or not r.stdout.strip()
        ):
            return ""

        runs = self._json_list(
            r.stdout
        )

        chunks: list[str] = []

        for item in runs[:max_runs]:
            run_id = item.get(
                "databaseId"
            )

            if not run_id:
                continue

            logs = self._run(
                [
                    "gh",
                    "run",
                    "view",
                    str(run_id),
                    "--log-failed",
                ],
                worktree,
            )

            if logs.stdout.strip():
                chunks.append(
                    "Workflow: "
                    f"{item.get('workflowName') or run_id}"
                    "\n"
                    f"{logs.stdout}"
                )

        return "\n\n".join(
            chunks
        )

    def pr_state(
        self,
        worktree: Path,
        pr: int,
    ) -> dict:
        r = self._run(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                (
                    "mergeable,"
                    "mergeStateStatus,"
                    "state,"
                    "headRefOid"
                ),
            ],
            worktree,
        )

        if not r.ok:
            raise RuntimeError(
                r.stderr
            )

        return json.loads(
            r.stdout
        )

    def merge(
        self,
        worktree: Path,
        pr: int,
        method: str,
        head_sha: str,
    ) -> None:
        flag = {
            "squash": "--squash",
            "merge": "--merge",
            "rebase": "--rebase",
        }.get(
            method,
            "--squash",
        )

        r = self._run(
            [
                "gh",
                "pr",
                "merge",
                str(pr),
                flag,
                "--delete-branch",
                "--match-head-commit",
                head_sha,
            ],
            worktree,
        )

        if not r.ok:
            raise RuntimeError(
                r.stderr
            )