from aipipe.models import ContextClass, Risk, TaskType
from aipipe.router import acceptance_from_text, route_task


def test_docs_low_risk_small_context():
    r = route_task("Fix typo in README documentation")
    assert r.task_type == TaskType.DOCS
    assert r.risk == Risk.LOW
    assert r.context_class == ContextClass.SMALL
    assert "review" not in r.gates


def test_password_auth_is_high_risk():
    r = route_task("Add password reset authentication API with expiring token")
    assert r.risk == Risk.HIGH
    assert "security_review" in r.gates
    assert "authentication" in r.scopes


def test_database_feature_medium():
    r = route_task("Add API endpoint that stores preferences in the database")
    assert r.risk == Risk.MEDIUM
    assert "review" in r.gates


def test_deep_context_independent_of_risk():
    r = route_task("Refactor entire frontend navigation architecture")
    assert r.context_class == ContextClass.DEEP


def test_acceptance_extracts_explicit_language():
    out = acceptance_from_text("The endpoint must reject invalid IDs.\nIt should return JSON.")
    assert len(out) == 2
