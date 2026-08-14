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

    @staticmethod
    def _parse_json_object(
        raw: str,
        context: str,
    ) -> dict:
        if not raw.strip():
            raise RuntimeError(
                f"{context} returned an empty response."
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{context} returned invalid JSON: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                f"{context} returned unexpected JSON type: "
                f"{type(data).__name__}"
            )

        return data

    @staticmethod
    def _parse_json_list(
        raw: str,
        context: str,
    ) -> list[dict]:
        if not raw.strip():
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{context} returned invalid JSON: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise RuntimeError(
                f"{context} returned unexpected JSON type: "
                f"{type(data).__name__}"
            )

        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    @staticmethod
    def _command_error(
        prefix: str,
        result,
    ) -> RuntimeError:
        detail = (
            result.stderr
            or result.stdout
            or "unknown error"
        ).strip()

        return RuntimeError(
            f"{prefix}: {detail}"
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
            raise self._command_error(
                "Failed to read GitHub issue",
                r,
            )

        return self._parse_json_object(
            r.stdout,
            "gh issue view",
        )

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
            raise self._command_error(
                "Failed to create GitHub pull request",
                r,
            )

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
            raise self._command_error(
                "Failed to resolve created pull request number",
                view,
            )

        try:
            return int(
                view.stdout.strip()
            )
        except ValueError as exc:
            raise RuntimeError(
                "GitHub returned an invalid pull request "
                f"number: {view.stdout!r}"
            ) from exc

    @staticmethod
    def _state_from_check_records(
        data: list[dict],
        returncode: int = 0,
    ) -> str:
        buckets = {
            str(
                item.get("bucket")
                or ""
            ).lower()
            for item in data
        }

        buckets.discard("")

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
    def _check_run_bucket(
        check_run: dict,
    ) -> str:
        status = str(
            check_run.get("status")
            or ""
        ).lower()

        conclusion = str(
            check_run.get("conclusion")
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

        # A completed run without a recognized
        # successful conclusion is not sufficient
        # evidence for auto-merge.
        if status == "completed":
            return "fail"

        # Unknown non-terminal states are treated
        # conservatively as pending.
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
            raise self._command_error(
                f"Failed to resolve head SHA for PR #{pr}",
                r,
            )

        return r.stdout.strip()

    def _api_check_runs_for_ref(
        self,
        worktree: Path,
        head_sha: str,
        pr: int,
    ) -> list[dict]:
        # Query the Checks REST API directly.
        #
        # This avoids relying only on
        # `gh pr checks` when the CLI reports
        # an empty list even though GitHub has
        # actual check runs for the PR head SHA.
        r = self._run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                (
                    "repos/{owner}/{repo}/commits/"
                    f"{head_sha}/check-runs"
                ),
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                "X-GitHub-Api-Version: 2026-03-10",
                "-f",
                "per_page=100",
                "-f",
                "filter=latest",
            ],
            worktree,
        )

        if not r.ok:
            raise self._command_error(
                (
                    "GitHub Checks API query failed "
                    f"for PR #{pr} ({head_sha})"
                ),
                r,
            )

        payload = self._parse_json_object(
            r.stdout,
            "GitHub Checks API",
        )

        raw_runs = payload.get(
            "check_runs",
            [],
        )

        if not isinstance(
            raw_runs,
            list,
        ):
            raise RuntimeError(
                "GitHub Checks API response has "
                "invalid check_runs data."
            )

        records: list[dict] = []

        for item in raw_runs:
            if not isinstance(
                item,
                dict,
            ):
                continue

            # GitHub check runs may include explicit
            # PR association metadata.
            #
            # If it exists, only use checks related
            # to this PR.
            #
            # Some providers omit this array entirely,
            # so missing/empty metadata is not discarded.
            pull_requests = item.get(
                "pull_requests"
            )

            if (
                isinstance(
                    pull_requests,
                    list,
                )
                and pull_requests
            ):
                associated_numbers = {
                    p.get("number")
                    for p in pull_requests
                    if isinstance(
                        p,
                        dict,
                    )
                }

                if (
                    pr
                    not in associated_numbers
                ):
                    continue

            app = item.get("app")

            app_slug = (
                app.get("slug")
                if isinstance(
                    app,
                    dict,
                )
                else None
            )

            records.append(
                {
                    "name": (
                        item.get("name")
                        or (
                            "check-run-"
                            f"{item.get('id', 'unknown')}"
                        )
                    ),
                    "state": (
                        item.get(
                            "conclusion"
                        )
                        or item.get(
                            "status"
                        )
                        or "unknown"
                    ),
                    "bucket": (
                        self._check_run_bucket(
                            item
                        )
                    ),
                    "link": (
                        item.get(
                            "html_url"
                        )
                        or item.get(
                            "details_url"
                        )
                        or ""
                    ),
                    "source": (
                        "checks_api"
                    ),
                    "databaseId": (
                        item.get("id")
                    ),
                    "headSha": (
                        item.get(
                            "head_sha"
                        )
                        or head_sha
                    ),
                    "app": (
                        app_slug
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
        # Primary CI source
        # -------------------------------------------------
        #
        # gh pr checks is still preferred because
        # it is PR-specific and can include checks
        # from providers other than GitHub Actions.
        primary_result = self._run(
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

        primary = (
            self._parse_json_list(
                primary_result.stdout,
                "gh pr checks",
            )
        )

        if primary:
            return (
                self._state_from_check_records(
                    primary,
                    primary_result.returncode,
                ),
                primary,
            )

        # -------------------------------------------------
        # Direct GitHub Checks API fallback
        # -------------------------------------------------
        #
        # Resolve the exact PR head SHA and ask the
        # GitHub Checks REST API directly.
        #
        # Unlike the previous fallback, an API error
        # is NOT converted silently into an empty list.
        head_sha = self._pr_head_sha(
            worktree,
            pr,
        )

        # Preserve existing no-check behavior for
        # a successful-but-empty gh response.
        #
        # This also keeps the existing adapter unit
        # test compatible.
        if not head_sha:
            if (
                primary_result.returncode
                == 8
            ):
                return "pending", []

            return "none", []

        fallback = (
            self._api_check_runs_for_ref(
                worktree,
                head_sha,
                pr,
            )
        )

        if fallback:
            return (
                self._state_from_check_records(
                    fallback
                ),
                fallback,
            )

        # gh pr checks explicitly indicates pending
        # using return code 8.
        if (
            primary_result.returncode
            == 8
        ):
            return "pending", []

        # Neither source produced CI evidence.
        return "none", []

    def _api_workflow_runs_for_head(
        self,
        worktree: Path,
        head_sha: str,
        event: str = "pull_request",
        per_page: int = 100,
    ) -> list[dict]:
        r = self._run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                (
                    "repos/{owner}/{repo}"
                    "/actions/runs"
                ),
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                "X-GitHub-Api-Version: 2026-03-10",
                "-f",
                f"head_sha={head_sha}",
                "-f",
                f"event={event}",
                "-f",
                f"per_page={per_page}",
            ],
            worktree,
        )

        if not r.ok:
            raise self._command_error(
                (
                    "GitHub Actions API query "
                    "failed for commit "
                    f"{head_sha}"
                ),
                r,
            )

        payload = self._parse_json_object(
            r.stdout,
            "GitHub Actions API",
        )

        runs = payload.get(
            "workflow_runs",
            [],
        )

        if not isinstance(
            runs,
            list,
        ):
            raise RuntimeError(
                "GitHub Actions API response has "
                "invalid workflow_runs data."
            )

        return [
            item
            for item in runs
            if isinstance(
                item,
                dict,
            )
        ]

    def failed_run_logs(
        self,
        worktree: Path,
        branch: str,
        head_sha: str,
        max_runs: int = 3,
    ) -> str:
        # branch remains in the method signature
        # for compatibility with Orchestrator.
        _ = branch

        # Discover workflow runs directly through
        # the GitHub Actions REST API.
        #
        # GitHub supports filtering repository
        # workflow runs by both head SHA and event.
        try:
            runs = (
                self._api_workflow_runs_for_head(
                    worktree,
                    head_sha,
                    event="pull_request",
                )
            )
        except RuntimeError as exc:
            # Do not silently hide log-discovery
            # errors. Send the diagnostic into the
            # CI repair context instead.
            return (
                "Unable to retrieve GitHub Actions "
                f"run metadata: {exc}"
            )

        failed_runs = [
            item
            for item in runs
            if str(
                item.get(
                    "conclusion"
                )
                or ""
            ).lower()
            in {
                "failure",
                "cancelled",
                "timed_out",
                "action_required",
                "stale",
                "startup_failure",
            }
        ]

        # Explicit sorting keeps behavior stable
        # if the REST API ordering changes.
        failed_runs.sort(
            key=lambda item: str(
                item.get(
                    "created_at"
                )
                or ""
            ),
            reverse=True,
        )

        chunks: list[str] = []

        for item in (
            failed_runs[:max_runs]
        ):
            run_id = item.get(
                "id"
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

            workflow_name = (
                item.get("name")
                or (
                    "workflow-run-"
                    f"{run_id}"
                )
            )

            if logs.stdout.strip():
                chunks.append(
                    (
                        f"Workflow: "
                        f"{workflow_name}\n"
                        f"{logs.stdout}"
                    )
                )

            elif not logs.ok:
                detail = (
                    logs.stderr
                    or (
                        "no failed-step "
                        "logs returned"
                    )
                ).strip()

                chunks.append(
                    (
                        f"Workflow: "
                        f"{workflow_name}\n"
                        "Unable to retrieve "
                        "failed-step logs: "
                        f"{detail}"
                    )
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
            raise self._command_error(
                (
                    "Failed to read state "
                    f"for PR #{pr}"
                ),
                r,
            )

        return (
            self._parse_json_object(
                r.stdout,
                "gh pr view",
            )
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
            raise self._command_error(
                f"Failed to merge PR #{pr}",
                r,
            )