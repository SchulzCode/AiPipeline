from types import SimpleNamespace

from aipipe.models import ContextClass, Risk, TaskType
from aipipe.router import acceptance_from_text, planner_required, route_task


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


def _config(**overrides):
    defaults = dict(planner_enabled=True, planner_context_classes=("DEEP",))
    return SimpleNamespace(**{**defaults, **overrides})


def test_planner_required_for_deep_context_by_default():
    assert planner_required(ContextClass.DEEP, _config()) is True


def test_planner_not_required_for_small_or_normal_context_by_default():
    assert planner_required(ContextClass.SMALL, _config()) is False
    assert planner_required(ContextClass.NORMAL, _config()) is False


def test_planner_disabled_globally_skips_even_deep_context():
    assert planner_required(ContextClass.DEEP, _config(planner_enabled=False)) is False


def test_planner_threshold_is_configurable_to_include_normal():
    cfg = _config(planner_context_classes=("NORMAL", "DEEP"))
    assert planner_required(ContextClass.NORMAL, cfg) is True
    assert planner_required(ContextClass.SMALL, cfg) is False


def test_planner_required_accepts_plain_string_context_class():
    assert planner_required("DEEP", _config()) is True
    assert planner_required("small", _config()) is False


def test_planner_required_defaults_are_safe_without_config_attributes():
    # A config object missing the planner fields entirely still behaves like
    # the documented default (DEEP-only, enabled) rather than raising.
    assert planner_required(ContextClass.DEEP, SimpleNamespace()) is True
    assert planner_required(ContextClass.NORMAL, SimpleNamespace()) is False


def test_risk_and_context_class_are_independent_for_planning():
    # A high-risk but architecturally simple task should not require planning
    # (context_class is NORMAL), while a low-risk but deep/architectural one
    # should (context_class is DEEP) -- planning tracks complexity, not risk.
    high_risk_normal = route_task("Add a new admin permission flag toggle")
    assert high_risk_normal.risk == Risk.HIGH
    assert high_risk_normal.context_class == ContextClass.NORMAL
    deep_low_risk = route_task("Refactor entire frontend navigation architecture")
    assert planner_required(high_risk_normal.context_class, _config()) is False
    assert planner_required(deep_low_risk.context_class, _config()) is True
