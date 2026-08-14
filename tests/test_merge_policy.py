from aipipe.merge_policy import MergeEvidence, merge_allowed


def evidence(**overrides):
    base = dict(
        quality_passed=True,
        secret_scan_passed=True,
        security_commands_passed=True,
        review_passed=True,
        security_review_passed=True,
        ci_passed=True,
        mergeable=True,
        unresolved_blocking_findings=False,
    )
    base.update(overrides)
    return MergeEvidence(**base)


def test_all_evidence_allows_merge():
    assert merge_allowed(evidence())


def test_red_ci_blocks_merge():
    assert not merge_allowed(evidence(ci_passed=False))


def test_findings_block_merge():
    assert not merge_allowed(evidence(unresolved_blocking_findings=True))
