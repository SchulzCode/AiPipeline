from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MergeEvidence:
    quality_passed: bool
    secret_scan_passed: bool
    security_commands_passed: bool
    review_passed: bool
    security_review_passed: bool
    ci_passed: bool
    mergeable: bool
    unresolved_blocking_findings: bool = False


def merge_allowed(e: MergeEvidence) -> bool:
    return all([
        e.quality_passed,
        e.secret_scan_passed,
        e.security_commands_passed,
        e.review_passed,
        e.security_review_passed,
        e.ci_passed,
        e.mergeable,
        not e.unresolved_blocking_findings,
    ])
