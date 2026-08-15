import json

from aipipe.discovery import (
    DISCOVERY_MARKER,
    FeatureCandidate,
    build_candidates,
    detect_duplicates,
    issue_body,
    parse_candidates,
    rank_candidates,
    score_candidate,
    within_bounds,
)


# --- parse_candidates -------------------------------------------------------


def test_parse_candidates_clean_json():
    raw = json.dumps({"candidates": [{"title": "A", "summary": "B"}]})
    assert parse_candidates(raw) == [{"title": "A", "summary": "B"}]


def test_parse_candidates_strips_markdown_fence():
    raw = "```json\n" + json.dumps({"candidates": [{"title": "A", "summary": "B"}]}) + "\n```"
    assert parse_candidates(raw) == [{"title": "A", "summary": "B"}]


def test_parse_candidates_tolerates_surrounding_prose():
    raw = (
        "Sure, here are my findings.\n\n"
        + json.dumps({"candidates": [{"title": "A", "summary": "B"}]})
        + "\n\nLet me know if you want more."
    )
    assert parse_candidates(raw) == [{"title": "A", "summary": "B"}]


def test_parse_candidates_returns_empty_list_when_no_envelope_present():
    assert parse_candidates("I found nothing interesting to propose.") == []


def test_parse_candidates_returns_empty_list_for_empty_input():
    assert parse_candidates("") == []
    assert parse_candidates("   ") == []


def test_parse_candidates_drops_non_dict_items():
    raw = json.dumps({"candidates": [{"title": "A", "summary": "B"}, "not-a-dict", 5]})
    assert parse_candidates(raw) == [{"title": "A", "summary": "B"}]


def test_parse_candidates_ignores_unrelated_json_objects_before_the_envelope():
    raw = (
        '{"note": "unrelated"}\n'
        + json.dumps({"candidates": [{"title": "A", "summary": "B"}]})
    )
    assert parse_candidates(raw) == [{"title": "A", "summary": "B"}]


# --- build_candidates --------------------------------------------------------


def test_build_candidates_normalizes_and_defaults_invalid_fields():
    raw = [
        {
            "title": "Add CSV export",
            "summary": "Export report data as CSV.",
            "suggested_risk": "not-a-risk",
            "suggested_complexity": "not-a-class",
            "task_type": "not-a-type",
        }
    ]
    [candidate] = build_candidates(raw, max_candidates=5)
    assert candidate.title == "Add CSV export"
    assert candidate.risk == "MEDIUM"
    assert candidate.context_class == "NORMAL"
    assert candidate.task_type == "FEATURE"
    assert candidate.status == "proposed"


def test_build_candidates_drops_entries_missing_title_or_summary():
    raw = [
        {"title": "", "summary": "has no title"},
        {"title": "has no summary", "summary": ""},
        {"title": "Valid", "summary": "Valid summary"},
    ]
    built = build_candidates(raw, max_candidates=5)
    assert [c.title for c in built] == ["Valid"]


def test_build_candidates_caps_at_max_candidates():
    raw = [{"title": f"Feature {i}", "summary": f"Summary {i}"} for i in range(10)]
    built = build_candidates(raw, max_candidates=3)
    assert len(built) == 3


def test_build_candidates_deduplicates_by_derived_key():
    raw = [
        {"title": "Add dark mode", "summary": "First proposal"},
        {"title": "Add dark mode", "summary": "Second proposal, same title"},
    ]
    built = build_candidates(raw, max_candidates=5)
    assert len(built) == 1


def test_build_candidates_key_is_stable_and_deterministic():
    raw = [{"title": "Add dark mode", "summary": "s"}]
    a = build_candidates(raw, max_candidates=5)[0]
    b = build_candidates(raw, max_candidates=5)[0]
    assert a.key == b.key
    assert len(a.key) == 12


# --- score_candidate / rank_candidates ---------------------------------------


def _candidate(risk="MEDIUM", context_class="NORMAL", criteria=None, key="k"):
    return FeatureCandidate(
        key=key,
        title="t",
        summary="s",
        risk=risk,
        context_class=context_class,
        acceptance_criteria=criteria or [],
    )


def test_score_candidate_is_deterministic():
    c = _candidate()
    assert score_candidate(c) == score_candidate(_candidate())


def test_score_candidate_rewards_lower_risk_and_complexity_and_concrete_criteria():
    low = _candidate(risk="LOW", context_class="SMALL", criteria=["a", "b", "c"])
    high = _candidate(risk="HIGH", context_class="DEEP", criteria=[])
    assert score_candidate(low) > score_candidate(high)


def test_rank_candidates_orders_best_first_and_assigns_rank():
    low = _candidate(risk="LOW", context_class="SMALL", criteria=["a", "b", "c"], key="low")
    high = _candidate(risk="HIGH", context_class="DEEP", criteria=[], key="high")
    ranked = rank_candidates([high, low])
    assert [c.key for c in ranked] == ["low", "high"]
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2


def test_rank_candidates_breaks_ties_by_key_for_reproducibility():
    a = _candidate(key="bbb")
    b = _candidate(key="aaa")
    ranked = rank_candidates([a, b])
    assert [c.key for c in ranked] == ["aaa", "bbb"]


# --- detect_duplicates --------------------------------------------------------


def test_detect_duplicates_exact_marker_match():
    candidate = _candidate(key="abc123def456")
    existing_issues = [{"number": 7, "title": "Something else", "body": DISCOVERY_MARKER.format(key="abc123def456")}]
    detect_duplicates([candidate], existing_issues, [])
    assert candidate.status == "duplicate"
    assert candidate.duplicate_of == "#7"


def test_detect_duplicates_fuzzy_title_match_against_issue():
    candidate = _candidate(key="k")
    candidate.title = "Add CSV export for reports"
    existing_issues = [{"number": 3, "title": "Add CSV export for reports", "body": ""}]
    detect_duplicates([candidate], existing_issues, [])
    assert candidate.status == "duplicate"
    assert candidate.duplicate_of == "#3"


def test_detect_duplicates_fuzzy_title_match_against_pr():
    candidate = _candidate(key="k")
    candidate.title = "Add CSV export for reports"
    existing_prs = [{"number": 11, "title": "Add CSV export for reports"}]
    detect_duplicates([candidate], [], existing_prs)
    assert candidate.status == "duplicate"
    assert candidate.duplicate_of == "#11"


def test_detect_duplicates_leaves_dissimilar_candidates_proposed():
    candidate = _candidate(key="k")
    candidate.title = "Add CSV export for reports"
    existing_issues = [{"number": 3, "title": "Fix login race condition", "body": ""}]
    detect_duplicates([candidate], existing_issues, [])
    assert candidate.status == "proposed"
    assert candidate.duplicate_of is None


def test_detect_duplicates_with_no_existing_issues_or_prs_is_a_no_op():
    candidate = _candidate(key="k")
    detect_duplicates([candidate], [], [])
    assert candidate.status == "proposed"


# --- within_bounds -------------------------------------------------------------


def test_within_bounds_allows_candidate_at_or_below_ceiling():
    c = _candidate(risk="LOW", context_class="SMALL")
    assert within_bounds(c, max_risk="MEDIUM", max_context_class="NORMAL") is True


def test_within_bounds_rejects_candidate_above_risk_ceiling():
    c = _candidate(risk="HIGH", context_class="SMALL")
    assert within_bounds(c, max_risk="MEDIUM", max_context_class="NORMAL") is False


def test_within_bounds_rejects_candidate_above_context_ceiling():
    c = _candidate(risk="LOW", context_class="DEEP")
    assert within_bounds(c, max_risk="MEDIUM", max_context_class="NORMAL") is False


# --- issue_body ----------------------------------------------------------------


def test_issue_body_contains_marker_and_structured_sections():
    c = _candidate(key="abc123def456")
    c.title = "Add dark mode"
    c.summary = "Add a dark theme toggle."
    c.rationale = "Frequently requested."
    c.acceptance_criteria = ["Toggle persists across sessions."]
    body = issue_body(c)
    assert DISCOVERY_MARKER.format(key="abc123def456") in body
    assert "## Summary" in body
    assert "## Rationale" in body
    assert "## Acceptance Criteria" in body
    assert "## Suggested routing" in body
    assert "Add a dark theme toggle." in body
    assert "Toggle persists across sessions." in body


def test_issue_body_never_instructs_direct_implementation():
    c = _candidate(key="k")
    body = issue_body(c)
    assert "not implemented automatically" in body.lower()
