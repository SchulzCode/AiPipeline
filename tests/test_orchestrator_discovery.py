import json
from types import SimpleNamespace

import pytest

from aipipe.discovery import DiscoveryResult
from aipipe.models import FailureCategory
from aipipe.orchestrator import Orchestrator, PipelineBlocked


class _FakeContext:
    def build(self, *args, **kwargs):
        return "context"


class _FakeGit:
    def __init__(self, worktree, branch="ai/T-0001-discovery", diff_sequence=None):
        self.worktree = worktree
        self.branch = branch
        self.prepare_calls = 0
        self.cleanup_calls = 0
        self._diff_sequence = list(diff_sequence) if diff_sequence is not None else None
        self._diff_index = 0

    def prepare(self, task_id, title):
        self.prepare_calls += 1
        return self.branch, self.worktree

    def assert_worktree(self, worktree, branch):
        pass

    def diff(self, worktree):
        if self._diff_sequence is None:
            return ""
        value = self._diff_sequence[min(self._diff_index, len(self._diff_sequence) - 1)]
        self._diff_index += 1
        return value

    def cleanup(self, worktree, branch):
        self.cleanup_calls += 1

    def commit(self, *args, **kwargs):
        raise AssertionError("discovery must never commit repository changes")

    def push(self, *args, **kwargs):
        raise AssertionError("discovery must never push")


class _FailingPrepareGit(_FakeGit):
    def prepare(self, task_id, title):
        raise RuntimeError("worktree busy")


class _FakeGitHub:
    def __init__(self, issues=None, prs=None, create_results=None, list_error=None):
        self._issues = issues or []
        self._prs = prs or []
        self._create_results = create_results or {}
        self._list_error = list_error
        self.created_titles: list[str] = []

    def list_issues(self, state="all", limit=200):
        if self._list_error:
            raise self._list_error
        return self._issues

    def list_recent_prs(self, state="all", limit=100):
        return self._prs

    def create_issue(self, title, body, labels, marker):
        self.created_titles.append(title)
        outcome = self._create_results.get(title)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        number = 100 + len(self.created_titles)
        return {"number": number, "url": f"https://example.invalid/issues/{number}"}


class _FakeStateStore:
    def __init__(self, task_row):
        self._task_row = dict(task_row)
        self.events: list[tuple[int, str, str | None]] = []
        self.statuses: list[tuple[str, str | None]] = []
        self._run_id = 0

    def task(self, public_id):
        return dict(self._task_row)

    def event(self, task_id, event, detail=None):
        self.events.append((task_id, event, detail))

    def set_status(self, public_id, status, detail=None, failure_category=None):
        self.statuses.append((str(status), str(failure_category) if failure_category else None))
        self._task_row["status"] = str(status)

    def start_run(self, task_id, role, backend, attempt):
        self._run_id += 1
        return self._run_id

    def finish_run(self, run_id, status, summary=None):
        pass

    def record_usage(self, *args, **kwargs):
        pass


class _FakeAgent:
    name = "fake"

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0

    def run(self, role, prompt, workspace):
        self.calls += 1
        return self._outputs.pop(0)


def _agent_result(ok=True, output="", returncode=None):
    return SimpleNamespace(
        ok=ok,
        output=output,
        returncode=returncode if returncode is not None else (0 if ok else 1),
        input_tokens=0,
        output_tokens=0,
    )


def _candidates_output(items):
    return json.dumps({"candidates": items})


def _make_orchestrator(tmp_path, agent_outputs, github=None, git=None, config_overrides=None):
    orch = Orchestrator.__new__(Orchestrator)
    defaults = dict(
        discovery_max_candidates=5,
        discovery_max_new_issues=5,
        discovery_max_auto_implement=0,
        discovery_max_risk="MEDIUM",
        discovery_max_context_class="NORMAL",
        discovery_attempts=2,
    )
    defaults.update(config_overrides or {})
    orch.config = SimpleNamespace(**defaults)
    orch.context = _FakeContext()
    orch.git = git or _FakeGit(tmp_path)
    task_row = {
        "id": 1,
        "public_id": "T-0001",
        "goal": "Discover valuable features.",
        "title": "Feature discovery",
        "body": None,
        "status": "QUEUED",
    }
    orch.state = _FakeStateStore(task_row)
    orch.agent = _FakeAgent(agent_outputs)
    orch.github = github or _FakeGitHub()
    orch._preflight = lambda: None
    orch._project = lambda: 1
    return orch


DARK_MODE = {
    "title": "Add dark mode",
    "summary": "Add a dark theme toggle.",
    "rationale": "Frequently requested.",
    "acceptance_criteria": ["Toggle persists across sessions."],
    "suggested_risk": "LOW",
    "suggested_complexity": "SMALL",
    "labels": ["ui"],
}

CSV_EXPORT = {
    "title": "Add CSV export",
    "summary": "Export report data as CSV.",
    "rationale": "Requested by finance team.",
    "acceptance_criteria": ["Export button produces a valid CSV."],
    "suggested_risk": "LOW",
    "suggested_complexity": "SMALL",
    "labels": ["reporting"],
}


# --- discovery-only completion ------------------------------------------------


def test_discovery_only_completion_reaches_done_without_git_diff_or_commit(tmp_path):
    github = _FakeGitHub(issues=[], prs=[])
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([DARK_MODE]))],
        github=github,
    )

    result = orch.run_discovery("T-0001")

    assert isinstance(result, DiscoveryResult)
    assert orch.state.statuses[-1] == ("DONE", None)
    assert orch.git.cleanup_calls == 1
    assert len(result.created) == 1
    assert result.created[0].issue_number is not None
    assert result.handoff_issue_numbers == []  # default max_auto_implement=0


def test_discovery_persists_candidates_event_even_with_zero_candidates(tmp_path):
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([]))],
    )
    result = orch.run_discovery("T-0001")
    assert result.candidates == []
    assert orch.state.statuses[-1] == ("DONE", None)
    assert any(kind == "DISCOVERY_CANDIDATES" for _, kind, _ in orch.state.events)


# --- read-only tripwire ---------------------------------------------------------


def test_discovery_agent_mutating_workspace_raises_state_inconsistency(tmp_path):
    git = _FakeGit(tmp_path, diff_sequence=["before", "after-mutation"])
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([DARK_MODE]))],
        git=git,
    )

    with pytest.raises(PipelineBlocked) as exc:
        orch.run_discovery("T-0001")

    assert exc.value.category == FailureCategory.STATE_INCONSISTENCY
    assert "read-only" in str(exc.value)
    assert orch.state.statuses[-1][0] == "BLOCKED"
    # Nothing was committed and the ephemeral worktree/branch is still reclaimed.
    assert git.cleanup_calls == 1


def test_discovery_workspace_preparation_failure_is_state_inconsistency(tmp_path):
    orch = _make_orchestrator(
        tmp_path,
        [],
        git=_FailingPrepareGit(tmp_path),
    )
    with pytest.raises(PipelineBlocked) as exc:
        orch.run_discovery("T-0001")
    assert exc.value.category == FailureCategory.STATE_INCONSISTENCY


# --- duplicate prevention -------------------------------------------------------


def test_duplicate_candidates_never_trigger_create_issue(tmp_path):
    existing_issues = [{"number": 5, "title": "Add dark mode", "body": ""}]
    github = _FakeGitHub(issues=existing_issues, prs=[])
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([DARK_MODE, CSV_EXPORT]))],
        github=github,
    )

    result = orch.run_discovery("T-0001")

    assert github.created_titles == ["Add CSV export"]
    assert len(result.duplicates) == 1
    assert result.duplicates[0].title == "Add dark mode"
    assert result.duplicates[0].duplicate_of == "#5"
    assert len(result.created) == 1


# --- partial GitHub failure recoverability --------------------------------------


def test_one_failing_issue_creation_still_reaches_done_with_candidates_preserved(tmp_path):
    third = {
        "title": "Add dashboard widget",
        "summary": "Show recent activity on the dashboard.",
        "acceptance_criteria": ["Widget renders recent activity."],
        "suggested_risk": "LOW",
        "suggested_complexity": "SMALL",
    }
    github = _FakeGitHub(
        issues=[],
        prs=[],
        create_results={"Add CSV export": RuntimeError("GitHub API unavailable")},
    )
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([DARK_MODE, CSV_EXPORT, third]))],
        github=github,
    )

    result = orch.run_discovery("T-0001")

    assert orch.state.statuses[-1] == ("DONE", None)
    assert len(result.created) == 2
    assert len(result.failed) == 1
    assert result.failed[0].title == "Add CSV export"
    assert result.failed[0].error

    kinds = [kind for _, kind, _ in orch.state.events]
    assert "DISCOVERY_CANDIDATES" in kinds
    assert "DISCOVERY_ISSUE_FAILED" in kinds
    candidates_event = next(detail for _, kind, detail in orch.state.events if kind == "DISCOVERY_CANDIDATES")
    persisted = json.loads(candidates_event)
    assert len(persisted) == 3


def test_duplicate_lookup_failure_still_preserves_generated_candidates(tmp_path):
    github = _FakeGitHub(list_error=RuntimeError("connection reset"))
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([DARK_MODE]))],
        github=github,
    )

    with pytest.raises(PipelineBlocked) as exc:
        orch.run_discovery("T-0001")

    assert exc.value.category == FailureCategory.TRANSIENT_EXTERNAL
    kinds = [kind for _, kind, _ in orch.state.events]
    assert "DISCOVERY_CANDIDATES" in kinds
    assert orch.state.statuses[-1][0] == "BLOCKED"


# --- budget enforcement -----------------------------------------------------------


def test_max_candidates_and_max_new_issues_budget_enforcement(tmp_path):
    many = [
        {
            "title": f"Feature {i}",
            "summary": f"Summary {i}",
            "acceptance_criteria": ["a"],
            "suggested_risk": "LOW",
            "suggested_complexity": "SMALL",
        }
        for i in range(10)
    ]
    github = _FakeGitHub(issues=[], prs=[])
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output(many))],
        github=github,
        config_overrides={"discovery_max_candidates": 4, "discovery_max_new_issues": 2},
    )

    result = orch.run_discovery("T-0001")

    assert len(result.candidates) == 4
    assert len(github.created_titles) == 2
    assert len(result.created) == 2
    assert sum(1 for c in result.candidates if c.status == "proposed") == 2


# --- handoff selection -------------------------------------------------------------


def test_handoff_selection_respects_rank_risk_and_context_bounds_and_max_auto_implement(tmp_path):
    low_risk_small = {
        "title": "Low risk small feature",
        "summary": "s",
        "acceptance_criteria": ["a", "b", "c"],
        "suggested_risk": "LOW",
        "suggested_complexity": "SMALL",
    }
    high_risk = {
        "title": "High risk feature",
        "summary": "s",
        "acceptance_criteria": ["a"],
        "suggested_risk": "HIGH",
        "suggested_complexity": "SMALL",
    }
    deep_context = {
        "title": "Deep context feature",
        "summary": "s",
        "acceptance_criteria": ["a"],
        "suggested_risk": "LOW",
        "suggested_complexity": "DEEP",
    }
    medium_ok = {
        "title": "Medium risk normal feature",
        "summary": "s",
        "acceptance_criteria": ["a", "b"],
        "suggested_risk": "MEDIUM",
        "suggested_complexity": "NORMAL",
    }
    github = _FakeGitHub(issues=[], prs=[])
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([low_risk_small, high_risk, deep_context, medium_ok]))],
        github=github,
        config_overrides={
            "discovery_max_new_issues": 4,
            "discovery_max_auto_implement": 2,
            "discovery_max_risk": "MEDIUM",
            "discovery_max_context_class": "NORMAL",
        },
    )

    result = orch.run_discovery("T-0001")

    handed_off_titles = {c.title for c in result.created if c.handoff}
    assert handed_off_titles == {"Low risk small feature", "Medium risk normal feature"}
    assert len(result.handoff_issue_numbers) == 2
    assert "High risk feature" not in handed_off_titles
    assert "Deep context feature" not in handed_off_titles


def test_default_config_yields_no_handoff_issue_numbers(tmp_path):
    """Safe-default acceptance criterion: max_auto_implement=0 by default."""
    github = _FakeGitHub(issues=[], prs=[])
    orch = _make_orchestrator(
        tmp_path,
        [_agent_result(ok=True, output=_candidates_output([DARK_MODE, CSV_EXPORT]))],
        github=github,
    )
    assert orch.config.discovery_max_auto_implement == 0

    result = orch.run_discovery("T-0001")

    assert result.handoff_issue_numbers == []
    assert all(not c.handoff for c in result.created)


# --- discovery agent retry / protocol failure --------------------------------------


def test_discovery_agent_failure_retries_within_bounded_budget_then_blocks(tmp_path):
    orch = _make_orchestrator(
        tmp_path,
        [
            _agent_result(ok=False, output="crashed"),
            _agent_result(ok=False, output="crashed again"),
        ],
        config_overrides={"discovery_attempts": 2},
    )

    with pytest.raises(PipelineBlocked) as exc:
        orch.run_discovery("T-0001")

    assert exc.value.category == FailureCategory.AGENT_PROTOCOL
    assert orch.agent.calls == 2


def test_discovery_agent_succeeds_after_one_retry(tmp_path):
    orch = _make_orchestrator(
        tmp_path,
        [
            _agent_result(ok=False, output="transient failure"),
            _agent_result(ok=True, output=_candidates_output([DARK_MODE])),
        ],
        config_overrides={"discovery_attempts": 2},
    )

    result = orch.run_discovery("T-0001")

    assert orch.agent.calls == 2
    assert len(result.candidates) == 1
