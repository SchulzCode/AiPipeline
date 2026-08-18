"""Orchestration-path tests for bounded Planner guidance during remediation (#50).

Issue #50 requires bounded Planner guidance (constraints/risks/out_of_scope,
derived once from the parsed Planner `TaskMap`) to survive into every later
remediation stage -- verification (`_ensure_local_gates`), review
(`_review_gate`/`_semantic_gates_after_change`), and CI (`_run_ci_gate`) --
not just the initial Implementer prompt. These tests drive the real
`Orchestrator.run()` state machine end-to-end (with the network/subprocess
boundaries -- Git, GitHub, agent CLI, quality/security command execution --
faked, matching this codebase's existing `Orchestrator.__new__` + fake test
style) rather than only exercising `_derive_bounded_guidance_from_task_map`
in isolation. See `test_bounded_guidance.py` for the derivation unit tests
and `test_orchestrator_hardening.py` for method-level threading tests.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from aipipe.config import PipelineConfig
from aipipe.models import ContextClass, Risk, Route, TaskType
from aipipe.orchestrator import Orchestrator


# -- Shared fakes -------------------------------------------------------
#
# Git/GitHub/agent-CLI/subprocess boundaries are faked; the Planner ->
# TaskMap -> bounded_guidance derivation, every gate method, and the CI
# repair loop all run as real, unmodified `Orchestrator` code.


class _Context:
    def __init__(self):
        self.build_calls = []

    def build(self, *args, **kwargs):
        self.build_calls.append((args, kwargs))
        return "context"


class _FakeState:
    def __init__(self, task_row):
        self._row = dict(task_row)
        self.events = []
        self.runs = []
        self._run_id = 0

    def task(self, public_id):
        return dict(self._row)

    def update_task(self, public_id, **fields):
        self._row.update(fields)

    def set_status(self, public_id, status, detail=None, failure_category=None):
        self._row["status"] = status

    def event(self, task_id, kind, detail=None):
        self.events.append((kind, detail))

    def check(self, task_id, check_type, name, status, command=None, returncode=None, summary=None):
        pass

    def finding(self, task_id, source, severity, description, status="OPEN"):
        pass

    def start_run(self, task_id, role, backend, attempt):
        self._run_id += 1
        self.runs.append((role, attempt, self._run_id))
        return self._run_id

    def finish_run(self, run_id, status, summary=None):
        pass

    def record_usage(self, task_id, run_id, agent, input_tokens, output_tokens):
        pass


class _FakeGit:
    def __init__(self, worktree: Path):
        self._worktree = worktree
        self._commit_n = 0

    def preflight(self):
        pass

    def prepare(self, public_id, title):
        return f"aipipe/{public_id}", self._worktree

    def assert_worktree(self, worktree, branch):
        pass

    def status(self, worktree):
        return ""

    def diff(self, worktree):
        return "diff --git a/file.py b/file.py\n+print('ok')\n"

    def changed_files(self, worktree):
        return ["file.py"]

    def commit(self, worktree, message):
        self._commit_n += 1
        return f"sha-{self._commit_n}"

    def push(self, worktree, branch):
        pass

    def head(self, worktree):
        return f"sha-{self._commit_n}"

    def cleanup(self, worktree, branch):
        pass


class _FakeGithub:
    def preflight(self, repo):
        pass

    def create_pr(self, worktree, title, body, main_branch):
        return 101

    def failed_run_logs(self, worktree, branch, head):
        return ""

    def merge(self, worktree, pr, method, sha):
        pass

    def pr_state(self, worktree, pr):
        return {"state": "MERGED", "mergeable": "MERGEABLE", "headRefOid": "sha-final"}


class _FakeQualityEngine:
    """Fails exactly once (the very first `.execute()` call), then always passes.

    Forces one real verification-remediation cycle inside `_ensure_local_gates`
    without any real subprocess execution.
    """

    def __init__(self, *args, **kwargs):
        self.calls = 0

    def execute(self, repo):
        self.calls += 1
        ok = self.calls != 1
        result = SimpleNamespace(
            ok=ok,
            stdout="" if ok else "quality check failed",
            stderr="",
            returncode=0 if ok else 1,
            command="quality",
        )
        return [("quality", result)]


class _FakeSecurityEngine:
    def __init__(self, *args, **kwargs):
        pass

    def execute_commands(self, repo):
        return []


class _AgentRunner:
    """Fakes `Orchestrator._agent_run`, dispatching canned per-role results.

    REVIEWER fails (FINDINGS) on its first call and passes thereafter, so
    exactly one review-remediation cycle runs. CI is driven separately by
    `_CiWaiter`.
    """

    def __init__(self, plan_output: str):
        self.plan_output = plan_output
        self.calls = []
        self._reviewer_calls = 0

    def __call__(self, task_db_id, role, prompt, worktree, attempt):
        self.calls.append((role, attempt))
        if role == "PLANNER":
            return _result(ok=True, output=self.plan_output)
        if role == "IMPLEMENTER":
            return _result(ok=True, output="applied fix")
        if role == "REVIEWER":
            self._reviewer_calls += 1
            verdict = "FINDINGS\n- MEDIUM: needs work" if self._reviewer_calls == 1 else "PASS"
            return _result(ok=True, output=verdict)
        raise AssertionError(f"unexpected role: {role}")

    def role_calls(self, role):
        return [attempt for r, attempt in self.calls if r == role]


class _CiWaiter:
    """Fails CI on the first check, then passes -- forcing one CI-repair cycle."""

    def __init__(self):
        self.calls = 0

    def __call__(self, worktree, pr):
        self.calls += 1
        if self.calls == 1:
            return "fail", [{"bucket": "fail", "name": "unit-tests"}]
        return "pass", [{"bucket": "pass", "name": "unit-tests"}]


def _result(ok=True, output="ok"):
    return SimpleNamespace(ok=ok, output=output, returncode=0 if ok else 1, input_tokens=0, output_tokens=0)


def _build_fake_orchestrator(tmp_path: Path, monkeypatch, route: Route, plan_output: str):
    monkeypatch.setattr("aipipe.orchestrator.route_task", lambda goal, labels=None: route)
    monkeypatch.setattr("aipipe.orchestrator.QualityEngine", _FakeQualityEngine)
    monkeypatch.setattr("aipipe.orchestrator.SecurityEngine", _FakeSecurityEngine)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (tmp_path / "home").mkdir()

    orch = Orchestrator.__new__(Orchestrator)
    orch.repo = tmp_path
    orch.home = tmp_path / "home"
    orch.config = PipelineConfig(
        auto_merge=True,
        merge_method="squash",
        ci_timeout_seconds=60,
        ci_registration_grace_seconds=5,
        command_timeout_seconds=60,
        implementation_attempts=1,
        verification_attempts=2,
        review_attempts=2,
        ci_attempts=2,
        external_attempts=1,
        external_backoff_seconds=0,
        planner_attempts=1,
        planner_enabled=True,
        planner_context_classes=("DEEP",),
        setup_commands={},
        setup_auto=False,
        quality_commands={},
        security_commands={},
    )
    task_row = {
        "id": 1,
        "goal": "Refactor the widget pipeline for maintainability.",
        "source": "prompt",
        "source_reference": None,
        "title": "Refactor widget pipeline",
        "body": None,
        "status": "PENDING",
    }
    orch.state = _FakeState(task_row)
    orch.git = _FakeGit(worktree)
    orch.github = _FakeGithub()
    orch.context = _Context()
    orch.index_cache = None
    orch.agent = SimpleNamespace(name="test-agent", runtime_env={})

    agent_runner = _AgentRunner(plan_output)
    orch._agent_run = agent_runner
    orch._wait_for_ci = _CiWaiter()
    orch._wait_for_pr_head = lambda worktree, pr, expected_sha: {
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "headRefOid": expected_sha,
    }

    return orch, agent_runner


PLAN_JSON = {
    "constraints": ["stay read-only during exploration", "no schema changes"],
    "risks": ["breaking change to the public widget API"],
    "out_of_scope": ["billing integration"],
}
PLAN_OUTPUT = "Goal\nRefactor the pipeline.\n\n```json\n" + json.dumps(PLAN_JSON) + "\n```\n"
EXPECTED_BOUNDED_GUIDANCE = {
    "constraints": list(PLAN_JSON["constraints"]),
    "risks": list(PLAN_JSON["risks"]),
    "out_of_scope": list(PLAN_JSON["out_of_scope"]),
}


def test_full_run_derives_bounded_guidance_once_and_threads_it_through_every_remediation_stage(
    tmp_path, monkeypatch
):
    route = Route(TaskType.FEATURE, Risk.MEDIUM, ContextClass.DEEP, ["general"], ["quality", "review"])
    orch, agent_runner = _build_fake_orchestrator(tmp_path, monkeypatch, route, PLAN_OUTPUT)

    orch.run("T-1")

    # The Planner ran exactly once for the whole task, including across
    # verification/review/CI remediation -- it is never re-invoked merely
    # because remediation is needed (#50).
    assert agent_runner.role_calls("PLANNER") == [1]

    implementer_builds = [
        (args, kwargs) for (args, kwargs) in orch.context.build_calls if args[2] == "IMPLEMENTER"
    ]
    # First IMPLEMENTER build is the initial prompt: it must not duplicate
    # bounded_guidance (plan + task_map already carry the same content).
    assert "bounded_guidance" not in implementer_builds[0][1]
    remediation_builds = implementer_builds[1:]
    # Verification-remediation, review-remediation, and CI-remediation each
    # produced at least one IMPLEMENTER fix-prompt build in this run.
    assert len(remediation_builds) >= 3
    for _, kwargs in remediation_builds:
        assert kwargs["bounded_guidance"] == EXPECTED_BOUNDED_GUIDANCE

    # REVIEWER's own prompt never receives Planner guidance (independence).
    reviewer_builds = [kw for (args, kw) in orch.context.build_calls if args[2] == "REVIEWER"]
    assert reviewer_builds
    assert all("bounded_guidance" not in kw for kw in reviewer_builds)

    # No raw plan text, provider session metadata, or full TaskMap object
    # ever appears as the durable guidance -- only the bounded dict.
    for _, kwargs in remediation_builds:
        guidance = kwargs["bounded_guidance"]
        assert isinstance(guidance, dict)
        assert all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in guidance.values())
        assert "session_id" not in json.dumps(guidance)
        assert "Goal\nRefactor the pipeline." not in json.dumps(guidance)

    assert orch.state.task("T-1")["status"] == "DONE"


def test_full_run_without_planner_degrades_bounded_guidance_to_empty_and_stays_compatible(
    tmp_path, monkeypatch
):
    """Backward compatibility: context_class not requiring a Planner (#50 constraint)."""
    route = Route(TaskType.BUG, Risk.LOW, ContextClass.SMALL, ["general"], ["quality"])
    orch, agent_runner = _build_fake_orchestrator(tmp_path, monkeypatch, route, plan_output="")

    orch.run("T-1")

    assert agent_runner.role_calls("PLANNER") == []
    implementer_builds = [
        (args, kwargs) for (args, kwargs) in orch.context.build_calls if args[2] == "IMPLEMENTER"
    ]
    initial_args, initial_kwargs = implementer_builds[0]
    assert initial_kwargs["task_map"] is None
    assert initial_kwargs["plan"] == ""
    for _, kwargs in implementer_builds[1:]:
        assert kwargs.get("bounded_guidance") == {}
    assert orch.state.task("T-1")["status"] == "DONE"


def test_full_run_with_malformed_planner_output_degrades_bounded_guidance_to_empty(tmp_path, monkeypatch):
    """A Planner that ran but produced no parseable TaskMap must still degrade safely (#50)."""
    route = Route(TaskType.FEATURE, Risk.LOW, ContextClass.DEEP, ["general"], ["quality"])
    orch, agent_runner = _build_fake_orchestrator(
        tmp_path, monkeypatch, route, plan_output="Goal\nJust prose, no JSON task map at all.\n"
    )

    orch.run("T-1")

    assert agent_runner.role_calls("PLANNER") == [1]
    implementer_builds = [
        (args, kwargs) for (args, kwargs) in orch.context.build_calls if args[2] == "IMPLEMENTER"
    ]
    initial_args, initial_kwargs = implementer_builds[0]
    assert initial_kwargs["task_map"] is None
    for _, kwargs in implementer_builds[1:]:
        assert kwargs.get("bounded_guidance") == {}
    assert orch.state.task("T-1")["status"] == "DONE"
