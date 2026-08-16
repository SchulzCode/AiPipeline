from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from .agents import agent_models, build_agent
from .config import home_dir, load_config
from .context import ContextBuilder
from .discovery import (
    DISCOVERY_MARKER,
    DiscoveryResult,
    build_candidates,
    detect_duplicates,
    issue_body,
    parse_candidates,
    rank_candidates,
    within_bounds,
)
from .git_manager import GitManager
from .github import GitHubAdapter
from .knowledge import init_project_knowledge
from .merge_policy import MergeEvidence, merge_allowed
from .models import ContextClass, FailureCategory, Risk, Route, TaskContract, TaskStatus, TaskType
from .prompts import DISCOVERY_SUFFIX, IMPLEMENTER_SUFFIX, PLANNER_SUFFIX, REVIEWER_SUFFIX, SECURITY_SUFFIX
from .quality import QualityEngine
from .reliability import ReviewVerdict, looks_like_capacity_exhaustion, looks_transient, parse_review_verdict
from .repo_index import RepoIndexCache
from .router import acceptance_from_text, planner_required, route_task
from .security import SecurityEngine, scan_added_diff
from .setup_engine import SetupEngine
from .state import StateStore
from .util import truncate


class PipelineBlocked(RuntimeError):
    def __init__(
        self,
        message: str,
        category: FailureCategory = FailureCategory.STATE_INCONSISTENCY,
    ):
        super().__init__(message)
        self.category = category


class Orchestrator:
    def __init__(
        self,
        repo: Path,
        agent_override: str | None = None,
        state_observer: Callable[[str, dict], None] | None = None,
        github_env_provider: Callable[[], dict[str, str]] | None = None,
        model_override: str | None = None,
    ):
        self.repo = repo.resolve()
        self.home = home_dir()
        self.home.mkdir(parents=True, exist_ok=True)
        self.config = load_config(self.repo)

        if agent_override:
            self.config.agent = agent_override

        if model_override is not None:
            valid = {item.id for item in agent_models(self.config.agent) if item.id is not None}
            if model_override not in valid:
                raise ValueError(
                    f"Model {model_override!r} is not available for agent {self.config.agent!r}."
                )

        self.state = StateStore(
            self.home / "state" / "pipeline.db",
            observer=state_observer,
        )
        self.git = GitManager(
            self.repo,
            self.config.main_branch,
            self.home / "worktrees",
            self.config.command_timeout_seconds,
            env_provider=github_env_provider,
        )
        self.github = GitHubAdapter(
            self.repo,
            self.config.command_timeout_seconds,
            env_provider=github_env_provider,
            read_attempts=self.config.external_attempts,
            backoff_seconds=self.config.external_backoff_seconds,
        )
        self.index_cache = RepoIndexCache(self.home / "index")
        self.context = ContextBuilder(self.home / "global", self.index_cache)
        self.agent = build_agent(
            self.config.agent,
            self.config,
            model=model_override,
        )

    def _project(self) -> int:
        return self.state.project_id(
            self.repo,
            self.git.remote_url(),
        )

    def enqueue_prompt_task(self, prompt: str) -> str:
        task = self.state.create_task(
            self._project(),
            "prompt",
            prompt,
            title=prompt[:120],
        )
        return task["public_id"]

    def create_prompt_task(self, prompt: str) -> str:
        public_id = self.enqueue_prompt_task(prompt)
        self.run(public_id)
        return public_id

    def enqueue_issue_task(self, issue_number: int) -> tuple[str, list[str]]:
        issue = self.github.issue(issue_number)
        labels = [x.get("name", "") for x in issue.get("labels", [])]
        comments = truncate(
            "\n".join(c.get("body", "") for c in issue.get("comments", [])[-8:]),
            8000,
        )
        issue_body = truncate(issue.get("body") or "", 12000)
        body = issue_body + ("\n\nRecent comments:\n" + comments if comments else "")
        goal = truncate(f"{issue['title']}\n\n{body}".strip(), 22000)
        task = self.state.create_task(
            self._project(),
            "github_issue",
            goal,
            title=issue["title"],
            body=body,
            source_reference=str(issue_number),
        )
        task["_labels"] = labels
        return task["public_id"], labels

    def create_issue_task(self, issue_number: int) -> str:
        public_id, labels = self.enqueue_issue_task(issue_number)
        self.run(public_id, labels=labels)
        return public_id

    def enqueue_discovery_task(
        self,
        prompt: str = "Discover valuable, implementation-ready feature candidates for this repository.",
    ) -> str:
        task = self.state.create_task(
            self._project(),
            "discovery",
            prompt,
            title="Feature discovery",
        )
        return task["public_id"]

    def create_discovery_task(self) -> DiscoveryResult:
        public_id = self.enqueue_discovery_task()
        return self.run_discovery(public_id)

    def _record_checks(self, task_db_id: int, kind: str, results) -> bool:
        all_ok = True
        for name, result in results:
            status = "PASS" if result.ok else "FAIL"
            all_ok &= result.ok
            summary = truncate(
                (result.stdout or "") + "\n" + (result.stderr or ""),
                9000,
            )
            self.state.check(
                task_db_id,
                kind,
                name,
                status,
                str(result.command),
                result.returncode,
                summary,
            )
        return all_ok

    @staticmethod
    def _review_pass(output: str) -> bool:
        return parse_review_verdict(output).verdict == ReviewVerdict.PASS

    def _validate_config(self) -> None:
        if self.config.merge_method not in {"squash", "merge", "rebase"}:
            raise PipelineBlocked(
                f"Unsupported merge method: {self.config.merge_method}",
                FailureCategory.CONFIGURATION,
            )
        numeric = {
            "implementation_attempts": self.config.implementation_attempts,
            "verification_attempts": self.config.verification_attempts,
            "review_attempts": self.config.review_attempts,
            "ci_attempts": self.config.ci_attempts,
            "external_attempts": self.config.external_attempts,
            "ci_timeout_seconds": self.config.ci_timeout_seconds,
            "ci_registration_grace_seconds": self.config.ci_registration_grace_seconds,
            "planner_attempts": self.config.planner_attempts,
            "discovery_attempts": self.config.discovery_attempts,
        }
        for name, value in numeric.items():
            minimum = (
                1
                if name in {
                    "implementation_attempts", "external_attempts", "ci_timeout_seconds",
                    "planner_attempts", "discovery_attempts",
                }
                else 0
            )
            if value < minimum:
                raise PipelineBlocked(
                    f"Invalid configuration: {name}={value} (minimum {minimum}).",
                    FailureCategory.CONFIGURATION,
                )
        valid_context_classes = {c.value for c in ContextClass}
        invalid_classes = set(self.config.planner_context_classes) - valid_context_classes
        if invalid_classes:
            raise PipelineBlocked(
                f"Invalid planning.context_classes entries: {sorted(invalid_classes)}.",
                FailureCategory.CONFIGURATION,
            )
        if self.config.discovery_max_candidates < 1:
            raise PipelineBlocked(
                f"Invalid configuration: discovery.max_candidates={self.config.discovery_max_candidates} (minimum 1).",
                FailureCategory.CONFIGURATION,
            )
        if not (0 <= self.config.discovery_max_new_issues <= self.config.discovery_max_candidates):
            raise PipelineBlocked(
                "Invalid configuration: discovery.max_new_issues must be between 0 and "
                f"discovery.max_candidates ({self.config.discovery_max_candidates}).",
                FailureCategory.CONFIGURATION,
            )
        if not (0 <= self.config.discovery_max_auto_implement <= self.config.discovery_max_new_issues):
            raise PipelineBlocked(
                "Invalid configuration: discovery.max_auto_implement must be between 0 and "
                f"discovery.max_new_issues ({self.config.discovery_max_new_issues}).",
                FailureCategory.CONFIGURATION,
            )
        if self.config.discovery_max_risk not in {r.value for r in Risk}:
            raise PipelineBlocked(
                f"Invalid discovery.max_risk: {self.config.discovery_max_risk!r}.",
                FailureCategory.CONFIGURATION,
            )
        if self.config.discovery_max_context_class not in valid_context_classes:
            raise PipelineBlocked(
                f"Invalid discovery.max_context_class: {self.config.discovery_max_context_class!r}.",
                FailureCategory.CONFIGURATION,
            )
        for group_name, commands in {
            "setup": self.config.setup_commands,
            "quality": self.config.quality_commands,
            "security": self.config.security_commands,
        }.items():
            for name, command in commands.items():
                if not isinstance(command, str) or not command.strip():
                    raise PipelineBlocked(
                        f"Invalid {group_name} command {name!r}: command must be a non-empty string.",
                        FailureCategory.CONFIGURATION,
                    )

    def _preflight(self) -> None:
        self._validate_config()
        try:
            self.git.preflight()
        except Exception as exc:
            category = (
                FailureCategory.TRANSIENT_EXTERNAL
                if looks_transient(str(exc))
                else FailureCategory.ENVIRONMENT
            )
            raise PipelineBlocked(f"Git preflight failed: {exc}", category) from exc
        try:
            self.github.preflight(self.repo)
        except Exception as exc:
            category = (
                FailureCategory.TRANSIENT_EXTERNAL
                if looks_transient(str(exc))
                else FailureCategory.CONFIGURATION
            )
            raise PipelineBlocked(f"GitHub preflight failed: {exc}", category) from exc

    def _diff_hash(self, worktree: Path) -> str:
        return hashlib.sha256(self.git.diff(worktree).encode("utf-8")).hexdigest()

    def _run_local_gates(
        self,
        task_db_id: int,
        worktree: Path,
        quality: QualityEngine,
        security: SecurityEngine,
        quality_kind: str,
        security_kind: str,
    ) -> tuple[bool, bool, bool, bool, str]:
        qresults = quality.execute(worktree)
        quality_ok = bool(qresults) and self._record_checks(
            task_db_id,
            quality_kind,
            qresults,
        )

        diff = self.git.diff(worktree)
        secret_findings = scan_added_diff(diff)
        for finding in secret_findings:
            self.state.finding(task_db_id, "secret_scan", "HIGH", finding)
        secret_ok = not secret_findings
        self.state.check(
            task_db_id,
            security_kind,
            "added-diff-secret-scan",
            "PASS" if secret_ok else "FAIL",
            summary="\n".join(secret_findings),
        )

        sresults = security.execute_commands(worktree)
        sec_cmd_ok = (
            self._record_checks(task_db_id, security_kind, sresults)
            if sresults
            else True
        )

        failures = [
            truncate((r.stdout or "") + "\n" + (r.stderr or ""), 5000)
            for _, r in (qresults + sresults)
            if not r.ok
        ]
        if not qresults:
            failures.append(
                "No configured or autodetected quality command produced a passing result."
            )
        failures.extend(secret_findings)
        feedback = "\n".join(item for item in failures if item.strip())
        ok = quality_ok and secret_ok and sec_cmd_ok
        return ok, quality_ok, secret_ok, sec_cmd_ok, feedback

    def _ensure_local_gates(
        self,
        task_db_id: int,
        worktree: Path,
        contract: TaskContract,
        quality: QualityEngine,
        security: SecurityEngine,
        *,
        quality_kind: str,
        security_kind: str,
        max_repairs: int,
        failure_category: FailureCategory,
        failure_message: str,
    ) -> tuple[bool, bool, bool]:
        repairs = 0
        last_feedback = ""

        while True:
            ok, quality_ok, secret_ok, sec_cmd_ok, feedback = self._run_local_gates(
                task_db_id,
                worktree,
                quality,
                security,
                quality_kind,
                security_kind,
            )
            if ok:
                return quality_ok, secret_ok, sec_cmd_ok

            last_feedback = feedback
            if repairs >= max_repairs:
                raise PipelineBlocked(
                    f"{failure_message} {truncate(last_feedback, 2000)}".strip(),
                    failure_category,
                )

            repairs += 1
            fix_prompt = (
                self.context.build(
                    worktree,
                    contract,
                    "IMPLEMENTER",
                    self.git.diff(worktree),
                    feedback,
                )
                + "\n\n"
                + IMPLEMENTER_SUFFIX
            )
            fix = self._agent_run(
                task_db_id,
                "IMPLEMENTER",
                fix_prompt,
                worktree,
                repairs,
            )
            self.state.event(
                task_db_id,
                "GATE_REMEDIATION",
                f"attempt={repairs} rc={fix.returncode}\n{truncate(fix.output, 5000)}",
            )

    def _invoke_review(
        self,
        task_db_id: int,
        role: str,
        event_name: str,
        prompt: str,
        worktree: Path,
        logical_attempt: int,
    ) -> tuple[ReviewVerdict, str, str]:
        before_hash = self._diff_hash(worktree)
        result = self._agent_run(
            task_db_id,
            role,
            prompt,
            worktree,
            logical_attempt,
        )
        after_hash = self._diff_hash(worktree)
        if after_hash != before_hash:
            raise PipelineBlocked(
                f"{role} modified repository state despite being a read-only gate.",
                FailureCategory.STATE_INCONSISTENCY,
            )

        self.state.event(task_db_id, event_name, truncate(result.output, 7000))

        if not result.ok:
            # Transport/runtime failures are retried once without consuming a
            # remediation cycle. They are not code-review findings.
            retry = self._agent_run(
                task_db_id,
                role,
                prompt,
                worktree,
                logical_attempt,
            )
            if self._diff_hash(worktree) != before_hash:
                raise PipelineBlocked(
                    f"{role} modified repository state during retry.",
                    FailureCategory.STATE_INCONSISTENCY,
                )
            self.state.event(
                task_db_id,
                event_name,
                "runtime_retry=1\n" + truncate(retry.output, 7000),
            )
            result = retry
            if not result.ok:
                raise PipelineBlocked(
                    f"{role} failed to execute twice: {truncate(result.output, 1500)}",
                    FailureCategory.ENVIRONMENT,
                )

        parsed = parse_review_verdict(result.output)
        if parsed.verdict != ReviewVerdict.PROTOCOL_ERROR:
            return parsed.verdict, result.output, before_hash

        correction = (
            prompt
            + "\n\nPROTOCOL CORRECTION: Your previous response could not be parsed. "
            "Do not change your review conclusion. Return only the required JSON object with "
            "verdict PASS or FINDINGS and a findings array."
        )
        corrected = self._agent_run(
            task_db_id,
            role,
            correction,
            worktree,
            logical_attempt,
        )
        if self._diff_hash(worktree) != before_hash:
            raise PipelineBlocked(
                f"{role} modified repository state during protocol retry.",
                FailureCategory.STATE_INCONSISTENCY,
            )
        self.state.event(
            task_db_id,
            event_name,
            "protocol_retry=1\n" + truncate(corrected.output, 7000),
        )
        if not corrected.ok:
            raise PipelineBlocked(
                f"{role} protocol retry failed to execute.",
                FailureCategory.ENVIRONMENT,
            )
        parsed = parse_review_verdict(corrected.output)
        if parsed.verdict == ReviewVerdict.PROTOCOL_ERROR:
            raise PipelineBlocked(
                parsed.reason or f"{role} returned an invalid verdict twice.",
                FailureCategory.AGENT_PROTOCOL,
            )
        return parsed.verdict, corrected.output, before_hash

    def _review_gate(
        self,
        task_db_id: int,
        role: str,
        event_name: str,
        suffix: str,
        contract: TaskContract,
        worktree: Path,
        quality: QualityEngine,
        security: SecurityEngine,
        *,
        category: FailureCategory,
        failure_message: str,
    ) -> tuple[str, int]:
        review_number = 0
        remediations = 0

        while True:
            review_number += 1
            diff = self.git.diff(worktree)
            prompt = (
                self.context.build(
                    worktree,
                    contract,
                    role,
                    diff,
                )
                + "\n\n"
                + suffix
            )
            verdict, raw_output, diff_hash = self._invoke_review(
                task_db_id,
                role,
                event_name,
                prompt,
                worktree,
                review_number,
            )
            if verdict == ReviewVerdict.PASS:
                return diff_hash, remediations

            # The budget counts code remediations, not reviewer invocations.
            # Therefore the diff produced by the final permitted remediation
            # always receives one more read-only confirmation review.
            if remediations >= self.config.review_attempts:
                raise PipelineBlocked(failure_message, category)

            remediations += 1
            fix_prompt = (
                self.context.build(
                    worktree,
                    contract,
                    "IMPLEMENTER",
                    diff,
                    raw_output,
                )
                + "\n\n"
                + IMPLEMENTER_SUFFIX
            )
            fix = self._agent_run(
                task_db_id,
                "IMPLEMENTER",
                fix_prompt,
                worktree,
                remediations,
            )
            self.state.event(
                task_db_id,
                f"{event_name}_REMEDIATION",
                f"attempt={remediations} rc={fix.returncode}\n{truncate(fix.output, 5000)}",
            )
            if not fix.ok:
                continue

            self._ensure_local_gates(
                task_db_id,
                worktree,
                contract,
                quality,
                security,
                quality_kind="quality-review-repair",
                security_kind="security-review-repair",
                max_repairs=self.config.verification_attempts,
                failure_category=FailureCategory.QUALITY_FAILURE,
                failure_message="Review remediation could not restore deterministic local gates.",
            )

    def _confirmation_review(
        self,
        task_db_id: int,
        role: str,
        event_name: str,
        suffix: str,
        contract: TaskContract,
        worktree: Path,
        *,
        category: FailureCategory,
        message: str,
    ) -> str:
        diff = self.git.diff(worktree)
        prompt = (
            self.context.build(worktree, contract, role, diff)
            + "\n\n"
            + suffix
            + "\nThis is a final read-only confirmation. Do not propose or perform remediation."
        )
        verdict, _, diff_hash = self._invoke_review(
            task_db_id,
            role,
            event_name,
            prompt,
            worktree,
            999,
        )
        if verdict != ReviewVerdict.PASS:
            raise PipelineBlocked(message, category)
        return diff_hash

    def _wait_for_pr_head(self, worktree: Path, pr: int, expected_sha: str) -> dict:
        deadline = time.time() + min(90, self.config.ci_timeout_seconds)
        last: dict = {}
        while time.time() < deadline:
            try:
                last = self.github.pr_state(worktree, pr)
            except Exception as exc:
                if looks_transient(str(exc)):
                    time.sleep(2)
                    continue
                raise PipelineBlocked(
                    f"Unable to read PR #{pr} state: {exc}",
                    FailureCategory.REMOTE_STATE_MISMATCH,
                ) from exc
            if str(last.get("state") or "").upper() == "MERGED":
                return last
            if str(last.get("headRefOid") or "") == expected_sha:
                return last
            time.sleep(2)
        raise PipelineBlocked(
            f"PR #{pr} head did not converge to expected commit {expected_sha}; got {last.get('headRefOid')!r}.",
            FailureCategory.REMOTE_STATE_MISMATCH,
        )

    def _wait_for_ci(self, worktree: Path, pr: int) -> tuple[str, list[dict]]:
        deadline = time.time() + self.config.ci_timeout_seconds
        registration_deadline = min(
            deadline,
            time.time() + self.config.ci_registration_grace_seconds,
        )
        try:
            state, checks = self.github.checks(worktree, pr)
            while state == "none" and time.time() < registration_deadline:
                time.sleep(5)
                state, checks = self.github.checks(worktree, pr)
            while state == "pending" and time.time() < deadline:
                time.sleep(15)
                state, checks = self.github.checks(worktree, pr)
        except Exception as exc:
            category = (
                FailureCategory.TRANSIENT_EXTERNAL
                if looks_transient(str(exc))
                else FailureCategory.REMOTE_STATE_MISMATCH
            )
            raise PipelineBlocked(f"CI state lookup failed: {exc}", category) from exc

        if state == "pending" and time.time() >= deadline:
            return "timeout", checks
        return state, checks

    def _semantic_gates_after_change(
        self,
        task_db_id: int,
        route,
        contract: TaskContract,
        worktree: Path,
        quality: QualityEngine,
        security: SecurityEngine,
    ) -> tuple[bool, bool]:
        review_ok = route.risk == Risk.LOW
        security_review_ok = route.risk != Risk.HIGH
        review_hash: str | None = None
        security_hash: str | None = None

        if route.risk in {Risk.MEDIUM, Risk.HIGH}:
            review_hash, _ = self._review_gate(
                task_db_id,
                "REVIEWER",
                "REVIEW",
                REVIEWER_SUFFIX,
                contract,
                worktree,
                quality,
                security,
                category=FailureCategory.REVIEW_FAILURE,
                failure_message="Independent review did not pass within the bounded remediation budget.",
            )
            review_ok = True

        if route.risk == Risk.HIGH:
            security_hash, _ = self._review_gate(
                task_db_id,
                "SECURITY_REVIEWER",
                "SECURITY_REVIEW",
                SECURITY_SUFFIX,
                contract,
                worktree,
                quality,
                security,
                category=FailureCategory.SECURITY_FAILURE,
                failure_message="Independent security review did not pass within the bounded remediation budget.",
            )
            security_review_ok = True

            current_hash = self._diff_hash(worktree)
            if review_hash != current_hash:
                review_hash = self._confirmation_review(
                    task_db_id,
                    "REVIEWER",
                    "REVIEW",
                    REVIEWER_SUFFIX,
                    contract,
                    worktree,
                    category=FailureCategory.REVIEW_FAILURE,
                    message="Final post-security confirmation review found unresolved issues.",
                )
            if security_hash != self._diff_hash(worktree):
                security_hash = self._confirmation_review(
                    task_db_id,
                    "SECURITY_REVIEWER",
                    "SECURITY_REVIEW",
                    SECURITY_SUFFIX,
                    contract,
                    worktree,
                    category=FailureCategory.SECURITY_FAILURE,
                    message="Final security confirmation no longer matches the current diff.",
                )

        return review_ok, security_review_ok

    def _run_implementer(
        self,
        task_db_id: int,
        implement_context: str,
        worktree: Path,
    ) -> None:
        """Run the bounded implementer retry loop.

        Returns normally once an attempt exits cleanly with a repository
        diff. On failure, a provider/session/quota capacity signal stops
        the retry loop immediately rather than consuming the remaining
        attempt budget, since an immediate retry will not resolve exhausted
        capacity. Any diff already present in the worktree (from this or an
        earlier attempt) is reported rather than masked, so a failure is
        never misreported as "no implementation exists" when partial work
        is actually recoverable.
        """
        last_output = ""
        capacity_exhausted = False
        for attempt in range(1, self.config.implementation_attempts + 1):
            result = self._agent_run(
                task_db_id,
                "IMPLEMENTER",
                implement_context,
                worktree,
                attempt,
            )
            last_output = result.output
            self.state.event(
                task_db_id,
                "IMPLEMENTER_RUN",
                f"attempt={attempt} rc={result.returncode}\n{truncate(result.output, 5000)}",
            )
            if result.ok and self.git.changed_files(worktree):
                return
            if not result.ok and looks_like_capacity_exhaustion(result.output):
                capacity_exhausted = True
                break

        has_existing_diff = bool(self.git.diff(worktree))
        if capacity_exhausted:
            message = "Implementation stopped because provider/session capacity appears exhausted."
            message += (
                " An existing repository diff was preserved for resumption."
                if has_existing_diff
                else " No repository changes had been produced yet."
            )
            raise PipelineBlocked(
                message + " " + truncate(last_output, 2000),
                FailureCategory.PROVIDER_CAPACITY,
            )
        if has_existing_diff:
            raise PipelineBlocked(
                "Implementation did not complete cleanly, but an existing repository diff "
                "was preserved rather than discarded. " + truncate(last_output, 2000),
                FailureCategory.AGENT_PROTOCOL,
            )
        raise PipelineBlocked(
            "Implementation did not produce a valid repository change. "
            + truncate(last_output, 2000),
            FailureCategory.AGENT_PROTOCOL,
        )

    def _run_planner(
        self,
        task_db_id: int,
        contract: TaskContract,
        worktree: Path,
    ) -> str:
        prompt = (
            self.context.build(worktree, contract, "PLANNER")
            + "\n\n"
            + PLANNER_SUFFIX
        )
        attempts = max(1, self.config.planner_attempts)
        last_output = ""

        for attempt in range(1, attempts + 1):
            before_hash = self._diff_hash(worktree)
            result = self._agent_run(task_db_id, "PLANNER", prompt, worktree, attempt)
            if self._diff_hash(worktree) != before_hash:
                raise PipelineBlocked(
                    "PLANNER modified repository state despite being a read-only stage.",
                    FailureCategory.STATE_INCONSISTENCY,
                )

            last_output = result.output
            self.state.event(
                task_db_id,
                "PLANNER_RUN",
                f"attempt={attempt} rc={result.returncode}\n{truncate(result.output, 7000)}",
            )
            if result.ok and result.output.strip():
                self.state.event(task_db_id, "PLAN", truncate(result.output, 12000))
                return result.output

        raise PipelineBlocked(
            f"Planner did not produce a usable plan within the bounded retry budget. {truncate(last_output, 1500)}".strip(),
            FailureCategory.PLANNING_FAILURE,
        )

    def _run_discovery_agent(
        self,
        task_db_id: int,
        contract: TaskContract,
        worktree: Path,
        max_candidates: int,
    ) -> list[dict]:
        prompt = (
            self.context.build(worktree, contract, "DISCOVERY_AGENT")
            + "\n\n"
            + DISCOVERY_SUFFIX
            + f"\nPropose at most {max_candidates} candidates."
        )
        attempts = max(1, self.config.discovery_attempts)
        last_output = ""

        for attempt in range(1, attempts + 1):
            before_hash = self._diff_hash(worktree)
            result = self._agent_run(task_db_id, "DISCOVERY_AGENT", prompt, worktree, attempt)
            if self._diff_hash(worktree) != before_hash:
                raise PipelineBlocked(
                    "DISCOVERY_AGENT modified repository state despite being a read-only stage.",
                    FailureCategory.STATE_INCONSISTENCY,
                )

            last_output = result.output
            self.state.event(
                task_db_id,
                "DISCOVERY_AGENT_RUN",
                f"attempt={attempt} rc={result.returncode}\n{truncate(result.output, 7000)}",
            )
            if result.ok:
                return parse_candidates(result.output)

        raise PipelineBlocked(
            f"Discovery agent did not produce a usable response within the bounded retry budget. {truncate(last_output, 1500)}".strip(),
            FailureCategory.AGENT_PROTOCOL,
        )

    def run_discovery(self, public_id: str) -> DiscoveryResult:
        """Run the bounded, read-only feature-discovery workflow.

        Explores the repository, proposes ranked/deduplicated feature
        candidates, and files the non-duplicate ones as structured GitHub
        issues. Never commits, pushes, opens a PR, or implements a discovered
        feature itself; a caller (CLI or the control-plane executor) decides
        separately whether to enqueue any of the returned
        ``handoff_issue_numbers`` into the normal Issue -> Task -> PR -> CI ->
        Merge pipeline, so this method never invokes ``run`` on itself or
        recurses into another discovery run.
        """

        task_row = self.state.task(public_id)
        task_db_id = int(task_row["id"])
        worktree: Path | None = None
        branch: str | None = None

        try:
            self._preflight()
            self.state.set_status(public_id, TaskStatus.DISCOVERING)

            route = Route(TaskType.DISCOVERY, Risk.LOW, ContextClass.NORMAL, ["general"], [])
            contract = TaskContract(
                id=public_id,
                goal=task_row["goal"],
                source="discovery",
                title=task_row.get("title"),
                body=task_row.get("body"),
                acceptance_criteria=[],
                route=route,
            )

            try:
                branch, worktree = self.git.prepare(public_id, task_row.get("title") or "discovery")
            except Exception as exc:
                raise PipelineBlocked(
                    f"Workspace preparation failed: {exc}",
                    FailureCategory.STATE_INCONSISTENCY,
                ) from exc
            self.git.assert_worktree(worktree, branch)

            max_candidates = max(1, self.config.discovery_max_candidates)
            raw_candidates = self._run_discovery_agent(task_db_id, contract, worktree, max_candidates)
            candidates = build_candidates(raw_candidates, max_candidates)
            candidates = rank_candidates(candidates)

            # Proposals are persisted before any GitHub call so a downstream
            # duplicate-lookup or issue-creation failure never loses generated
            # candidates; the task remains recoverable from this event alone.
            self.state.event(
                task_db_id,
                "DISCOVERY_CANDIDATES",
                json.dumps([c.to_dict() for c in candidates], ensure_ascii=False)[:16000],
            )

            try:
                existing_issues = self.github.list_issues(state="all", limit=200)
                existing_prs = self.github.list_recent_prs(state="all", limit=100)
            except Exception as exc:
                category = (
                    FailureCategory.TRANSIENT_EXTERNAL
                    if looks_transient(str(exc))
                    else FailureCategory.REMOTE_STATE_MISMATCH
                )
                raise PipelineBlocked(
                    f"Unable to read existing GitHub issues/pull requests for duplicate detection: {exc}",
                    category,
                ) from exc

            detect_duplicates(candidates, existing_issues, existing_prs)

            max_new_issues = max(0, min(self.config.discovery_max_new_issues, max_candidates))
            creation_targets = [c for c in candidates if c.status == "proposed"][:max_new_issues]

            # Repository labels are looked up once per run. Missing labels
            # (or an unavailable label list entirely) must never block issue
            # creation, and discovery never creates new repository labels -
            # proposed labels are only ever a filtered subset of what already
            # exists.
            available_labels: set[str] = set()
            if creation_targets:
                try:
                    available_labels = set(self.github.list_labels())
                except Exception as exc:
                    self.state.event(
                        task_db_id,
                        "DISCOVERY_LABELS_UNAVAILABLE",
                        truncate(
                            f"Unable to list repository labels; issues will be created without labels: {exc}",
                            2000,
                        ),
                    )

            for candidate in creation_targets:
                try:
                    valid_labels = [label for label in candidate.labels if label in available_labels]
                    skipped_labels = [label for label in candidate.labels if label not in available_labels]
                    if skipped_labels:
                        self.state.event(
                            task_db_id,
                            "DISCOVERY_LABELS_SKIPPED",
                            json.dumps({"key": candidate.key, "skipped": skipped_labels}),
                        )
                    issue = self.github.create_issue(
                        candidate.title,
                        issue_body(candidate),
                        valid_labels,
                        DISCOVERY_MARKER.format(key=candidate.key),
                    )
                    candidate.status = "created"
                    candidate.issue_number = int(issue.get("number") or 0) or None
                    candidate.issue_url = issue.get("url")
                    self.state.event(
                        task_db_id,
                        "DISCOVERY_ISSUE_CREATED",
                        json.dumps(
                            {
                                "key": candidate.key,
                                "issue_number": candidate.issue_number,
                                "issue_url": candidate.issue_url,
                            }
                        ),
                    )
                except Exception as exc:
                    # A single failed issue creation must not abort the run: the
                    # remaining candidates are still filed and the proposal
                    # (already persisted above) stays recoverable/retryable.
                    candidate.status = "failed"
                    candidate.error = truncate(str(exc), 2000)
                    self.state.event(
                        task_db_id,
                        "DISCOVERY_ISSUE_FAILED",
                        json.dumps({"key": candidate.key, "title": candidate.title, "error": candidate.error}),
                    )

            result = DiscoveryResult(candidates=candidates)
            result.created = [c for c in candidates if c.status == "created"]
            result.duplicates = [c for c in candidates if c.status == "duplicate"]
            result.failed = [c for c in candidates if c.status == "failed"]

            max_auto = max(0, min(self.config.discovery_max_auto_implement, max_new_issues))
            eligible = [
                c for c in result.created
                if within_bounds(c, self.config.discovery_max_risk, self.config.discovery_max_context_class)
            ]
            eligible.sort(key=lambda c: c.rank if c.rank is not None else 1 << 30)
            for candidate in eligible[:max_auto]:
                candidate.handoff = True
            result.handoff_issue_numbers = [
                c.issue_number for c in eligible[:max_auto] if c.issue_number is not None
            ]

            self.state.event(
                task_db_id,
                "DISCOVERY_SUMMARY",
                json.dumps(result.to_dict(), ensure_ascii=False)[:16000],
            )
            self.state.set_status(public_id, TaskStatus.DONE)
            return result

        except PipelineBlocked as exc:
            self.state.set_status(
                public_id,
                TaskStatus.BLOCKED,
                str(exc),
                failure_category=exc.category,
            )
            raise
        except Exception as exc:
            self.state.set_status(
                public_id,
                TaskStatus.FAILED,
                str(exc),
                failure_category=FailureCategory.TERMINAL_INTERNAL,
            )
            raise
        finally:
            # Discovery never commits, so the ephemeral worktree/branch can
            # always be reclaimed, unlike the normal run() flow where cleanup
            # is gated on a successful merge.
            if worktree and branch:
                try:
                    self.git.cleanup(worktree, branch)
                except Exception as exc:
                    self.state.event(task_db_id, "CLEANUP_WARNING", truncate(str(exc), 4000))

    def run(self, public_id: str, labels: list[str] | None = None) -> None:
        task_row = self.state.task(public_id)
        task_db_id = int(task_row["id"])
        worktree: Path | None = None
        branch: str | None = None

        try:
            self._preflight()
            self.state.set_status(public_id, TaskStatus.ROUTING)
            route = route_task(task_row["goal"], labels)
            acceptance = acceptance_from_text(task_row["goal"])
            self.state.update_task(
                public_id,
                task_type=route.task_type.value,
                risk=route.risk.value,
                context_class=route.context_class.value,
                scopes_json=json.dumps(route.scopes),
                gates_json=json.dumps(route.gates),
                acceptance_json=json.dumps(acceptance),
                failure_category=None,
            )
            contract = TaskContract(
                id=public_id,
                goal=task_row["goal"],
                source=task_row["source"],
                source_reference=task_row.get("source_reference"),
                title=task_row.get("title"),
                body=task_row.get("body"),
                acceptance_criteria=acceptance,
                route=route,
            )

            self.state.set_status(public_id, TaskStatus.PREPARING)
            try:
                branch, worktree = self.git.prepare(
                    public_id,
                    task_row.get("title") or task_row["goal"],
                )
            except Exception as exc:
                raise PipelineBlocked(
                    f"Workspace preparation failed: {exc}",
                    FailureCategory.STATE_INCONSISTENCY,
                ) from exc

            init_project_knowledge(
                worktree,
                main_branch=self.config.main_branch,
                agent=self.config.agent,
                auto_merge=self.config.auto_merge,
                merge_method=self.config.merge_method,
            )
            self.git.assert_worktree(worktree, branch)
            self.state.update_task(public_id, branch=branch, worktree=str(worktree))

            runtime_root = self.home / "runtime" / public_id
            status_before_setup = self.git.status(worktree)
            setup = SetupEngine(
                self.config.setup_commands,
                self.config.setup_auto,
                self.config.command_timeout_seconds,
                runtime_root,
            )
            setup_outcome = setup.execute(worktree)
            if setup_outcome.results:
                if not self._record_checks(task_db_id, "setup", setup_outcome.results):
                    raise PipelineBlocked(
                        "Project dependency/setup step failed. Configure .ai/config.yml setup.commands if autodetection is insufficient.",
                        FailureCategory.ENVIRONMENT,
                    )
            if self.git.status(worktree) != status_before_setup:
                raise PipelineBlocked(
                    "Project setup changed Git-visible files. Fix .gitignore or configure a non-mutating setup command.",
                    FailureCategory.STATE_INCONSISTENCY,
                )
            self.agent.runtime_env = setup_outcome.runtime_env

            self.state.set_status(public_id, TaskStatus.DISCOVERY)
            self.state.set_status(public_id, TaskStatus.PLANNING)
            plan_text = ""
            if planner_required(route.context_class, self.config):
                plan_text = self._run_planner(task_db_id, contract, worktree)
            self.state.set_status(public_id, TaskStatus.IMPLEMENTING)

            implement_context = (
                self.context.build(worktree, contract, "IMPLEMENTER", plan=plan_text)
                + "\n\n"
                + IMPLEMENTER_SUFFIX
            )
            self._run_implementer(task_db_id, implement_context, worktree)

            quality = QualityEngine(
                self.config.quality_commands,
                self.config.command_timeout_seconds,
                runtime_env=setup_outcome.runtime_env,
            )
            security = SecurityEngine(
                self.config.security_commands,
                self.config.command_timeout_seconds,
                runtime_env=setup_outcome.runtime_env,
            )

            self.state.set_status(public_id, TaskStatus.VERIFYING)
            quality_ok, secret_ok, sec_cmd_ok = self._ensure_local_gates(
                task_db_id,
                worktree,
                contract,
                quality,
                security,
                quality_kind="quality",
                security_kind="security",
                max_repairs=self.config.verification_attempts,
                failure_category=FailureCategory.QUALITY_FAILURE,
                failure_message="Verification retry budget exhausted.",
            )

            self.state.set_status(public_id, TaskStatus.REVIEWING)
            review_ok, security_review_ok = self._semantic_gates_after_change(
                task_db_id,
                route,
                contract,
                worktree,
                quality,
                security,
            )

            # Deterministic final gates are intentionally non-remediating: a
            # post-review code change would invalidate the semantic verdicts.
            final_ok, quality_ok, secret_ok, sec_cmd_ok, _ = self._run_local_gates(
                task_db_id,
                worktree,
                quality,
                security,
                "quality-final",
                "security-final",
            )
            if not final_ok:
                raise PipelineBlocked(
                    "Final local gates failed after semantic review.",
                    FailureCategory.QUALITY_FAILURE,
                )

            commit_sha = self.git.commit(
                worktree,
                f"{public_id}: {task_row.get('title') or task_row['goal'][:72]}",
            )
            self.git.push(worktree, branch)

            self.state.set_status(public_id, TaskStatus.PR_OPEN)
            body = self._pr_body(contract, route, task_row)
            try:
                pr = self.github.create_pr(
                    worktree,
                    task_row.get("title") or public_id,
                    body,
                    self.config.main_branch,
                )
            except Exception as exc:
                category = (
                    FailureCategory.TRANSIENT_EXTERNAL
                    if looks_transient(str(exc))
                    else FailureCategory.REMOTE_STATE_MISMATCH
                )
                raise PipelineBlocked(f"Pull request creation/reconciliation failed: {exc}", category) from exc
            self.state.update_task(public_id, pr_number=pr)
            self._wait_for_pr_head(worktree, pr, commit_sha)

            self.state.set_status(public_id, TaskStatus.CI)
            ci_repairs = 0
            ci_ok = False

            while True:
                state, checks = self._wait_for_ci(worktree, pr)
                self.state.event(task_db_id, "CI", json.dumps(checks)[:9000])
                if state == "pass":
                    ci_ok = True
                    break
                if state == "none":
                    raise PipelineBlocked(
                        "No GitHub CI checks were found after the registration grace period; refusing to merge without CI evidence.",
                        FailureCategory.REMOTE_STATE_MISMATCH,
                    )
                if state == "timeout":
                    raise PipelineBlocked(
                        "GitHub CI remained pending until the configured timeout.",
                        FailureCategory.TRANSIENT_EXTERNAL,
                    )
                if ci_repairs >= self.config.ci_attempts:
                    raise PipelineBlocked(
                        "CI failed after the bounded repair budget was exhausted.",
                        FailureCategory.QUALITY_FAILURE,
                    )

                ci_repairs += 1
                failure = json.dumps(
                    [c for c in checks if c.get("bucket") == "fail"],
                    indent=2,
                )
                failed_logs = self.github.failed_run_logs(
                    worktree,
                    branch,
                    self.git.head(worktree),
                )
                ci_context = "CI failure metadata:\n" + failure
                if failed_logs:
                    ci_context += "\n\nFailed GitHub Actions steps/logs:\n" + truncate(failed_logs, 12000)
                fix_prompt = (
                    self.context.build(
                        worktree,
                        contract,
                        "IMPLEMENTER",
                        self.git.diff(worktree),
                        ci_context,
                    )
                    + "\n\n"
                    + IMPLEMENTER_SUFFIX
                )
                fix = self._agent_run(
                    task_db_id,
                    "IMPLEMENTER",
                    fix_prompt,
                    worktree,
                    ci_repairs,
                )
                self.state.event(
                    task_db_id,
                    "CI_REMEDIATION",
                    f"attempt={ci_repairs} rc={fix.returncode}\n{truncate(fix.output, 5000)}",
                )
                if not fix.ok or not self.git.status(worktree).strip():
                    continue

                self._ensure_local_gates(
                    task_db_id,
                    worktree,
                    contract,
                    quality,
                    security,
                    quality_kind="quality-ci-fix",
                    security_kind="security-ci-fix",
                    max_repairs=self.config.verification_attempts,
                    failure_category=FailureCategory.QUALITY_FAILURE,
                    failure_message="CI repair could not restore local gates.",
                )
                review_ok, security_review_ok = self._semantic_gates_after_change(
                    task_db_id,
                    route,
                    contract,
                    worktree,
                    quality,
                    security,
                )
                final_ok, quality_ok, secret_ok, sec_cmd_ok, _ = self._run_local_gates(
                    task_db_id,
                    worktree,
                    quality,
                    security,
                    "quality-ci-final",
                    "security-ci-final",
                )
                if not final_ok:
                    raise PipelineBlocked(
                        "Final local gates failed after CI remediation review.",
                        FailureCategory.QUALITY_FAILURE,
                    )

                self.git.commit(worktree, f"{public_id}: fix CI")
                self.git.push(worktree, branch)
                commit_sha = self.git.head(worktree)
                self._wait_for_pr_head(worktree, pr, commit_sha)
                # Loop back to CI. Even the final permitted repair receives a
                # fresh CI verdict before the budget can terminate.

            pr_state = self._wait_for_pr_head(worktree, pr, commit_sha)
            merge_state = str(pr_state.get("state") or "").upper()
            mergeable_value = str(pr_state.get("mergeable") or "").upper()
            if merge_state == "OPEN" and mergeable_value in {"UNKNOWN", ""}:
                deadline = time.time() + min(60, self.config.ci_timeout_seconds)
                while time.time() < deadline and mergeable_value in {"UNKNOWN", ""}:
                    time.sleep(3)
                    pr_state = self._wait_for_pr_head(worktree, pr, commit_sha)
                    mergeable_value = str(pr_state.get("mergeable") or "").upper()
                    merge_state = str(pr_state.get("state") or "").upper()

            mergeable = (
                merge_state == "MERGED"
                or (merge_state == "OPEN" and mergeable_value == "MERGEABLE")
            )
            evidence = MergeEvidence(
                quality_passed=quality_ok,
                secret_scan_passed=secret_ok,
                security_commands_passed=sec_cmd_ok,
                review_passed=review_ok,
                security_review_passed=security_review_ok,
                ci_passed=ci_ok,
                mergeable=mergeable,
            )
            if not merge_allowed(evidence):
                raise PipelineBlocked(
                    f"Merge policy denied merge: {evidence}",
                    FailureCategory.STATE_INCONSISTENCY,
                )
            if not self.config.auto_merge:
                raise PipelineBlocked(
                    "All gates passed, but auto_merge=false in configuration.",
                    FailureCategory.CONFIGURATION,
                )

            self.state.set_status(public_id, TaskStatus.MERGING)
            try:
                self.github.merge(
                    worktree,
                    pr,
                    self.config.merge_method,
                    commit_sha,
                )
            except Exception as exc:
                category = (
                    FailureCategory.TRANSIENT_EXTERNAL
                    if looks_transient(str(exc))
                    else FailureCategory.REMOTE_STATE_MISMATCH
                )
                raise PipelineBlocked(f"Merge reconciliation failed: {exc}", category) from exc

            self.state.set_status(public_id, TaskStatus.POST_MERGE)
            deadline = time.time() + self.config.ci_timeout_seconds
            while time.time() < deadline:
                try:
                    post = self.github.pr_state(worktree, pr)
                except Exception as exc:
                    if looks_transient(str(exc)):
                        time.sleep(5)
                        continue
                    raise PipelineBlocked(
                        f"Unable to verify merged PR state: {exc}",
                        FailureCategory.REMOTE_STATE_MISMATCH,
                    ) from exc
                if str(post.get("state") or "").upper() == "MERGED":
                    self.state.set_status(public_id, TaskStatus.DONE)
                    break
                time.sleep(10)
            else:
                raise PipelineBlocked(
                    "PR passed all gates but did not reach MERGED state before timeout.",
                    FailureCategory.REMOTE_STATE_MISMATCH,
                )

        except PipelineBlocked as exc:
            self.state.set_status(
                public_id,
                TaskStatus.BLOCKED,
                str(exc),
                failure_category=exc.category,
            )
            raise
        except Exception as exc:
            self.state.set_status(
                public_id,
                TaskStatus.FAILED,
                str(exc),
                failure_category=FailureCategory.TERMINAL_INTERNAL,
            )
            raise
        finally:
            current = self.state.task(public_id)
            if current["status"] == TaskStatus.DONE and worktree and branch:
                try:
                    self.git.cleanup(worktree, branch)
                except Exception as exc:
                    # A successful remote merge must not be reclassified as a
                    # failed engineering task because local cleanup needs manual
                    # reconciliation. Preserve DONE and record the warning.
                    self.state.event(
                        task_db_id,
                        "CLEANUP_WARNING",
                        truncate(str(exc), 4000),
                    )

    def _agent_run(
        self,
        task_db_id: int,
        role: str,
        prompt: str,
        workspace: Path,
        attempt: int,
    ):
        run_id = self.state.start_run(
            task_db_id,
            role,
            self.agent.name,
            attempt,
        )
        try:
            result = self.agent.run(role, prompt, workspace)
            self.state.finish_run(
                run_id,
                "PASS" if result.ok else "FAIL",
                truncate(result.output, 5000),
            )
            self.state.record_usage(
                task_db_id,
                run_id,
                self.agent.name,
                result.input_tokens,
                result.output_tokens,
            )
            return result
        except Exception as exc:
            self.state.finish_run(run_id, "ERROR", str(exc))
            raise

    def _head(self, worktree: Path) -> str:
        return self.git.head(worktree)

    def _pr_body(self, contract: TaskContract, route, task_row: dict) -> str:
        closes = (
            f"Closes #{task_row['source_reference']}\n\n"
            if task_row.get("source") == "github_issue"
            else ""
        )
        criteria = "\n".join(f"- {item}" for item in contract.acceptance_criteria)
        return (
            f"{closes}"
            f"Automated by AIpipe {contract.id}.\n\n"
            f"## Goal\n{contract.goal[:3000]}\n\n"
            f"## Acceptance criteria\n{criteria}\n\n"
            f"## Routing\n"
            f"- Type: {route.task_type.value}\n"
            f"- Risk: {route.risk.value}\n"
            f"- Context: {route.context_class.value}\n"
            f"- Gates: {', '.join(route.gates)}\n\n"
            "Local quality, security and required independent review gates passed before this PR was opened. "
            "GitHub required checks must also pass before merge."
        )
