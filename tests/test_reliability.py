import pytest

import aipipe.reliability as reliability
from aipipe.reliability import ReviewVerdict, parse_review_verdict, retry_transient


def test_json_pass_verdict():
    parsed = parse_review_verdict('{"verdict":"PASS","findings":[]}')
    assert parsed.verdict == ReviewVerdict.PASS
    assert parsed.findings == ()


def test_json_findings_verdict():
    parsed = parse_review_verdict(
        '{"verdict":"FINDINGS","findings":["MEDIUM: regression"]}'
    )
    assert parsed.verdict == ReviewVerdict.FINDINGS
    assert parsed.findings == ("MEDIUM: regression",)


def test_json_pass_with_surrounding_prose_is_accepted():
    parsed = parse_review_verdict(
        "Test fixture consolidation only affects test-only dev-auth setup, "
        "not production code paths — no security impact.\n\n"
        '{"verdict":"PASS","findings":[]}'
    )
    assert parsed.verdict == ReviewVerdict.PASS
    assert parsed.findings == ()


def test_json_findings_with_surrounding_prose_is_accepted():
    parsed = parse_review_verdict(
        "I found one actionable regression.\n\n"
        '{"verdict":"FINDINGS","findings":["MEDIUM: regression"]}\n'
        "Review complete."
    )
    assert parsed.verdict == ReviewVerdict.FINDINGS
    assert parsed.findings == ("MEDIUM: regression",)


def test_duplicate_equivalent_json_verdicts_are_not_ambiguous():
    parsed = parse_review_verdict(
        '{"verdict":"PASS","findings":[]}\n'
        "Same conclusion after final check.\n"
        '{"verdict":"PASS","findings":[]}'
    )
    assert parsed.verdict == ReviewVerdict.PASS


def test_conflicting_embedded_json_verdicts_are_protocol_error():
    parsed = parse_review_verdict(
        '{"verdict":"PASS","findings":[]}\n'
        '{"verdict":"FINDINGS","findings":["MEDIUM: regression"]}'
    )
    assert parsed.verdict == ReviewVerdict.PROTOCOL_ERROR


def test_embedded_json_conflicting_with_legacy_marker_is_protocol_error():
    parsed = parse_review_verdict(
        "FINDINGS\n- MEDIUM: regression\n"
        '{"verdict":"PASS","findings":[]}'
    )
    assert parsed.verdict == ReviewVerdict.PROTOCOL_ERROR


def test_legacy_explanation_followed_by_pass_is_accepted():
    parsed = parse_review_verdict("Checked the current diff.\nPASS")
    assert parsed.verdict == ReviewVerdict.PASS


def test_markdown_legacy_verdict_pass_is_accepted():
    parsed = parse_review_verdict(
        "My review is complete — no issues found.\n\n**Verdict: PASS**\n\nDetails follow."
    )
    assert parsed.verdict == ReviewVerdict.PASS


def test_conflicting_findings_and_pass_is_never_pass():
    parsed = parse_review_verdict("FINDINGS\n- MEDIUM: bug\nPASS")
    assert parsed.verdict == ReviewVerdict.FINDINGS


def test_invalid_review_is_protocol_error():
    parsed = parse_review_verdict("Looks reasonable to me.")
    assert parsed.verdict == ReviewVerdict.PROTOCOL_ERROR


def test_json_pass_with_findings_is_not_pass():
    parsed = parse_review_verdict(
        '{"verdict":"PASS","findings":["LOW: contradictory"]}'
    )
    assert parsed.verdict == ReviewVerdict.FINDINGS


def test_retry_transient_recovers_within_bound(monkeypatch):
    monkeypatch.setattr(reliability.time, "sleep", lambda _: None)
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("HTTP 503 temporarily unavailable")
        return "ok"

    assert retry_transient(operation, attempts=3, initial_delay=0) == "ok"
    assert attempts == 3


def test_retry_transient_does_not_retry_permanent_error(monkeypatch):
    monkeypatch.setattr(reliability.time, "sleep", lambda _: None)
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("permission denied")

    with pytest.raises(RuntimeError, match="permission denied"):
        retry_transient(operation, attempts=3, initial_delay=0)
    assert attempts == 1
