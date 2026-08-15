from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import ContextClass, Risk, TaskType


DISCOVERY_MARKER = "<!-- aipipe-discovery:{key} -->"

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_JSON_DECODER = json.JSONDecoder()

_VALID_TASK_TYPES = {t.value for t in TaskType if t is not TaskType.DISCOVERY}
_VALID_RISKS = {r.value for r in Risk}
_VALID_CONTEXT_CLASSES = {c.value for c in ContextClass}

_RISK_SCORE = {"LOW": 1.0, "MEDIUM": 0.6, "HIGH": 0.3}
_CONTEXT_SCORE = {"SMALL": 1.0, "NORMAL": 0.6, "DEEP": 0.3}
_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_CONTEXT_ORDER = {"SMALL": 0, "NORMAL": 1, "DEEP": 2}


@dataclass
class FeatureCandidate:
    key: str
    title: str
    summary: str
    rationale: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    task_type: str = TaskType.FEATURE.value
    risk: str = Risk.MEDIUM.value
    context_class: str = ContextClass.NORMAL.value
    labels: list[str] = field(default_factory=list)
    score: float = 0.0
    rank: int | None = None
    status: str = "proposed"
    duplicate_of: str | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    error: str | None = None
    handoff: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "summary": self.summary,
            "rationale": self.rationale,
            "acceptance_criteria": self.acceptance_criteria,
            "task_type": self.task_type,
            "risk": self.risk,
            "context_class": self.context_class,
            "labels": self.labels,
            "score": self.score,
            "rank": self.rank,
            "status": self.status,
            "duplicate_of": self.duplicate_of,
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "error": self.error,
            "handoff": self.handoff,
        }


@dataclass
class DiscoveryResult:
    candidates: list[FeatureCandidate] = field(default_factory=list)
    created: list[FeatureCandidate] = field(default_factory=list)
    duplicates: list[FeatureCandidate] = field(default_factory=list)
    failed: list[FeatureCandidate] = field(default_factory=list)
    handoff_issue_numbers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "created": [c.key for c in self.created],
            "duplicates": [c.key for c in self.duplicates],
            "failed": [c.key for c in self.failed],
            "handoff_issue_numbers": self.handoff_issue_numbers,
        }


def _candidate_key(title: str) -> str:
    return hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()[:12]


def parse_candidates(raw: str) -> list[dict]:
    """Tolerant extraction of the ``{"candidates":[...]}`` envelope.

    Mirrors the ``json.JSONDecoder.raw_decode`` scan idiom used by
    ``reliability._embedded_review_payloads`` so a discovery agent's harmless
    surrounding prose does not prevent the candidate list from being parsed.
    """

    text = (raw or "").strip()
    if not text:
        return []

    candidate = _JSON_FENCE_RE.sub("", text).strip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        return [item for item in payload["candidates"] if isinstance(item, dict)]

    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            break
        try:
            payload, consumed = _JSON_DECODER.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = start + max(consumed, 1)
        if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
            return [item for item in payload["candidates"] if isinstance(item, dict)]

    return []


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def build_candidates(raw: list[dict], max_candidates: int) -> list[FeatureCandidate]:
    """Normalize, validate and cap raw candidate dicts.

    Malformed entries (missing title/summary) are dropped rather than
    blocking the whole batch. Deterministic; no LLM/network calls.
    """

    built: list[FeatureCandidate] = []
    seen_keys: set[str] = set()

    for item in raw:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not title or not summary:
            continue

        key = _candidate_key(title)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        task_type = str(item.get("task_type") or TaskType.FEATURE.value).strip().upper()
        if task_type not in _VALID_TASK_TYPES:
            task_type = TaskType.FEATURE.value

        risk = str(item.get("suggested_risk") or item.get("risk") or Risk.MEDIUM.value).strip().upper()
        if risk not in _VALID_RISKS:
            risk = Risk.MEDIUM.value

        context_class = str(
            item.get("suggested_complexity") or item.get("context_class") or ContextClass.NORMAL.value
        ).strip().upper()
        if context_class not in _VALID_CONTEXT_CLASSES:
            context_class = ContextClass.NORMAL.value

        built.append(
            FeatureCandidate(
                key=key,
                title=title[:200],
                summary=summary[:2000],
                rationale=str(item.get("rationale") or "").strip()[:2000],
                acceptance_criteria=_normalize_list(item.get("acceptance_criteria"))[:10],
                task_type=task_type,
                risk=risk,
                context_class=context_class,
                labels=_normalize_list(item.get("labels"))[:10],
            )
        )
        if len(built) >= max_candidates:
            break

    return built


def score_candidate(candidate: FeatureCandidate) -> float:
    """Deterministic, inspectable score: lower risk/complexity and concrete
    acceptance criteria rank higher. No LLM call.
    """

    risk_component = _RISK_SCORE.get(candidate.risk, 0.6)
    context_component = _CONTEXT_SCORE.get(candidate.context_class, 0.6)
    criteria_component = min(1.0, len(candidate.acceptance_criteria) / 3)
    return round(0.4 * risk_component + 0.3 * context_component + 0.3 * criteria_component, 6)


def rank_candidates(candidates: list[FeatureCandidate]) -> list[FeatureCandidate]:
    """Score and rank candidates in place; returns them sorted best-first.

    Ties break on ``key`` so ranking stays stable/reproducible across runs.
    """

    for candidate in candidates:
        candidate.score = score_candidate(candidate)
    ordered = sorted(candidates, key=lambda c: (-c.score, c.key))
    for index, candidate in enumerate(ordered, start=1):
        candidate.rank = index
    return ordered


def _text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def detect_duplicates(
    candidates: list[FeatureCandidate],
    existing_issues: list[dict],
    existing_prs: list[dict],
    threshold: float = 0.72,
) -> list[FeatureCandidate]:
    """Deterministic duplicate detection against open/closed issues and PRs.

    First pass: an exact discovery-marker match in an issue body (the
    idempotent case — this candidate was already filed by a previous
    discovery run). Second pass: a title/body similarity fallback via
    ``difflib.SequenceMatcher`` for organically-filed duplicates. Mutates
    ``status``/``duplicate_of`` on matched candidates in place.
    """

    for candidate in candidates:
        marker = DISCOVERY_MARKER.format(key=candidate.key)
        marker_match = next(
            (
                issue for issue in existing_issues
                if marker in str(issue.get("body") or "")
            ),
            None,
        )
        if marker_match is not None:
            candidate.status = "duplicate"
            candidate.duplicate_of = f"#{marker_match.get('number')}"
            continue

        best_ratio = 0.0
        best_ref: str | None = None
        for issue in existing_issues:
            ratio = _text_similarity(candidate.title, str(issue.get("title") or ""))
            if ratio > best_ratio:
                best_ratio, best_ref = ratio, f"#{issue.get('number')}"
        for pr in existing_prs:
            ratio = _text_similarity(candidate.title, str(pr.get("title") or ""))
            if ratio > best_ratio:
                best_ratio, best_ref = ratio, f"#{pr.get('number')}"

        if best_ratio >= threshold and best_ref is not None:
            candidate.status = "duplicate"
            candidate.duplicate_of = best_ref

    return candidates


def within_bounds(candidate: FeatureCandidate, max_risk: str, max_context_class: str) -> bool:
    """True when a candidate is eligible for autonomous handoff.

    Compares against the project's configured ceilings (``discovery.max_risk``,
    ``discovery.max_context_class``); unrecognized values are treated as
    exceeding any bound so malformed data never becomes auto-implementable.
    """

    return (
        _RISK_ORDER.get(candidate.risk, 99) <= _RISK_ORDER.get(max_risk, 1)
        and _CONTEXT_ORDER.get(candidate.context_class, 99) <= _CONTEXT_ORDER.get(max_context_class, 1)
    )


def issue_body(candidate: FeatureCandidate) -> str:
    """Structured, implementation-ready issue body mirroring the PR body's
    quality bar (see ``Orchestrator._pr_body``), plus the idempotency marker.
    """

    criteria = "\n".join(f"- {item}" for item in candidate.acceptance_criteria) or "- (none proposed)"
    return (
        f"{DISCOVERY_MARKER.format(key=candidate.key)}\n\n"
        f"_Proposed by AIpipe's automated feature discovery workflow. This issue was not "
        f"implemented automatically; it is queued for the normal Issue → Task → PR → CI → "
        f"Merge pipeline._\n\n"
        f"## Summary\n{candidate.summary}\n\n"
        f"## Rationale\n{candidate.rationale or 'Not provided.'}\n\n"
        f"## Acceptance Criteria\n{criteria}\n\n"
        f"## Suggested routing\n"
        f"- Type: {candidate.task_type}\n"
        f"- Risk: {candidate.risk}\n"
        f"- Context: {candidate.context_class}\n"
        f"- Discovery score: {candidate.score} (rank {candidate.rank})\n"
    )
