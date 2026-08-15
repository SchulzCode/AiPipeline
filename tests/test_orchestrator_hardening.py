from types import SimpleNamespace

import pytest

from aipipe.models import FailureCategory
from aipipe.orchestrator import Orchestrator, PipelineBlocked
from aipipe.reliability import ReviewVerdict


class _Context:
    def build(self, *args, **kwargs):
        return "context"


class _Git:
    def diff(self, worktree):
        return "diff"


class _State:
    def __init__(self):
        self.events = []

    def event(self, *args):
        self.events.append(args)


def _orchestrator(review_attempts=2):
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = SimpleNamespace(
        review_attempts=review_attempts,
        verification_attempts=2,
    )
    orch.context = _Context()
    orch.git = _Git()
    orch.state = _State()
    return orch


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
