from types import SimpleNamespace

import pytest

from aipipe.models import FailureCategory, Risk
from aipipe.orchestrator import Orchestrator, PipelineBlocked
from aipipe.reliability import ReviewVerdict


class _Context:
    def __init__(self):
        self.build_calls = []

    def build(self, *args, **kwargs):
        self.build_calls.append((args, kwargs))
        return "context"


class _Git:
    def diff(self, worktree):
        return "diff"


class _State:
    def __init__(self):
        self.events = []

    def event(self, *args):
        self.events.append(args)


class _MutatingGit:
    """A `.diff()` fake that returns a different value on each successive call.

    Used to simulate a "read-only" role unexpectedly mutating the worktree,
    the same way the real diff-hash tripwire in `_invoke_review`/`_run_planner`
    would detect it.
    """

    def __init__(self, sequence):
        self._sequence = list(sequence)
        self._index = 0

    def diff(self, worktree):
        value = self._sequence[min(self._index, len(self._sequence) - 1)]
        self._index += 1
        return value


def _orchestrator(review_attempts=2, planner_attempts=2, implementation_attempts=3):
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = SimpleNamespace(
        review_attempts=review_attempts,
        verification_attempts=2,
        planner_attempts=planner_attempts,
        implementation_attempts=implementation_attempts,
    )
    orch.context = _Context()
    orch.git = _Git()
    orch.state = _State()
    return orch


class _ImplementerGit:
    """A `.changed_files()`/`.diff()` fake for implementer-loop tests.

    `changed_files` drives the loop's per-attempt success check (mirrors
    `git diff --name-only`); `diff_value` drives the final
    "does a repository diff already exist" preservation check (mirrors
    `git diff`, which also picks up untracked files). The two are tracked
    independently since the real GitManager methods differ in what they see.
    """

    def __init__(self, changed_files=(), diff_value=""):
        self._changed_files = list(changed_files)
        self._diff_value = diff_value

    def changed_files(self, worktree):
        return list(self._changed_files)

    def diff(self, worktree):
        return self._diff_value


def _agent_result(ok=True, output="fixed"):
    return SimpleNamespace(
        ok=ok,
        output=output,
        returncode=0 if ok else 1,
        input_tokens=0,
        output_tokens=0,
    )


def test_review_budget_ends_on_final_confirmation_pass_not_last_fix():
    orch = _orchestrator(review_attempts=2)
    verdicts = iter([
        ReviewVerdict.FINDINGS,
        ReviewVerdict.FINDINGS,
        ReviewVerdict.PASS,
    ])
    review_calls = []
    fix_calls = []

    def invoke(*args, **kwargs):
        verdict = next(verdicts)
        review_calls.append(verdict)
        return verdict, "FINDINGS\n- MEDIUM: fix me", "hash"

    orch._invoke_review = invoke
    orch._agent_run = lambda *args, **kwargs: (fix_calls.append(1) or _agent_result())
    orch._ensure_local_gates = lambda *args, **kwargs: (True, True, True)

    diff_hash, remediations = orch._review_gate(
        1,
        "REVIEWER",
        "REVIEW",
        "suffix",
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        category=FailureCategory.REVIEW_FAILURE,
        failure_message="review failed",
    )

    assert diff_hash == "hash"
    assert remediations == 2
    assert len(review_calls) == 3
    assert len(fix_calls) == 2


def test_review_blocks_only_after_final_confirmation_still_has_findings():
    orch = _orchestrator(review_attempts=2)
    verdicts = iter([
        ReviewVerdict.FINDINGS,
        ReviewVerdict.FINDINGS,
        ReviewVerdict.FINDINGS,
    ])
    review_calls = []
    fix_calls = []

    def invoke(*args, **kwargs):
        verdict = next(verdicts)
        review_calls.append(verdict)
        return verdict, "FINDINGS\n- MEDIUM: still broken", "hash"

    orch._invoke_review = invoke
    orch._agent_run = lambda *args, **kwargs: (fix_calls.append(1) or _agent_result())
    orch._ensure_local_gates = lambda *args, **kwargs: (True, True, True)

    with pytest.raises(PipelineBlocked) as exc:
        orch._review_gate(
            1,
            "REVIEWER",
            "REVIEW",
            "suffix",
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            category=FailureCategory.REVIEW_FAILURE,
            failure_message="review failed",
        )

    assert exc.value.category == FailureCategory.REVIEW_FAILURE
    assert len(review_calls) == 3
    assert len(fix_calls) == 2


def test_verification_budget_also_ends_on_a_post_fix_gate_result():
    orch = _orchestrator(review_attempts=2)
    results = iter([
        (False, False, True, True, "tests failed"),
        (False, False, True, True, "tests still failed"),
        (True, True, True, True, ""),
    ])
    gate_calls = []
    fix_calls = []

    def run_gates(*args, **kwargs):
        result = next(results)
        gate_calls.append(result)
        return result

    orch._run_local_gates = run_gates
    orch._agent_run = lambda *args, **kwargs: (fix_calls.append(1) or _agent_result())

    quality_ok, secret_ok, security_ok = orch._ensure_local_gates(
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        quality_kind="quality",
        security_kind="security",
        max_repairs=2,
        failure_category=FailureCategory.QUALITY_FAILURE,
        failure_message="verification failed",
    )

    assert (quality_ok, secret_ok, security_ok) == (True, True, True)
    assert len(gate_calls) == 3
    assert len(fix_calls) == 2


def test_verification_blocks_after_last_fix_is_actually_rechecked():
    orch = _orchestrator(review_attempts=2)
    results = iter([
        (False, False, True, True, "fail 1"),
        (False, False, True, True, "fail 2"),
        (False, False, True, True, "fail 3"),
    ])
    gate_calls = []
    fix_calls = []

    def run_gates(*args, **kwargs):
        result = next(results)
        gate_calls.append(result)
        return result

    orch._run_local_gates = run_gates
    orch._agent_run = lambda *args, **kwargs: (fix_calls.append(1) or _agent_result())

    with pytest.raises(PipelineBlocked):
        orch._ensure_local_gates(
            1,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            quality_kind="quality",
            security_kind="security",
            max_repairs=2,
            failure_category=FailureCategory.QUALITY_FAILURE,
            failure_message="verification failed",
        )

    assert len(gate_calls) == 3
    assert len(fix_calls) == 2


# -- Bounded Planner guidance threaded into remediation (#50) ---------------
#
# `bounded_guidance` is a `dict[str, list[str]]` derived once, in `run()`,
# from the parsed Planner `TaskMap` (see `test_bounded_guidance.py`). These
# tests exercise the real orchestration methods that must carry it forward
# into every remediation fix-prompt -- not a standalone extraction helper.


def test_ensure_local_gates_threads_bounded_guidance_into_fix_prompt():
    orch = _orchestrator()
    results = iter([
        (False, False, True, True, "tests failed"),
        (True, True, True, True, ""),
    ])
    orch._run_local_gates = lambda *args, **kwargs: next(results)
    orch._agent_run = lambda *args, **kwargs: _agent_result()
    bounded_guidance = {"constraints": ["stay read-only"]}

    orch._ensure_local_gates(
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        quality_kind="quality",
        security_kind="security",
        max_repairs=2,
        failure_category=FailureCategory.QUALITY_FAILURE,
        failure_message="verification failed",
        bounded_guidance=bounded_guidance,
    )

    (_, kwargs) = orch.context.build_calls[-1]
    assert kwargs["bounded_guidance"] == bounded_guidance


def test_ensure_local_gates_defaults_bounded_guidance_to_none_for_compatibility():
    orch = _orchestrator()
    results = iter([
        (False, False, True, True, "tests failed"),
        (True, True, True, True, ""),
    ])
    orch._run_local_gates = lambda *args, **kwargs: next(results)
    orch._agent_run = lambda *args, **kwargs: _agent_result()

    orch._ensure_local_gates(
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        quality_kind="quality",
        security_kind="security",
        max_repairs=2,
        failure_category=FailureCategory.QUALITY_FAILURE,
        failure_message="verification failed",
    )

    (_, kwargs) = orch.context.build_calls[-1]
    assert kwargs["bounded_guidance"] is None


def test_review_gate_threads_bounded_guidance_to_fix_prompt_and_nested_local_gates_not_own_prompt():
    orch = _orchestrator(review_attempts=2)
    verdicts = iter([ReviewVerdict.FINDINGS, ReviewVerdict.PASS])
    orch._invoke_review = lambda *args, **kwargs: (next(verdicts), "FINDINGS\n- MEDIUM: fix me", "hash")
    orch._agent_run = lambda *args, **kwargs: _agent_result()
    nested_ensure_calls = []
    orch._ensure_local_gates = lambda *args, **kwargs: (nested_ensure_calls.append(kwargs) or (True, True, True))

    bounded_guidance = {"risks": ["breaking change"]}

    orch._review_gate(
        1,
        "REVIEWER",
        "REVIEW",
        "suffix",
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        category=FailureCategory.REVIEW_FAILURE,
        failure_message="review failed",
        bounded_guidance=bounded_guidance,
    )

    # REVIEWER's own prompt builds (role positional arg) must never receive
    # Planner guidance, to preserve independent review (#50 constraint).
    reviewer_builds = [kw for (a, kw) in orch.context.build_calls if a[2] == "REVIEWER"]
    assert reviewer_builds
    assert all("bounded_guidance" not in kw for kw in reviewer_builds)
    # The IMPLEMENTER fix-prompt build must receive it.
    fix_builds = [kw for (a, kw) in orch.context.build_calls if a[2] == "IMPLEMENTER"]
    assert fix_builds
    assert fix_builds[-1]["bounded_guidance"] == bounded_guidance
    # ... and so must the nested local-gates re-verification after the fix.
    assert nested_ensure_calls[-1]["bounded_guidance"] == bounded_guidance


def test_semantic_gates_after_change_forwards_bounded_guidance_to_both_review_gates():
    orch = _orchestrator()
    orch._confirmation_review = lambda *args, **kwargs: "confirmed-hash"
    review_gate_calls = []
    orch._review_gate = lambda *args, **kwargs: (review_gate_calls.append(kwargs) or ("hash", 0))

    bounded_guidance = {"out_of_scope": ["billing"]}
    route = SimpleNamespace(risk=Risk.HIGH)

    orch._semantic_gates_after_change(
        1,
        route,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        bounded_guidance=bounded_guidance,
    )

    assert len(review_gate_calls) == 2  # REVIEWER, then SECURITY_REVIEWER for HIGH risk
    assert review_gate_calls[0]["bounded_guidance"] == bounded_guidance
    assert review_gate_calls[1]["bounded_guidance"] == bounded_guidance


def test_run_ci_gate_threads_bounded_guidance_into_fix_prompt_and_nested_gates():
    orch = _orchestrator()
    orch.config.ci_attempts = 2
    orch.github = SimpleNamespace(failed_run_logs=lambda *args, **kwargs: "")
    ci_states = iter([("fail", [{"bucket": "fail"}]), ("pass", [])])
    orch._wait_for_ci = lambda worktree, pr: next(ci_states)
    orch._wait_for_pr_head = lambda *args, **kwargs: {}
    orch._agent_run = lambda *args, **kwargs: _agent_result()
    orch.git = SimpleNamespace(
        diff=lambda wt: "diff",
        status=lambda wt: "M file.py",
        commit=lambda wt, msg: "sha-new",
        push=lambda wt, branch: None,
        head=lambda wt: "sha-new",
    )
    ensure_calls = []
    orch._ensure_local_gates = lambda *args, **kwargs: (ensure_calls.append(kwargs) or (True, True, True))
    semantic_calls = []
    orch._semantic_gates_after_change = lambda *args, **kwargs: (semantic_calls.append(kwargs) or (True, True))
    orch._run_local_gates = lambda *args, **kwargs: (True, True, True, True, "")

    bounded_guidance = {"constraints": ["stay read-only"]}

    result = orch._run_ci_gate(
        "T-1",
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        "branch",
        42,
        SimpleNamespace(),
        SimpleNamespace(),
        "sha-old",
        True,
        True,
        True,
        True,
        True,
        bounded_guidance=bounded_guidance,
    )

    commit_sha, quality_ok, secret_ok, sec_cmd_ok, review_ok, security_review_ok, ci_ok = result
    assert ci_ok is True
    assert commit_sha == "sha-new"

    (_, fix_kwargs) = orch.context.build_calls[-1]
    assert fix_kwargs["bounded_guidance"] == bounded_guidance
    assert ensure_calls[-1]["bounded_guidance"] == bounded_guidance
    assert semantic_calls[-1]["bounded_guidance"] == bounded_guidance


def test_remediation_paths_never_invoke_the_planner():
    """Planner must not be re-run merely because remediation is needed (#50).

    None of `_ensure_local_gates`, `_review_gate`, or `_run_ci_gate` may call
    `_run_planner`; `bounded_guidance` is threaded through as already-derived
    state instead of being recovered by re-planning.
    """
    orch = _orchestrator()
    orch.config.ci_attempts = 2

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Planner must not be re-invoked during remediation")

    orch._run_planner = fail_if_called
    bounded_guidance = {"constraints": ["c"]}

    gate_results = iter([(False, False, True, True, "fail"), (True, True, True, True, "")])
    orch._run_local_gates = lambda *args, **kwargs: next(gate_results)
    orch._agent_run = lambda *args, **kwargs: _agent_result()
    orch._ensure_local_gates(
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        quality_kind="quality",
        security_kind="security",
        max_repairs=2,
        failure_category=FailureCategory.QUALITY_FAILURE,
        failure_message="x",
        bounded_guidance=bounded_guidance,
    )

    verdicts = iter([ReviewVerdict.FINDINGS, ReviewVerdict.PASS])
    orch._invoke_review = lambda *args, **kwargs: (next(verdicts), "FINDINGS", "hash")
    orch._ensure_local_gates = lambda *args, **kwargs: (True, True, True)
    orch._review_gate(
        1,
        "REVIEWER",
        "REVIEW",
        "suffix",
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        category=FailureCategory.REVIEW_FAILURE,
        failure_message="x",
        bounded_guidance=bounded_guidance,
    )

    ci_states = iter([("fail", []), ("pass", [])])
    orch._wait_for_ci = lambda *args, **kwargs: next(ci_states)
    orch._wait_for_pr_head = lambda *args, **kwargs: {}
    orch.github = SimpleNamespace(failed_run_logs=lambda *args, **kwargs: "")
    orch.git = SimpleNamespace(
        diff=lambda wt: "diff",
        status=lambda wt: "M x",
        commit=lambda wt, msg: "s",
        push=lambda wt, branch: None,
        head=lambda wt: "s",
    )
    orch._semantic_gates_after_change = lambda *args, **kwargs: (True, True)
    orch._run_local_gates = lambda *args, **kwargs: (True, True, True, True, "")
    orch._run_ci_gate(
        "T-1",
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        "branch",
        1,
        SimpleNamespace(),
        SimpleNamespace(),
        "sha",
        True,
        True,
        True,
        True,
        True,
        bounded_guidance=bounded_guidance,
    )


def test_agent_run_starts_a_fresh_run_every_invocation():
    """Every remediation attempt is a fresh agent run, never a reused session (#50)."""
    orch = _orchestrator()
    orch.agent = SimpleNamespace(name="test-agent", run=lambda role, prompt, workspace: _agent_result())
    calls = []

    def start_run(task_id, role, backend, attempt):
        calls.append((role, backend, attempt))
        return len(calls)

    orch.state.start_run = start_run
    orch.state.finish_run = lambda *args, **kwargs: None
    orch.state.record_usage = lambda *args, **kwargs: None

    orch._agent_run(1, "IMPLEMENTER", "prompt-1", SimpleNamespace(), 1)
    orch._agent_run(1, "IMPLEMENTER", "prompt-2", SimpleNamespace(), 2)

    assert calls == [("IMPLEMENTER", "test-agent", 1), ("IMPLEMENTER", "test-agent", 2)]


def test_planner_returns_plan_on_first_success():
    orch = _orchestrator(planner_attempts=2)
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append((role, attempt))
        return _agent_result(ok=True, output="Goal\nDo the thing.\n")

    orch._agent_run = agent_run

    plan = orch._run_planner(1, SimpleNamespace(), SimpleNamespace())

    assert plan == "Goal\nDo the thing.\n"
    assert calls == [("PLANNER", 1)]
    kinds = [e[1] for e in orch.state.events]  # state.event(task_db_id, kind, detail)
    assert kinds == ["PLANNER_RUN", "PLAN"]


def test_planner_retries_once_then_succeeds_within_budget():
    orch = _orchestrator(planner_attempts=2)
    outputs = iter([
        _agent_result(ok=True, output=""),  # empty plan: not usable, must retry
        _agent_result(ok=True, output="Goal\nDo the thing.\n"),
    ])
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return next(outputs)

    orch._agent_run = agent_run

    plan = orch._run_planner(1, SimpleNamespace(), SimpleNamespace())

    assert plan == "Goal\nDo the thing.\n"
    assert calls == [1, 2]


def test_planner_is_blocked_after_exhausting_retry_budget():
    orch = _orchestrator(planner_attempts=2)
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=False, output="agent crashed")

    orch._agent_run = agent_run

    with pytest.raises(PipelineBlocked) as exc:
        orch._run_planner(1, SimpleNamespace(), SimpleNamespace())

    assert exc.value.category == FailureCategory.PLANNING_FAILURE
    assert calls == [1, 2]  # bounded: never loops past the configured budget


def test_planner_does_not_create_an_infinite_loop_with_a_budget_of_one():
    orch = _orchestrator(planner_attempts=1)
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=False, output="")

    orch._agent_run = agent_run

    with pytest.raises(PipelineBlocked):
        orch._run_planner(1, SimpleNamespace(), SimpleNamespace())

    assert calls == [1]


def test_planner_mutating_the_worktree_is_blocked_as_state_inconsistency():
    orch = _orchestrator(planner_attempts=3)
    orch.git = _MutatingGit(["diff-before", "diff-after-mutation"])
    orch._agent_run = lambda *args, **kwargs: _agent_result(ok=True, output="Goal\n...")

    with pytest.raises(PipelineBlocked) as exc:
        orch._run_planner(1, SimpleNamespace(), SimpleNamespace())

    assert exc.value.category == FailureCategory.STATE_INCONSISTENCY
    assert "read-only" in str(exc.value)


# -- Planner -> Implementer task-map handoff (#49) --------------------------
#
# `_build_implement_context` no longer parses `plan_text` itself (see #50):
# `run()` parses the Planner's raw output into a `TaskMap` exactly once and
# passes the already-parsed result in, so every test below constructs the
# `task_map` the same way `run()` now does (`parse_task_map(plan_text)`)
# instead of relying on the callee to do it.


def test_build_implement_context_passes_parsed_task_map_to_context_build():
    from aipipe.task_map import parse_task_map

    orch = _orchestrator()
    plan_text = (
        "Goal\nDo the thing.\n\n"
        '```json\n{"relevant_files": ["a.py"], "constraints": ["stay read-only"]}\n```\n'
    )
    task_map = parse_task_map(plan_text)

    orch._build_implement_context(SimpleNamespace(), SimpleNamespace(), plan_text, task_map)

    (args, kwargs) = orch.context.build_calls[-1]
    assert args[2] == "IMPLEMENTER"
    assert kwargs["plan"] == plan_text
    built_task_map = kwargs["task_map"]
    assert built_task_map is not None
    assert built_task_map.relevant_files == ("a.py",)
    assert built_task_map.constraints == ("stay read-only",)
    # The initial Implementer prompt already carries the same
    # constraints/risks/out-of-scope content via `plan` + `task_map`;
    # duplicating it a third time as `bounded_guidance` would only crowd the
    # context budget, so the initial build must not receive it (#50).
    assert "bounded_guidance" not in kwargs


def test_build_implement_context_degrades_to_no_task_map_when_plan_has_no_json():
    orch = _orchestrator()
    plan_text = "Goal\nDo the thing.\nNo JSON task map included.\n"

    orch._build_implement_context(SimpleNamespace(), SimpleNamespace(), plan_text, None)

    (args, kwargs) = orch.context.build_calls[-1]
    assert kwargs["plan"] == plan_text
    assert kwargs["task_map"] is None


def test_build_implement_context_degrades_to_no_task_map_when_plan_is_empty():
    orch = _orchestrator()

    orch._build_implement_context(SimpleNamespace(), SimpleNamespace(), "", None)

    (args, kwargs) = orch.context.build_calls[-1]
    assert kwargs["plan"] == ""
    assert kwargs["task_map"] is None


def test_implementer_succeeds_on_first_clean_attempt():
    orch = _orchestrator(implementation_attempts=3)
    orch.git = _ImplementerGit(changed_files=["src/thing.py"])
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=True, output="done")

    orch._agent_run = agent_run

    orch._run_implementer(1, "context", SimpleNamespace())

    assert calls == [1]


def test_implementer_retries_a_plain_failure_then_succeeds():
    orch = _orchestrator(implementation_attempts=3)
    orch.git = _ImplementerGit(changed_files=[])
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        if attempt == 1:
            return _agent_result(ok=False, output="unexpected internal error")
        orch.git._changed_files = ["src/thing.py"]
        return _agent_result(ok=True, output="done")

    orch._agent_run = agent_run

    orch._run_implementer(1, "context", SimpleNamespace())

    assert calls == [1, 2]


def test_implementer_blocks_after_exhausting_retries_with_no_diff():
    orch = _orchestrator(implementation_attempts=3)
    orch.git = _ImplementerGit(changed_files=[], diff_value="")
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=False, output="agent crashed with a stack trace")

    orch._agent_run = agent_run

    with pytest.raises(PipelineBlocked) as exc:
        orch._run_implementer(1, "context", SimpleNamespace())

    assert calls == [1, 2, 3]  # bounded: full retry budget consumed
    assert exc.value.category == FailureCategory.AGENT_PROTOCOL
    assert "did not produce a valid repository change" in str(exc.value)


def test_implementer_preserves_existing_diff_instead_of_reporting_none():
    # Nonzero exit with no capacity signal, but a diff already exists in the
    # worktree (e.g. from partial work before the failing attempt). This is
    # a non-capacity case: classification stays AGENT_PROTOCOL, but the
    # failure must not falsely claim no implementation exists.
    orch = _orchestrator(implementation_attempts=2)
    orch.git = _ImplementerGit(changed_files=[], diff_value="diff --git a/x b/x\n+work in progress")
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=False, output="agent exited with a tool error")

    orch._agent_run = agent_run

    with pytest.raises(PipelineBlocked) as exc:
        orch._run_implementer(1, "context", SimpleNamespace())

    assert calls == [1, 2]  # non-capacity retries are unchanged
    assert exc.value.category == FailureCategory.AGENT_PROTOCOL
    assert "did not produce a valid repository change" not in str(exc.value)
    assert "preserved" in str(exc.value)


def test_implementer_stops_immediately_when_capacity_is_exhausted():
    orch = _orchestrator(implementation_attempts=3)
    orch.git = _ImplementerGit(changed_files=[], diff_value="")
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=False, output="Error: usage limit reached. Try again later.")

    orch._agent_run = agent_run

    with pytest.raises(PipelineBlocked) as exc:
        orch._run_implementer(1, "context", SimpleNamespace())

    assert calls == [1]  # stops immediately, does not consume the full budget
    assert exc.value.category == FailureCategory.PROVIDER_CAPACITY


def test_implementer_capacity_exhaustion_preserves_existing_diff():
    orch = _orchestrator(implementation_attempts=3)
    orch.git = _ImplementerGit(changed_files=[], diff_value="diff --git a/x b/x\n+partial")
    calls = []

    def agent_run(task_db_id, role, prompt, worktree, attempt):
        calls.append(attempt)
        return _agent_result(ok=False, output="session limit exceeded for this account")

    orch._agent_run = agent_run

    with pytest.raises(PipelineBlocked) as exc:
        orch._run_implementer(1, "context", SimpleNamespace())

    assert calls == [1]  # stops immediately even though a diff exists
    assert exc.value.category == FailureCategory.PROVIDER_CAPACITY
    assert "preserved" in str(exc.value)
