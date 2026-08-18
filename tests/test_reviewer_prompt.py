from aipipe.prompts import REVIEWER_SUFFIX


def test_reviewer_prompt_requires_current_repository_evidence_for_blockers():
    assert "current repository state after all remediation already applied" in REVIEWER_SUFFIX
    assert "not on an earlier diff or previous attempt" in REVIEWER_SUFFIX
    assert "Before claiming a function, validation, integration, or test is missing" in REVIEWER_SUFFIX
    assert "imported/helper code" in REVIEWER_SUFFIX
    assert "closest relevant tests" in REVIEWER_SUFFIX
    assert "file/path and relevant symbol or behavior" in REVIEWER_SUFFIX
    assert "acceptance criterion or correctness/security/compatibility property" in REVIEWER_SUFFIX
    assert "HIGH requires a demonstrated material" in REVIEWER_SUFFIX
    assert "MEDIUM requires a demonstrated behavioral or compatibility defect" in REVIEWER_SUFFIX
    assert 'hypothetical "could potentially" concerns are LOW' in REVIEWER_SUFFIX
    assert "If evidence is insufficient, omit the finding." in REVIEWER_SUFFIX
    assert "Passing gates do not by themselves prove semantic correctness." in REVIEWER_SUFFIX


def test_reviewer_prompt_preserves_json_only_protocol():
    assert '{"verdict":"PASS","findings":[]}' in REVIEWER_SUFFIX
    assert '{"verdict":"FINDINGS"' in REVIEWER_SUFFIX
    assert "HIGH/MEDIUM findings block merge." in REVIEWER_SUFFIX
    assert "Do not mix PASS with findings." in REVIEWER_SUFFIX
