from __future__ import annotations

import json
import time
from pathlib import Path
from collections.abc import Callable

from .agents import build_agent
from .config import PipelineConfig, home_dir, load_config
from .context import ContextBuilder
from .git_manager import GitManager
from .github import GitHubAdapter
from .knowledge import init_project_knowledge
from .merge_policy import MergeEvidence, merge_allowed
from .models import Risk, TaskContract, TaskStatus
from .prompts import IMPLEMENTER_SUFFIX, REVIEWER_SUFFIX, SECURITY_SUFFIX
from .quality import QualityEngine
from .router import acceptance_from_text, route_task
from .security import SecurityEngine, scan_added_diff
from .setup_engine import SetupEngine
from .state import StateStore
from .util import truncate


class PipelineBlocked(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, repo: Path, agent_override: str | None = None, state_observer: Callable[[str, dict], None] | None = None, github_env_provider: Callable[[], dict[str, str]] | None = None):
        self.repo = repo.resolve()
        self.home = home_dir()
        self.home.mkdir(parents=True, exist_ok=True)
        self.config = load_config(self.repo)
        if agent_override:
            self.config.agent = agent_override
        self.state = StateStore(self.home / "state" / "pipeline.db", observer=state_observer)
        self.git = GitManager(self.repo, self.config.main_branch, self.home / "worktrees", self.config.command_timeout_seconds, env_provider=github_env_provider)
        self.github = GitHubAdapter(self.repo, self.config.command_timeout_seconds, env_provider=github_env_provider)
        self.context = ContextBuilder(self.home / "global")
        self.agent = build_agent(self.config.agent, self.config)

    def _project(self) -> int:
        return self.state.project_id(self.repo, self.git.remote_url())

    def enqueue_prompt_task(self, prompt: str) -> str:
        task = self.state.create_task(self._project(), "prompt", prompt, title=prompt[:120])
        return task["public_id"]

    def create_prompt_task(self, prompt: str) -> str:
        public_id = self.enqueue_prompt_task(prompt)
        self.run(public_id)
        return public_id

    def enqueue_issue_task(self, issue_number: int) -> tuple[str, list[str]]:
        issue = self.github.issue(issue_number)
        labels = [x.get("name", "") for x in issue.get("labels", [])]
        comments = truncate("\n".join(c.get("body", "") for c in issue.get("comments", [])[-8:]), 8000)
        issue_body = truncate(issue.get("body") or "", 12000)
        body = issue_body + ("\n\nRecent comments:\n" + comments if comments else "")
        goal = truncate(f"{issue['title']}\n\n{body}".strip(), 22000)
        task = self.state.create_task(
            self._project(), "github_issue", goal, title=issue["title"], body=body,
            source_reference=str(issue_number),
        )
        task["_labels"] = labels
        return task["public_id"], labels

    def create_issue_task(self, issue_number: int) -> str:
        public_id, labels = self.enqueue_issue_task(issue_number)
        self.run(public_id, labels=labels)
        return public_id

    def _record_checks(self, task_db_id: int, kind: str, results) -> bool:
        all_ok = True
        for name, r in results:
            status = "PASS" if r.ok else "FAIL"
            all_ok &= r.ok
            summary = truncate((r.stdout or "") + "\n" + (r.stderr or ""), 9000)
            self.state.check(task_db_id, kind, name, status, str(r.command), r.returncode, summary)
        return all_ok

    @staticmethod
    def _review_pass(output: str) -> bool:
        stripped = output.strip().upper()
        return stripped.startswith("PASS") and "FINDINGS" not in stripped

    def run(self, public_id: str, labels: list[str] | None = None) -> None:
        task_row = self.state.task(public_id)
        task_db_id = int(task_row["id"])
        worktree: Path | None = None
        branch: str | None = None
        try:
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
            branch, worktree = self.git.prepare(public_id, task_row.get("title") or task_row["goal"])
            init_project_knowledge(worktree, main_branch=self.config.main_branch, agent=self.config.agent, auto_merge=self.config.auto_merge, merge_method=self.config.merge_method)
            self.state.update_task(public_id, branch=branch, worktree=str(worktree))

            runtime_root = self.home / "runtime" / public_id
            status_before_setup = self.git.status(worktree)
            setup = SetupEngine(self.config.setup_commands, self.config.setup_auto, self.config.command_timeout_seconds, runtime_root)
            setup_outcome = setup.execute(worktree)
            if setup_outcome.results:
                setup_ok = self._record_checks(task_db_id, "setup", setup_outcome.results)
                if not setup_ok:
                    raise PipelineBlocked("Project dependency/setup step failed. Configure .ai/config.yml setup.commands if autodetection is insufficient.")
            if self.git.status(worktree) != status_before_setup:
                # Setup may generate ignored dependency/cache directories, but it may not
                # mutate tracked/unignored project state before the agent begins.
                raise PipelineBlocked("Project setup changed Git-visible files. Fix .gitignore or configure a non-mutating setup command.")
            self.agent.runtime_env = setup_outcome.runtime_env

            self.state.set_status(public_id, TaskStatus.DISCOVERY)
            self.state.set_status(public_id, TaskStatus.PLANNING)
            self.state.set_status(public_id, TaskStatus.IMPLEMENTING)
            implement_context = self.context.build(worktree, contract, "IMPLEMENTER") + "\n\n" + IMPLEMENTER_SUFFIX
            implemented = False
            last_output = ""
            for attempt in range(1, self.config.implementation_attempts + 1):
                result = self._agent_run(task_db_id, "IMPLEMENTER", implement_context, worktree, attempt)
                last_output = result.output
                self.state.event(task_db_id, "IMPLEMENTER_RUN", f"attempt={attempt} rc={result.returncode}\n{truncate(result.output, 5000)}")
                if result.ok and self.git.status(worktree).strip():
                    implemented = True
                    break
            if not implemented:
                raise PipelineBlocked("Implementation did not produce a valid repository change. " + truncate(last_output, 2000))

            quality = QualityEngine(self.config.quality_commands, self.config.command_timeout_seconds, runtime_env=setup_outcome.runtime_env)
            security = SecurityEngine(self.config.security_commands, self.config.command_timeout_seconds, runtime_env=setup_outcome.runtime_env)

            self.state.set_status(public_id, TaskStatus.VERIFYING)
            quality_ok = False
            verification_feedback = ""
            for attempt in range(1, self.config.verification_attempts + 1):
                qresults = quality.execute(worktree)
                quality_ok = bool(qresults) and self._record_checks(task_db_id, "quality", qresults)
                diff = self.git.diff(worktree)
                secret_findings = scan_added_diff(diff)
                for finding in secret_findings:
                    self.state.finding(task_db_id, "secret_scan", "HIGH", finding)
                secret_ok = not secret_findings
                self.state.check(task_db_id, "security", "added-diff-secret-scan", "PASS" if secret_ok else "FAIL", summary="\n".join(secret_findings))
                sresults = security.execute_commands(worktree)
                sec_cmd_ok = self._record_checks(task_db_id, "security", sresults) if sresults else True
                if quality_ok and secret_ok and sec_cmd_ok:
                    break
                failure_text = "\n".join(
                    truncate((r.stdout or "") + "\n" + (r.stderr or ""), 5000) for _, r in qresults + sresults if not r.ok
                ) + "\n" + "\n".join(secret_findings)
                verification_feedback = failure_text
                fix_prompt = self.context.build(worktree, contract, "IMPLEMENTER", self.git.diff(worktree), failure_text) + "\n\n" + IMPLEMENTER_SUFFIX
                fix = self._agent_run(task_db_id, "IMPLEMENTER", fix_prompt, worktree, attempt)
                if not fix.ok:
                    continue
            else:
                raise PipelineBlocked("Verification retry budget exhausted. " + truncate(verification_feedback, 2000))

            if not quality_ok:
                raise PipelineBlocked("No configured or autodetected quality command passed. Configure .ai/config.yml if autodetection is insufficient.")

            review_ok = route.risk == Risk.LOW
            security_review_ok = route.risk != Risk.HIGH
            self.state.set_status(public_id, TaskStatus.REVIEWING)

            if route.risk in {Risk.MEDIUM, Risk.HIGH}:
                for attempt in range(1, self.config.review_attempts + 1):
                    diff = self.git.diff(worktree)
                    prompt = self.context.build(worktree, contract, "REVIEWER", diff) + "\n\n" + REVIEWER_SUFFIX
                    review = self._agent_run(task_db_id, "REVIEWER", prompt, worktree, attempt)
                    review_ok = review.ok and self._review_pass(review.output)
                    self.state.event(task_db_id, "REVIEW", truncate(review.output, 7000))
                    if review_ok:
                        break
                    fix_prompt = self.context.build(worktree, contract, "IMPLEMENTER", diff, review.output) + "\n\n" + IMPLEMENTER_SUFFIX
                    fix = self._agent_run(task_db_id, "IMPLEMENTER", fix_prompt, worktree, attempt)
                    if not fix.ok:
                        continue
                    qresults = quality.execute(worktree)
                    quality_ok = bool(qresults) and self._record_checks(task_db_id, "quality", qresults)
                    if not quality_ok:
                        continue
                if not review_ok:
                    raise PipelineBlocked("Independent review did not pass within retry budget.")

            if route.risk == Risk.HIGH:
                for attempt in range(1, self.config.review_attempts + 1):
                    diff = self.git.diff(worktree)
                    prompt = self.context.build(worktree, contract, "SECURITY_REVIEWER", diff) + "\n\n" + SECURITY_SUFFIX
                    sreview = self._agent_run(task_db_id, "SECURITY_REVIEWER", prompt, worktree, attempt)
                    security_review_ok = sreview.ok and self._review_pass(sreview.output)
                    self.state.event(task_db_id, "SECURITY_REVIEW", truncate(sreview.output, 7000))
                    if security_review_ok:
                        break
                    fix_prompt = self.context.build(worktree, contract, "IMPLEMENTER", diff, sreview.output) + "\n\n" + IMPLEMENTER_SUFFIX
                    fix = self._agent_run(task_db_id, "IMPLEMENTER", fix_prompt, worktree, attempt)
                    if not fix.ok:
                        continue
                    qresults = quality.execute(worktree)
                    quality_ok = bool(qresults) and self._record_checks(task_db_id, "quality", qresults)
                    if not quality_ok or scan_added_diff(self.git.diff(worktree)):
                        continue
                if not security_review_ok:
                    raise PipelineBlocked("Independent security review did not pass within retry budget.")

            # Final deterministic re-verification. Durable knowledge, when warranted, is
            # updated by the implementer in the same reviewed diff; a separate knowledge
            # agent is intentionally avoided to save tokens.
            qresults = quality.execute(worktree)
            quality_ok = bool(qresults) and self._record_checks(task_db_id, "quality-final", qresults)
            diff = self.git.diff(worktree)
            final_secret_findings = scan_added_diff(diff)
            secret_ok = not final_secret_findings
            for finding in final_secret_findings:
                self.state.finding(task_db_id, "secret_scan", "HIGH", finding)
            sec_results = security.execute_commands(worktree)
            sec_cmd_ok = self._record_checks(task_db_id, "security-final", sec_results) if sec_results else True
            if not quality_ok or not secret_ok or not sec_cmd_ok:
                raise PipelineBlocked("Final local gates failed after review.")

            commit_sha = self.git.commit(worktree, f"{public_id}: {task_row.get('title') or task_row['goal'][:72]}")
            self.git.push(worktree, branch)

            self.state.set_status(public_id, TaskStatus.PR_OPEN)
            body = self._pr_body(contract, route, task_row)
            pr = self.github.create_pr(worktree, task_row.get("title") or public_id, body, self.config.main_branch)
            self.state.update_task(public_id, pr_number=pr)

            self.state.set_status(public_id, TaskStatus.CI)
            ci_ok = False
            for ci_attempt in range(1, self.config.ci_attempts + 1):
                deadline = time.time() + self.config.ci_timeout_seconds

                # GitHub Actions may need a few seconds after PR creation (or after
                # pushing a CI-fix commit) before check runs become visible. Treat
                # an initial "none" state as transient for a short registration
                # window rather than failing immediately.
                registration_deadline = min(deadline, time.time() + 60)

                state, checks = self.github.checks(worktree, pr)
                while state == "none" and time.time() < registration_deadline:
                    time.sleep(5)
                    state, checks = self.github.checks(worktree, pr)

                # Once checks are registered, wait for them to finish.
                while state == "pending" and time.time() < deadline:
                    time.sleep(15)
                    state, checks = self.github.checks(worktree, pr)

                self.state.event(task_db_id, "CI", json.dumps(checks)[:9000])

                if state == "pass":
                    ci_ok = True
                    break

                if state == "none":
                    raise PipelineBlocked(
                        "No GitHub CI checks were found after waiting for GitHub "
                        "Actions registration. Refusing to auto-merge without CI evidence."
                    )

                failure = json.dumps([c for c in checks if c.get("bucket") == "fail"], indent=2)
                failed_logs = self.github.failed_run_logs(worktree, branch, self._head(worktree))
                ci_context = "CI failure metadata:\n" + failure
                if failed_logs:
                    ci_context += "\n\nFailed GitHub Actions steps/logs:\n" + truncate(failed_logs, 12000)
                fix_prompt = self.context.build(worktree, contract, "IMPLEMENTER", self.git.diff(worktree), ci_context) + "\n\n" + IMPLEMENTER_SUFFIX
                fix = self._agent_run(task_db_id, "IMPLEMENTER", fix_prompt, worktree, ci_attempt)
                if not fix.ok or not self.git.status(worktree).strip():
                    continue
                qresults = quality.execute(worktree)
                quality_ok = bool(qresults) and self._record_checks(task_db_id, "quality-ci-fix", qresults)
                diff = self.git.diff(worktree)
                secret_ok = not scan_added_diff(diff)
                sec_results = security.execute_commands(worktree)
                sec_cmd_ok = self._record_checks(task_db_id, "security-ci-fix", sec_results) if sec_results else True
                if not quality_ok or not secret_ok or not sec_cmd_ok:
                    continue

                # A CI repair changed the reviewed code. Re-run semantic gates before pushing it.
                if route.risk in {Risk.MEDIUM, Risk.HIGH}:
                    rprompt = self.context.build(worktree, contract, "REVIEWER", diff) + "\n\n" + REVIEWER_SUFFIX
                    rereview = self._agent_run(task_db_id, "REVIEWER", rprompt, worktree, ci_attempt)
                    review_ok = rereview.ok and self._review_pass(rereview.output)
                    if not review_ok:
                        repair_prompt = self.context.build(worktree, contract, "IMPLEMENTER", diff, rereview.output) + "\n\n" + IMPLEMENTER_SUFFIX
                        repair = self._agent_run(task_db_id, "IMPLEMENTER", repair_prompt, worktree, ci_attempt)
                        if not repair.ok:
                            continue
                        qresults = quality.execute(worktree)
                        quality_ok = bool(qresults) and self._record_checks(task_db_id, "quality-ci-review-repair", qresults)
                        diff = self.git.diff(worktree)
                        if not quality_ok or scan_added_diff(diff):
                            continue
                        rprompt = self.context.build(worktree, contract, "REVIEWER", diff) + "\n\n" + REVIEWER_SUFFIX
                        rereview = self._agent_run(task_db_id, "REVIEWER", rprompt, worktree, ci_attempt)
                        review_ok = rereview.ok and self._review_pass(rereview.output)
                        if not review_ok:
                            continue
                if route.risk == Risk.HIGH:
                    sprompt = self.context.build(worktree, contract, "SECURITY_REVIEWER", self.git.diff(worktree)) + "\n\n" + SECURITY_SUFFIX
                    sre = self._agent_run(task_db_id, "SECURITY_REVIEWER", sprompt, worktree, ci_attempt)
                    security_review_ok = sre.ok and self._review_pass(sre.output)
                    if not security_review_ok:
                        continue

                self.git.commit(worktree, f"{public_id}: fix CI")
                self.git.push(worktree, branch)
                commit_sha = self._head(worktree)
            if not ci_ok:
                raise PipelineBlocked("CI retry budget exhausted.")

            pr_state = self.github.pr_state(worktree, pr)
            mergeable = pr_state.get("mergeable") == "MERGEABLE" and pr_state.get("state") == "OPEN"
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
                raise PipelineBlocked(f"Merge policy denied merge: {evidence}")
            if not self.config.auto_merge:
                raise PipelineBlocked("All gates passed, but auto_merge=false in configuration.")

            self.state.set_status(public_id, TaskStatus.MERGING)
            head_sha = pr_state.get("headRefOid") or commit_sha
            self.github.merge(worktree, pr, self.config.merge_method, head_sha)

            self.state.set_status(public_id, TaskStatus.POST_MERGE)
            # Verify GitHub reports merged; auto-merge may queue under branch protection/merge queue.
            deadline = time.time() + self.config.ci_timeout_seconds
            while time.time() < deadline:
                post = self.github.pr_state(worktree, pr)
                if post.get("state") == "MERGED":
                    self.state.set_status(public_id, TaskStatus.DONE)
                    break
                time.sleep(10)
            else:
                raise PipelineBlocked("PR passed all gates but has not reached MERGED state before timeout (possibly merge queue/policy).")

        except PipelineBlocked as exc:
            self.state.set_status(public_id, TaskStatus.BLOCKED, str(exc))
            raise
        except Exception as exc:
            self.state.set_status(public_id, TaskStatus.FAILED, str(exc))
            raise
        finally:
            current = self.state.task(public_id)
            if current["status"] == TaskStatus.DONE and worktree and branch:
                self.git.cleanup(worktree, branch)

    def _agent_run(self, task_db_id: int, role: str, prompt: str, workspace: Path, attempt: int):
        run_id = self.state.start_run(task_db_id, role, self.agent.name, attempt)
        try:
            result = self.agent.run(role, prompt, workspace)
            self.state.finish_run(run_id, "PASS" if result.ok else "FAIL", truncate(result.output, 5000))
            self.state.record_usage(task_db_id, run_id, self.agent.name, result.input_tokens, result.output_tokens)
            return result
        except Exception as exc:
            self.state.finish_run(run_id, "ERROR", str(exc))
            raise

    def _head(self, worktree: Path) -> str:
        from .util import run
        return run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()

    def _pr_body(self, contract: TaskContract, route, task_row: dict) -> str:
        closes = f"Closes #{task_row['source_reference']}\n\n" if task_row.get("source") == "github_issue" else ""
        criteria = "\n".join(f"- {x}" for x in contract.acceptance_criteria)
        return (
            f"{closes}Automated by AIpipe {contract.id}.\n\n"
            f"## Goal\n{contract.goal[:3000]}\n\n"
            f"## Acceptance criteria\n{criteria}\n\n"
            f"## Routing\n- Type: {route.task_type.value}\n- Risk: {route.risk.value}\n- Context: {route.context_class.value}\n"
            f"- Gates: {', '.join(route.gates)}\n\n"
            "Local quality, security and required independent review gates passed before this PR was opened. "
            "GitHub required checks must also pass before merge."
        )
