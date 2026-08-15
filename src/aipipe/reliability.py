from __future__ import annotations

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


def parse_review_verdict(output: str) -> ParsedReview:
    """Parse reviewer output without depending on a brittle free-form prefix.

    New reviewers are asked for a small JSON envelope, but legacy PASS/FINDINGS
    output remains supported so old agent versions and recorded fixtures keep
    working. Ambiguous/conflicting output is never interpreted as PASS.
    """

    raw = (output or "").strip()
    if not raw:
        return ParsedReview(
            ReviewVerdict.PROTOCOL_ERROR,
            reason="Reviewer returned no verdict.",
        )

    candidate = _JSON_FENCE_RE.sub("", raw).strip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict):
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
        if verdict == "FINDINGS" or findings:
            return ParsedReview(ReviewVerdict.FINDINGS, findings=findings)
        return ParsedReview(
            ReviewVerdict.PROTOCOL_ERROR,
            reason="Reviewer JSON has no valid verdict.",
        )

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    upper = [line.upper() for line in lines]
    has_findings = any(
        line == "FINDINGS" or line.startswith("FINDINGS:")
        for line in upper
    )
    has_pass = any(line == "PASS" for line in upper)

    if has_findings:
        findings = tuple(
            line[1:].strip()
            for line in lines
            if line.startswith("-") and line[1:].strip()
        )
        return ParsedReview(ReviewVerdict.FINDINGS, findings=findings)

    if upper and upper[-1] == "PASS" and has_pass:
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


def build_identity(repo: Path | None = None) -> str:
    """Return a stable human-readable runtime build identity."""

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

    suffix = sha[:12] if sha else "unknown"
    return f"{package_version}+{suffix}"
