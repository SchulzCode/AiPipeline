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


def test_legacy_explanation_followed_by_pass_is_accepted():
    parsed = parse_review_verdict("Checked the current diff.\nPASS")
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
