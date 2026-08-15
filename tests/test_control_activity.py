import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aipipe.control.activity import build_activity_feed, next_phase_label


def _event(id, kind, detail, ts):
    payload = detail if isinstance(detail, str) or detail is None else json.dumps(detail)
    return SimpleNamespace(id=id, kind=kind, detail=payload, created_at=ts)


def _task(status, error=None):
    return SimpleNamespace(status=status, error=error)


def _ts(seconds=0):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_next_phase_label_walks_the_happy_path():
    assert next_phase_label("QUEUED") == "Routing the task"
    assert next_phase_label("POST_MERGE") == "Completed"
    assert next_phase_label("DONE") is None
    assert next_phase_label("BLOCKED") is None


def test_queued_and_routing_produce_human_readable_phase_items():
    events = [
        _event(1, "QUEUED", "Prompt task queued", _ts(0)),
        _event(2, "CLAIMED", "worker-1", _ts(1)),
        _event(3, "core:status", {"public_id": "T-1", "status": "ROUTING", "detail": None}, _ts(2)),
        _event(4, "core:task_updated", {"public_id": "T-1", "fields": {"risk": "LOW", "context_class": "SMALL"}}, _ts(3)),
    ]
    feed = build_activity_feed(_task("ROUTING"), events, "Claude · Sonnet")

    titles = [item["title"] for item in feed["items"]]
    assert titles == ["Queued", "Routing the task"]

    queued = feed["items"][0]
    assert queued["result"] == "A worker claimed the task."
    assert queued["duration_seconds"] == 2.0  # closed when ROUTING opened

    routing = feed["items"][1]
    assert routing["result"] == "Classified as LOW risk, SMALL context."
    assert routing["duration_seconds"] is None  # still open

    assert feed["current"]["title"] == "Routing the task"
    assert feed["current"]["next_step"] == "Preparing the workspace"
    assert feed["blocker"] is None


def test_review_and_check_events_are_summarized_not_raw():
    events = [
        _event(1, "core:status", {"status": "VERIFYING"}, _ts(0)),
        _event(2, "core:check", {"check_type": "quality", "name": "pytest", "status": "PASS"}, _ts(1)),
        _event(3, "core:check", {"check_type": "quality", "name": "lint", "status": "PASS"}, _ts(2)),
        _event(4, "core:status", {"status": "REVIEWING"}, _ts(3)),
        _event(5, "core:event", {"event": "REVIEW", "detail": "Looks good.\nPASS"}, _ts(4)),
    ]
    feed = build_activity_feed(_task("REVIEWING"), events, "Claude")

    quality_item = next(i for i in feed["items"] if i["title"] == "Quality checks")
    assert quality_item["result"] == "2/2 checks passed."
    assert quality_item["status"] == "success"

    review_item = next(i for i in feed["items"] if i["title"] == "Reviewing implementation")
    assert review_item["result"] == "Review passed."
    assert review_item["status"] == "success"
    assert "PASS" not in review_item["summary"]  # no raw agent output leaked into the summary

    assert feed["checks"]["review"]["status"] == "success"
    assert {c["name"] for c in feed["checks"]["checks"]} == {"pytest", "lint"}


def test_failed_check_batch_lists_failing_names():
    events = [
        _event(1, "core:status", {"status": "VERIFYING"}, _ts(0)),
        _event(2, "core:check", {"check_type": "quality", "name": "pytest", "status": "PASS"}, _ts(1)),
        _event(3, "core:check", {"check_type": "quality", "name": "mypy", "status": "FAIL"}, _ts(2)),
    ]
    feed = build_activity_feed(_task("VERIFYING"), events, "Codex")
    quality_item = next(i for i in feed["items"] if i["title"] == "Quality checks")
    assert quality_item["result"] == "1/2 checks passed. Failed: mypy."
    assert quality_item["status"] == "warning"


def test_ci_checks_are_aggregated_into_a_single_result():
    checks = [
        {"name": "build", "bucket": "pass"},
        {"name": "tests", "bucket": "fail"},
    ]
    events = [
        _event(1, "core:status", {"status": "CI"}, _ts(0)),
        _event(2, "core:event", {"event": "CI", "detail": json.dumps(checks)}, _ts(1)),
    ]
    feed = build_activity_feed(_task("CI"), events, "Claude")
    ci_item = next(i for i in feed["items"] if i["title"] == "CI checks")
    assert ci_item["result"] == "1/2 checks passed. Failed: tests."
    assert feed["checks"]["ci"] == {"total": 2, "passed": 1, "failed": 1}


def test_planner_run_and_plan_are_summarized_in_the_feed():
    events = [
        _event(1, "core:status", {"status": "PLANNING"}, _ts(0)),
        _event(2, "core:event", {"event": "PLANNER_RUN", "detail": "attempt=1 rc=0\nGoal\nDo the thing."}, _ts(1)),
        _event(3, "core:event", {"event": "PLAN", "detail": "Goal\nDo the thing.\n\nAffected components\n- api"}, _ts(2)),
    ]
    feed = build_activity_feed(_task("PLANNING"), events, "Claude")

    run_item = next(i for i in feed["items"] if i["title"] == "Planner attempt 1")
    assert run_item["result"] == "Plan produced."
    assert run_item["status"] == "success"

    plan_item = next(i for i in feed["items"] if i["title"] == "Implementation plan")
    assert plan_item["result"] == "Goal"
    assert plan_item["status"] == "success"

    assert feed["checks"]["plan"]["status"] == "success"
    assert "Affected components" in feed["checks"]["plan"]["plan"]


def test_planner_failed_attempt_is_surfaced_as_a_warning():
    events = [
        _event(1, "core:status", {"status": "PLANNING"}, _ts(0)),
        _event(2, "core:event", {"event": "PLANNER_RUN", "detail": "attempt=2 rc=1\nagent crashed"}, _ts(1)),
    ]
    feed = build_activity_feed(_task("PLANNING"), events, "Codex")
    run_item = next(i for i in feed["items"] if i["title"] == "Planner attempt 2")
    assert run_item["result"] == "Attempt did not produce a usable plan."
    assert run_item["status"] == "warning"


def test_no_plan_event_leaves_plan_summary_unset():
    events = [_event(1, "core:status", {"status": "IMPLEMENTING"}, _ts(0))]
    feed = build_activity_feed(_task("IMPLEMENTING"), events, "Claude")
    assert feed["checks"]["plan"] is None


def test_blocked_state_surfaces_reason_and_last_successful_phase():
    events = [
        _event(1, "core:status", {"status": "ROUTING"}, _ts(0)),
        _event(2, "core:status", {"status": "PREPARING"}, _ts(5)),
        _event(3, "core:status", {"status": "IMPLEMENTING"}, _ts(10)),
        _event(4, "core:status", {"status": "VERIFYING"}, _ts(20)),
        _event(5, "core:status", {"status": "BLOCKED", "detail": "No configured quality command passed."}, _ts(25)),
    ]
    feed = build_activity_feed(_task("BLOCKED", error="No configured quality command passed."), events, "Claude")

    assert feed["current"] is None  # no live "currently running" card once terminal
    assert feed["blocker"]["reason"] == "No configured quality command passed."
    assert feed["blocker"]["last_phase"] == "Running verification"

    blocked_item = feed["items"][-1]
    assert blocked_item["title"] == "Blocked"
    assert blocked_item["result"] == "No configured quality command passed."
    assert blocked_item["status"] == "error"


def test_worker_lost_produces_a_failed_item_without_a_core_status_event():
    events = [
        _event(1, "core:status", {"status": "IMPLEMENTING"}, _ts(0)),
        _event(2, "WORKER_LOST", "Worker heartbeat expired (host:123)", _ts(30)),
    ]
    feed = build_activity_feed(_task("FAILED", error="Worker heartbeat expired (host:123)"), events, "Codex")

    assert feed["items"][-1]["title"] == "Worker lost"
    assert feed["items"][-1]["result"] == "Worker heartbeat expired (host:123)"
    assert feed["blocker"]["reason"] == "Worker heartbeat expired (host:123)"
    assert feed["blocker"]["last_phase"] == "Implementing the change"


def test_secret_scan_finding_is_surfaced_as_an_error_item():
    events = [
        _event(1, "core:status", {"status": "VERIFYING"}, _ts(0)),
        _event(2, "core:finding", {"source": "secret_scan", "severity": "HIGH", "status": "OPEN", "description": "Possible AWS key in diff"}, _ts(1)),
    ]
    feed = build_activity_feed(_task("VERIFYING"), events, "Claude")
    finding = next(i for i in feed["items"] if i["title"] == "Secret scan finding")
    assert finding["status"] == "error"
    assert finding["result"] == "Possible AWS key in diff"


def test_unrelated_kinds_do_not_produce_visible_activity_items():
    events = [
        _event(1, "core:status", {"status": "CI"}, _ts(0)),
        _event(2, "core:usage", {"input_tokens": 100, "output_tokens": 50}, _ts(1)),
        _event(3, "core:run_started", {"role": "IMPLEMENTER"}, _ts(2)),
        _event(4, "github:check_suite", {"action": "completed"}, _ts(3)),
        _event(5, "CORE_TASK_CREATED", "T-1", _ts(4)),
    ]
    feed = build_activity_feed(_task("CI"), events, "Claude")
    assert len(feed["items"]) == 1  # only the CI phase item itself


def test_done_state_has_no_current_activity_card():
    events = [
        _event(1, "core:status", {"status": "MERGING"}, _ts(0)),
        _event(2, "core:status", {"status": "POST_MERGE"}, _ts(5)),
        _event(3, "core:status", {"status": "DONE"}, _ts(10)),
    ]
    feed = build_activity_feed(_task("DONE"), events, "Claude")
    assert feed["current"] is None
    assert feed["items"][-1]["title"] == "Completed"
    assert feed["items"][-1]["status"] == "success"
    # The final phase before DONE is closed with a duration once DONE opens.
    assert feed["items"][-2]["duration_seconds"] == 5.0


def test_no_events_yields_empty_feed():
    feed = build_activity_feed(_task("QUEUED"), [], "Claude")
    assert feed["items"] == []
    assert feed["current"] is None
    assert feed["blocker"] is None


def test_needs_input_surfaces_a_blocker_and_no_current_activity():
    events = [
        _event(1, "core:status", {"status": "ROUTING"}, _ts(0)),
        _event(2, "core:status", {"status": "PREPARING"}, _ts(5)),
        _event(3, "core:status", {"status": "NEEDS_INPUT", "detail": "Which package manager should be used?"}, _ts(10)),
    ]
    feed = build_activity_feed(_task("NEEDS_INPUT"), events, "Claude")

    assert feed["current"] is None  # stalled, not actively running a phase
    assert feed["blocker"] is not None
    assert feed["blocker"]["reason"] == "Which package manager should be used?"
    assert feed["blocker"]["last_phase"] == "Preparing the workspace"

    needs_input_item = feed["items"][-1]
    assert needs_input_item["title"] == "Needs input"
    assert needs_input_item["result"] == "Which package manager should be used?"


def test_needs_input_without_detail_uses_a_default_reason():
    events = [_event(1, "core:status", {"status": "NEEDS_INPUT"}, _ts(0))]
    feed = build_activity_feed(_task("NEEDS_INPUT"), events, "Claude")
    assert feed["blocker"]["reason"] == "Waiting for additional input."
    assert feed["blocker"]["last_phase"] is None


def test_non_phase_items_have_no_duration_by_default():
    events = [
        _event(1, "core:status", {"status": "VERIFYING"}, _ts(0)),
        _event(2, "core:check", {"check_type": "quality", "name": "pytest", "status": "PASS"}, _ts(1)),
        _event(3, "core:status", {"status": "REVIEWING"}, _ts(2)),
        _event(4, "core:event", {"event": "REVIEW", "detail": "PASS"}, _ts(3)),
    ]
    feed = build_activity_feed(_task("REVIEWING"), events, "Claude")

    quality_item = next(i for i in feed["items"] if i["title"] == "Quality checks")
    review_item = next(i for i in feed["items"] if i["title"] == "Reviewing implementation")
    assert quality_item["duration_seconds"] is None
    assert review_item["duration_seconds"] is None


def test_discovering_status_does_not_imply_progression_to_planning():
    # DISCOVERING is a distinct workflow from run()'s PHASE_ORDER, so it must
    # never suggest the task will proceed to PLANNING like DISCOVERY does.
    assert next_phase_label("DISCOVERING") is None


def test_discovering_phase_renders_readably_without_a_misleading_next_step():
    events = [_event(1, "core:status", {"status": "DISCOVERING"}, _ts(0))]
    feed = build_activity_feed(_task("DISCOVERING"), events, "Codex")

    assert feed["items"][0]["title"] == "Discovering features"
    assert feed["items"][0]["next_step"] is None
    assert feed["current"]["title"] == "Discovering features"
    assert feed["current"]["next_step"] is None


def test_discovery_agent_run_event_is_summarized_not_raw():
    events = [
        _event(1, "core:status", {"status": "DISCOVERING"}, _ts(0)),
        _event(2, "core:event", {"event": "DISCOVERY_AGENT_RUN", "detail": "attempt=1 rc=0\nsome raw output"}, _ts(1)),
    ]
    feed = build_activity_feed(_task("DISCOVERING"), events, "Codex")
    item = next(i for i in feed["items"] if i["title"] == "Discovery attempt 1")
    assert item["result"] == "Response received."
    assert item["status"] == "success"
    assert "raw output" not in item["summary"]


def test_discovery_candidates_event_reports_count():
    candidates_json = json.dumps([{"key": "a"}, {"key": "b"}])
    events = [
        _event(1, "core:status", {"status": "DISCOVERING"}, _ts(0)),
        _event(2, "core:event", {"event": "DISCOVERY_CANDIDATES", "detail": candidates_json}, _ts(1)),
    ]
    feed = build_activity_feed(_task("DISCOVERING"), events, "Codex")
    item = next(i for i in feed["items"] if i["title"] == "Feature candidates proposed")
    assert item["result"] == "2 candidate(s) ranked."


def test_discovery_issue_created_and_failed_events_are_summarized():
    events = [
        _event(1, "core:status", {"status": "DISCOVERING"}, _ts(0)),
        _event(2, "core:event", {"event": "DISCOVERY_ISSUE_CREATED", "detail": json.dumps({"key": "a", "issue_number": 42})}, _ts(1)),
        _event(3, "core:event", {"event": "DISCOVERY_ISSUE_FAILED", "detail": json.dumps({"key": "b", "title": "X", "error": "boom"})}, _ts(2)),
    ]
    feed = build_activity_feed(_task("DISCOVERING"), events, "Codex")

    created_item = next(i for i in feed["items"] if i["title"] == "Issue filed")
    assert created_item["result"] == "Issue #42 created."
    assert created_item["status"] == "success"

    failed_item = next(i for i in feed["items"] if i["title"] == "Issue creation failed")
    assert failed_item["result"] == "boom"
    assert failed_item["status"] == "warning"


def test_discovery_summary_event_reports_totals_and_marks_task_done():
    summary = {"created": ["a", "b"], "duplicates": ["c"], "failed": [], "handoff_issue_numbers": [1]}
    events = [
        _event(1, "core:status", {"status": "DISCOVERING"}, _ts(0)),
        _event(2, "core:event", {"event": "DISCOVERY_SUMMARY", "detail": json.dumps(summary)}, _ts(1)),
        _event(3, "core:status", {"status": "DONE"}, _ts(2)),
    ]
    feed = build_activity_feed(_task("DONE"), events, "Codex")
    item = next(i for i in feed["items"] if i["title"] == "Discovery summary")
    assert item["result"] == "2 issue(s) created, 1 duplicate(s) skipped, 0 failed, 1 handed off."
    assert feed["blocker"] is None
