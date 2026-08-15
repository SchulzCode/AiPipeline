from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable, TypeVar

from .util import run


class ReviewVerdict(StrEnum):
    PASS = "PASS"
    FINDINGS = "FINDINGS"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


@dataclass(frozen=True)
class ParsedReview:
    verdict: ReviewVerdict
    findings: tuple[str, ...] = ()
    reason: str | None = None


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_JSON_DECODER = json.JSONDecoder()


def _parse_review_payload(payload: dict) -> ParsedReview | None:
    """Parse one JSON review envelope.

    Return None for unrelated JSON objects so harmless diagnostic JSON in
    surrounding prose is ignored rather than mistaken for a review verdict.
    """

    if "verdict" not in payload:
        return None

    verdict = str(payload.get("verdict") or "").strip().upper()
    raw_findings = payload.get("findings") or []

    if isinstance(raw_findings, str):
        raw_findings = [raw_findings]
    if not isinstance(raw_findings, list):
        return ParsedReview(
            ReviewVerdict.PROTOCOL_ERROR,
            reason="Reviewer JSON has an invalid findings field.",
        )

    findings = tuple(
        str(item).strip()
        for item in raw_findings
        if str(item).strip()
    )

    if verdict == "PASS" and not findings:
        return ParsedReview(ReviewVerdict.PASS)
    if verdict == "FINDINGS":
        return ParsedReview(ReviewVerdict.FINDINGS, findings=findings)
    if verdict == "PASS" and findings:
        # A PASS carrying findings is contradictory and must never pass.
        return ParsedReview(ReviewVerdict.FINDINGS, findings=findings)

    return ParsedReview(
        ReviewVerdict.PROTOCOL_ERROR,
        reason="Reviewer JSON has no valid verdict.",
    )


def _embedded_review_payloads(raw: str) -> list[ParsedReview]:
    """Extract review JSON objects even when an agent adds harmless prose.

    json.JSONDecoder.raw_decode is used instead of a regex so braces and quoted
    text inside findings are handled correctly. Only objects containing a
    verdict field are considered review envelopes.
    """

    parsed: list[ParsedReview] = []
    index = 0

    while True:
        start = raw.find("{", index)
        if start < 0:
            break

        try:
            payload, consumed = _JSON_DECODER.raw_decode(raw[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue

        index = start + max(consumed, 1)
        if not isinstance(payload, dict):
            continue

        review = _parse_review_payload(payload)
        if review is not None:
            parsed.append(review)

    return parsed


def _legacy_markers(raw: str) -> tuple[bool, bool, tuple[str, ...]]:
    """Return explicit legacy PASS/FINDINGS markers from free-form output."""

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    normalized = [line.strip("*_` ").strip().upper() for line in lines]

    has_findings = any(
        line == "FINDINGS"
        or line.startswith("FINDINGS:")
        or line == "VERDICT: FINDINGS"
        for line in normalized
    )
    has_pass = any(
        line == "PASS" or line == "VERDICT: PASS"
        for line in normalized
    )
    findings = tuple(
        line[1:].strip()
        for line in lines
        if line.startswith("-") and line[1:].strip()
    )
    return has_pass, has_findings, findings


def parse_review_verdict(output: str) -> ParsedReview:
    """Parse reviewer output without depending on a brittle free-form prefix.

    Reviewers are asked for a small JSON envelope, but legacy PASS/FINDINGS
    output remains supported. A valid JSON envelope may be surrounded by
    harmless explanatory prose because real agents occasionally ignore the
    JSON-only formatting instruction. Ambiguous or conflicting output is never
    interpreted as PASS.
    """

    raw = (output or "").strip()
    if not raw:
        return ParsedReview(
            ReviewVerdict.PROTOCOL_ERROR,
            reason="Reviewer returned no verdict.",
        )

    # Preserve support for a normal fenced JSON response while also allowing
    # the more general embedded-object extractor below.
    candidate = _JSON_FENCE_RE.sub("", raw).strip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict):
        review = _parse_review_payload(payload)
        if review is not None:
            return review

    embedded = _embedded_review_payloads(raw)
    if embedded:
        if any(item.verdict == ReviewVerdict.PROTOCOL_ERROR for item in embedded):
            return ParsedReview(
                ReviewVerdict.PROTOCOL_ERROR,
                reason="Reviewer response contained an invalid review JSON envelope.",
            )

        semantic_results = {
            (item.verdict, item.findings)
            for item in embedded
        }
        if len(semantic_results) != 1:
            return ParsedReview(
                ReviewVerdict.PROTOCOL_ERROR,
                reason="Reviewer response contained conflicting JSON verdicts.",
            )

        review = embedded[0]
        has_pass, has_findings, _ = _legacy_markers(raw)
        if (
            review.verdict == ReviewVerdict.PASS
            and has_findings
        ) or (
            review.verdict == ReviewVerdict.FINDINGS
            and has_pass
        ):
            return ParsedReview(
                ReviewVerdict.PROTOCOL_ERROR,
                reason="Reviewer response contained conflicting verdict markers.",
            )
        return review

    has_pass, has_findings, findings = _legacy_markers(raw)
    if has_findings:
        return ParsedReview(ReviewVerdict.FINDINGS, findings=findings)
    if has_pass:
        return ParsedReview(ReviewVerdict.PASS)

    return ParsedReview(
        ReviewVerdict.PROTOCOL_ERROR,
        reason="Reviewer response did not contain an unambiguous verdict.",
    )


_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "temporary failure",
    "connection reset",
    "connection refused",
    "connection aborted",
    "network is unreachable",
    "could not resolve host",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "status 429",
    "status 500",
    "status 502",
    "status 503",
    "status 504",
    "rate limit",
    "secondary rate limit",
    "server error",
)


def looks_transient(detail: str) -> bool:
    text = (detail or "").lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


T = TypeVar("T")


def retry_transient(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    initial_delay: float = 1.0,
    is_transient: Callable[[Exception], bool] | None = None,
) -> T:
    """Run a side-effect-safe operation with bounded exponential backoff."""

    attempts = max(1, int(attempts))
    delay = max(0.0, float(initial_delay))
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - classifier decides retryability
            last = exc
            transient = (
                is_transient(exc)
                if is_transient is not None
                else looks_transient(str(exc))
            )
            if not transient or attempt >= attempts:
                raise
            time.sleep(delay)
            delay = max(delay * 2, 0.1)

    assert last is not None
    raise last


def _source_fingerprint() -> str:
    """Fingerprint installed AIpipe Python source when image git metadata is absent.

    Docker images normally do not include the repository's .git directory. A
    content fingerprint still lets the API and worker detect that they are
    running different builds even when the package version was not bumped.
    """

    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:12] if files else "unknown"


def build_identity(repo: Path | None = None) -> str:
    """Return a stable human-readable runtime build identity.

    Preference order is an explicit build SHA, a repository commit, then an
    installed-source fingerprint. This keeps local CLI output intuitive while
    making Docker API/worker builds comparable even without .git metadata.
    """

    try:
        package_version = version("aipipe")
    except PackageNotFoundError:
        package_version = "dev"

    explicit = (
        os.environ.get("AIPIPE_BUILD_SHA")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
    )
    sha = explicit.strip() if explicit else ""

    if not sha and repo and (repo / ".git").exists():
        result = run(["git", "rev-parse", "HEAD"], repo, timeout=10)
        if result.ok:
            sha = result.stdout.strip()

    suffix = sha[:12] if sha else _source_fingerprint()
    return f"{package_version}+{suffix}"
