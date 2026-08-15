"""Deterministic, human-readable activity derivation for the task page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from ..reliability import ReviewVerdict, parse_review_verdict


TERMINAL_STATUSES = {"DONE", "BLOCKED", "FAILED", "CANCELLED"}
BLOCKER_STATUSES = {"BLOCKED", "FAILED", "CANCELLED", "NEEDS_INPUT"}
_NON_PROGRESS_STATUSES = TERMINAL_STATUSES | {"NEEDS_INPUT"}

PHASE_ORDER = [
    "QUEUED",
    "ROUTING",
    "PREPARING",
    "DISCOVERY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "PR_OPEN",
    "CI",
    "MERGING",
    "POST_MERGE",
    "DONE",
]

PHASE_INFO: dict[str, tuple[str, str]] = {
    "QUEUED": ("Queued", "Waiting for a worker to pick up the task."),
    "ROUTING": ("Routing the task", "Classifying task type, risk level, and scope."),
    "PREPARING": ("Preparing the workspace", "Creating a working branch and installing project dependencies."),
    "DISCOVERY": ("Exploring the repository", "Reviewing repository structure and conventions relevant to the task."),
    "PLANNING": ("Planning the implementation", "Deciding the implementation approach before writing code."),
    "IMPLEMENTING": ("Implementing the change", "Writing code changes to satisfy the task requirements."),
    "VERIFYING": ("Running verification", "Running quality, security, and secret-scanning checks."),
    "REVIEWING": ("Independent review", "A reviewer agent is checking the implementation against the task requirements and repository constraints."),
    "PR_OPEN": ("Opening pull request", "Pushing the branch and opening a pull request."),
    "CI": ("Waiting on CI", "Waiting for GitHub Actions checks to complete."),
    "MERGING": ("Merging", "Merging the approved pull request."),
    "POST_MERGE": ("Finalizing", "Confirming the merge and cleaning up the workspace."),
    "DONE": ("Completed", "The task finished successfully."),
    "BLOCKED": ("Blocked", "The pipeline stopped because a required gate did not pass."),
    "NEEDS_INPUT": ("Needs input", "The task needs additional input before it can continue."),
    "FAILED": ("Failed", "The task stopped because of an unexpected error."),
    "CANCELLED": ("Cancelled", "The task was cancelled."),
}

CHECK_TITLES = {
    "setup": "Setup checks",
    "quality": "Quality checks",
    "security": "Security checks",
    "quality-final": "Final quality checks",
    "security-final": "Final security checks",
    "quality-ci-fix": "Quality checks (CI fix)",
    "security-ci-fix": "Security checks (CI fix)",
    "quality-ci-review-repair": "Quality checks (review repair)",
}

_ATTEMPT_RE = re.compile(r"attempt=(\d+)\s+rc=(-?\d+)")


def next_phase_label(status: str) -> str | None:
    if status not in PHASE_ORDER:
        return None
    index = PHASE_ORDER.index(status)
    if index + 1 >= len(PHASE_ORDER):
        return None
    return PHASE_INFO[PHASE_ORDER[index + 1]][0]


def _severity_for_status(status: str) -> str:
    if status in {"BLOCKED", "FAILED"}:
        return "error"
    if status in {"CANCELLED", "NEEDS_INPUT"}:
        return "warning"
    if status == "DONE":
        return "success"
    return "info"


def _parse_json(text: Any, default: Any) -> Any:
    if not text or not isinstance(text, str):
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _review_result(output: str) -> tuple[bool, str]:
    parsed = parse_review_verdict(output)
    if parsed.verdict == ReviewVerdict.PASS:
        return True, "Review passed."
    if parsed.verdict == ReviewVerdict.PROTOCOL_ERROR:
        return False, parsed.reason or "Reviewer returned an invalid verdict."
    return False, "Reviewer requested changes."


@dataclass
class ActivityItem:
    category: str
    title: str
    summary: str
    result: str | None
    next_step: str | None
    status: str
    timestamp: datetime
    duration_seconds: float | None
    technical_event_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "result": self.result,
            "next_step": self.next_step,
            "status": self.status,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "technical_event_id": self.technical_event_id,
        }


@dataclass
class _CheckBatch:
    item: ActivityItem
    total: int = 0
    passed: int = 0
    failed: list[str] = field(default_factory=list)


class _Builder:
    def __init__(self, agent_label: str):
        self.agent_label = agent_label
        self.items: list[ActivityItem] = []
        self.phase_items: list[ActivityItem] = []
        self.open_phase: ActivityItem | None = None
        self.current_status: str | None = None
        self._check_batches: dict[str, _CheckBatch] = {}
        self.latest_checks: dict[tuple[str, str], dict[str, Any]] = {}
        self.latest_review: dict[str, Any] | None = None
        self.latest_security_review: dict[str, Any] | None = None
        self.latest_ci: dict[str, Any] | None = None

    def _close_phase(self, end_ts: datetime) -> None:
        if not self.open_phase:
            return
        self.open_phase.duration_seconds = max(
            0.0,
            (end_ts - self.open_phase.timestamp).total_seconds(),
        )
        self.open_phase = None
        self._check_batches = {}

    def _open_phase(self, status: str, ts: datetime, event_id: int | None) -> ActivityItem:
        title, summary = PHASE_INFO.get(
            status,
            (status.replace("_", " ").title(), ""),
        )
        item = ActivityItem(
            category=status,
            title=title,
            summary=summary,
            result=None,
            next_step=next_phase_label(status),
            status=_severity_for_status(status),
            timestamp=ts,
            duration_seconds=None,
            technical_event_id=event_id,
        )
        self.items.append(item)
        self.phase_items.append(item)
        self.current_status = status
        self.open_phase = item if status not in _NON_PROGRESS_STATUSES else None
        return item

    def _append(
        self,
        category: str,
        title: str,
        summary: str,
        result: str | None,
        status: str,
        ts: datetime,
        event_id: int | None,
    ) -> ActivityItem:
        item = ActivityItem(
            category=category,
            title=title,
            summary=summary,
            result=result,
            next_step=None,
            status=status,
            timestamp=ts,
            duration_seconds=None,
            technical_event_id=event_id,
        )
        self.items.append(item)
        return item

    def handle(self, event: Any) -> None:
        kind = event.kind
        ts = event.created_at
        event_id = event.id

        if kind == "QUEUED":
            self._open_phase("QUEUED", ts, event_id)
            return
        if kind == "CLAIMED":
            if self.open_phase and self.open_phase.category == "QUEUED":
                self.open_phase.result = "A worker claimed the task."
            return
        if kind == "CORE_TASK_CREATED":
            return
        if kind == "WORKER_LOST":
            self._close_phase(ts)
            self._append(
                "FAILED",
                "Worker lost",
                "The worker running this task stopped sending heartbeats.",
                event.detail,
                "error",
                ts,
                event_id,
            )
            self.current_status = "FAILED"
            return
        if kind in {"BLOCKED", "FAILED"}:
            return

        if kind == "core:status":
            payload = _parse_json(event.detail, {})
            status = str(payload.get("status") or "")
            detail = payload.get("detail")
            self._close_phase(ts)
            item = self._open_phase(status, ts, event_id)
            if status in BLOCKER_STATUSES and detail:
                item.result = detail
            return

        if kind == "core:task_updated":
            if not self.open_phase:
                return
            payload = _parse_json(event.detail, {})
            fields = payload.get("fields") or {}
            if self.open_phase.category == "ROUTING" and fields.get("risk"):
                context = fields.get("context_class")
                self.open_phase.result = (
                    f"Classified as {fields['risk']} risk"
                    + (f", {context} context." if context else ".")
                )
            elif self.open_phase.category == "PREPARING" and fields.get("branch"):
                self.open_phase.result = f"Created branch `{fields['branch']}`."
            elif self.open_phase.category == "PR_OPEN" and fields.get("pr_number") is not None:
                self.open_phase.result = f"Opened pull request #{fields['pr_number']}."
            return

        if kind == "core:event":
            self._handle_core_event(event, ts, event_id)
            return
        if kind == "core:check":
            self._handle_check(event, ts, event_id)
            return
        if kind == "core:finding":
            self._handle_finding(event, ts, event_id)
            return

    def _handle_core_event(self, event: Any, ts: datetime, event_id: int | None) -> None:
        payload = _parse_json(event.detail, {})
        inner = payload.get("event")
        detail_text = payload.get("detail") or ""
        category = self.current_status or "UNKNOWN"

        if inner == "IMPLEMENTER_RUN":
            match = _ATTEMPT_RE.search(detail_text)
            attempt = match.group(1) if match else "?"
            ok = bool(match) and match.group(2) == "0"
            self._append(
                category,
                f"Implementer attempt {attempt}",
                f"{self.agent_label} wrote code changes for the task.",
                "Change applied." if ok else "Attempt produced no usable change.",
                "success" if ok else "warning",
                ts,
                event_id,
            )
            return

        if inner in {"REVIEW", "SECURITY_REVIEW"}:
            ok, result = _review_result(detail_text)
            if inner == "REVIEW":
                title = "Reviewing implementation"
                summary = (
                    f"{self.agent_label} is checking the implementation against "
                    "the task requirements and repository constraints."
                )
            else:
                title = "Security review"
                summary = f"{self.agent_label} is checking the change for security issues."
            item = self._append(
                category,
                title,
                summary,
                result,
                "success" if ok else "warning",
                ts,
                event_id,
            )
            value = {"status": item.status, "result": result, "updated_at": ts}
            if inner == "REVIEW":
                self.latest_review = value
            else:
                self.latest_security_review = value
            return

        if inner == "CI":
            checks = _parse_json(detail_text, [])
            if not isinstance(checks, list):
                checks = []
            passed = [check for check in checks if check.get("bucket") == "pass"]
            failed = [check for check in checks if check.get("bucket") == "fail"]
            if not checks:
                result, status = "No CI checks reported yet.", "info"
            elif failed:
                names = ", ".join(check.get("name", "check") for check in failed[:5])
                result, status = (
                    f"{len(passed)}/{len(checks)} checks passed. Failed: {names}.",
                    "warning",
                )
            elif len(passed) < len(checks):
                result, status = (
                    f"{len(passed)}/{len(checks)} checks passed so far.",
                    "info",
                )
            else:
                result, status = f"All {len(checks)} checks passed.", "success"
            self._append(
                category,
                "CI checks",
                "GitHub Actions is validating the pull request.",
                result,
                status,
                ts,
                event_id,
            )
            self.latest_ci = {
                "total": len(checks),
                "passed": len(passed),
                "failed": len(failed),
            }
            return

        self._append(category, inner or "Activity", "", None, "info", ts, event_id)

    def _handle_check(self, event: Any, ts: datetime, event_id: int | None) -> None:
        payload = _parse_json(event.detail, {})
        check_type = str(payload.get("check_type") or "check")
        name = str(payload.get("name") or "check")
        check_status = str(payload.get("status") or "")
        category = self.current_status or "UNKNOWN"
        self.latest_checks[(check_type, name)] = {
            "type": check_type,
            "name": name,
            "status": check_status,
            "updated_at": ts,
        }

        batch = self._check_batches.get(check_type)
        if batch is None:
            title = CHECK_TITLES.get(
                check_type,
                check_type.replace("-", " ").title(),
            )
            item = self._append(
                category,
                title,
                "Running configured project checks.",
                None,
                "info",
                ts,
                event_id,
            )
            batch = _CheckBatch(item=item)
            self._check_batches[check_type] = batch

        batch.total += 1
        if check_status == "PASS":
            batch.passed += 1
        else:
            batch.failed.append(name)

        if batch.failed:
            batch.item.status = "warning"
            batch.item.result = (
                f"{batch.passed}/{batch.total} checks passed. "
                f"Failed: {', '.join(batch.failed)}."
            )
        else:
            batch.item.status = "success"
            batch.item.result = f"{batch.passed}/{batch.total} checks passed."

    def _handle_finding(self, event: Any, ts: datetime, event_id: int | None) -> None:
        payload = _parse_json(event.detail, {})
        source = str(payload.get("source") or "scan")
        severity = str(payload.get("severity") or "").upper()
        description = payload.get("description") or "A potential issue was found."
        category = self.current_status or "UNKNOWN"
        title = (
            "Secret scan finding"
            if source == "secret_scan"
            else f"{source.replace('_', ' ').title()} finding"
        )
        status = "error" if severity in {"HIGH", "CRITICAL"} else "warning"
        self._append(
            category,
            title,
            "A finding was raised against the change.",
            description,
            status,
            ts,
            event_id,
        )


def build_activity_feed(task: Any, events: Iterable[Any], agent_label: str) -> dict[str, Any]:
    builder = _Builder(agent_label)
    for event in sorted(events, key=lambda item: item.id):
        builder.handle(event)

    status = str(getattr(task, "status", "") or "")
    current = None
    if builder.open_phase is not None and status not in TERMINAL_STATUSES:
        current = {
            "title": builder.open_phase.title,
            "summary": builder.open_phase.summary,
            "phase": builder.open_phase.category,
            "started_at": builder.open_phase.timestamp,
            "next_step": builder.open_phase.next_step,
            "agent_label": agent_label,
        }

    blocker = None
    if status in BLOCKER_STATUSES:
        reason = getattr(task, "error", None)
        if not reason and builder.items:
            reason = builder.items[-1].result
        progress_phases = [
            phase
            for phase in builder.phase_items
            if phase.category not in _NON_PROGRESS_STATUSES
        ]
        last_phase = progress_phases[-1].title if progress_phases else None
        default_reason = (
            "Waiting for additional input."
            if status == "NEEDS_INPUT"
            else "No error detail was recorded."
        )
        blocker = {
            "reason": reason or default_reason,
            "last_phase": last_phase,
            "category": getattr(task, "failure_category", None),
        }

    return {
        "items": [item.to_dict() for item in builder.items],
        "current": current,
        "blocker": blocker,
        "checks": {
            "checks": [
                builder.latest_checks[key]
                for key in sorted(builder.latest_checks)
            ],
            "review": builder.latest_review,
            "security_review": builder.latest_security_review,
            "ci": builder.latest_ci,
        },
    }
