from pathlib import Path

from aipipe.context import TRUNCATION_NOTICE, ContextBuilder
from aipipe.context_budget import (
    DEFAULT_TOTAL_BUDGET_TOKENS,
    ROLE_IMPLEMENTER,
    ROLE_IMPLEMENTER_REMEDIATION,
    ROLE_PLANNER,
    ROLE_REVIEWER,
    ROLE_SECURITY_REVIEWER,
    ROLE_TOTAL_BUDGET_TOKENS,
    budget_for,
    estimate_tokens,
)
from aipipe.models import ContextClass, Risk, Route, TaskContract, TaskType
from aipipe.task_map import TaskMap


def _task(context_class: ContextClass, **kwargs) -> TaskContract:
    route = Route(TaskType.FEATURE, Risk.LOW, context_class, ["general"], [])
    return TaskContract(
        "T-1",
        "do the thing",
        acceptance_criteria=kwargs.pop("acceptance_criteria", ["works"]),
        route=route,
        **kwargs,
    )


def test_estimate_tokens_is_deterministic_and_conservative():
    text = "a" * 300
    assert estimate_tokens(text) == estimate_tokens(text)
    assert estimate_tokens(text) >= len(text) // 4
    assert estimate_tokens("") == 0


def test_budgets_increase_monotonically_across_small_normal_deep():
    for role_table in list(ROLE_TOTAL_BUDGET_TOKENS.values()) + [DEFAULT_TOTAL_BUDGET_TOKENS]:
        small = role_table[ContextClass.SMALL]
        normal = role_table[ContextClass.NORMAL]
        deep = role_table[ContextClass.DEEP]
        assert small < normal < deep


def test_roles_have_distinct_budgets_for_the_same_context_class():
    roles = [ROLE_PLANNER, ROLE_IMPLEMENTER, ROLE_IMPLEMENTER_REMEDIATION, ROLE_REVIEWER, ROLE_SECURITY_REVIEWER]
    budgets = {role: budget_for(role, ContextClass.NORMAL).total_tokens for role in roles}
    # Remediation runs must be strictly smaller than the initial implementer budget.
    assert budgets[ROLE_IMPLEMENTER_REMEDIATION] < budgets[ROLE_IMPLEMENTER]
    # At least one other role differs from the initial implementer budget.
    assert len(set(budgets.values())) > 1


def test_unknown_role_falls_back_to_default_budget_table():
    b = budget_for("ROUTER", ContextClass.SMALL)
    assert b.total_tokens == DEFAULT_TOTAL_BUDGET_TOKENS[ContextClass.SMALL]
    b_none = budget_for(None, None)
    assert b_none.total_tokens == DEFAULT_TOTAL_BUDGET_TOKENS[ContextClass.NORMAL]


def test_total_budget_is_enforced_for_oversized_optional_sections(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("p" * 20_000, encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: general\nStatus: active\n" + ("d" * 20_000) + "\n",
        encoding="utf-8",
    )
    (repo / ".ai" / "LEARNINGS.md").write_text(
        "## general\nTags: general\nStatus: active\n" + ("k" * 20_000) + "\n",
        encoding="utf-8",
    )
    task = _task(ContextClass.SMALL)
    builder = ContextBuilder(global_root)

    huge_diff = "x" * 200_000
    huge_findings = "n" * 200_000
    text = builder.build(repo, task, "IMPLEMENTER", diff=huge_diff, findings=huge_findings)

    budget = budget_for("IMPLEMENTER", ContextClass.SMALL)
    # Allow modest overhead for the truncation marker/notice; the assembled
    # prompt must stay in the same order of magnitude as the budget, not grow
    # unbounded with the oversized input.
    assert len(text) <= budget.total_chars + 2000
    assert TRUNCATION_NOTICE in text


def test_protected_sections_survive_a_tiny_budget(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "AGENT.md").write_text("Global agent rules body.", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("x" * 50_000, encoding="utf-8")

    task = _task(
        ContextClass.SMALL,
        acceptance_criteria=["criterion one", "criterion two"],
        out_of_scope=["do not touch billing"],
    )
    builder = ContextBuilder(global_root)

    text = builder.build(repo, task, "IMPLEMENTER", diff="y" * 100_000, budget_role="IMPLEMENTER_REMEDIATION")

    assert "do the thing" in text
    assert "criterion one" in text
    assert "criterion two" in text
    assert "# Out of Scope" in text
    assert "do not touch billing" in text
    assert "Global agent rules body." in text


def test_lower_priority_sections_are_dropped_before_diff(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "AGENT.md").write_text("agent rules body", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("y" * 8000, encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: general\nStatus: active\n" + ("z" * 20_000) + "\n",
        encoding="utf-8",
    )
    (repo / ".ai" / "LEARNINGS.md").write_text(
        "## general\nTags: general\nStatus: active\n" + ("k" * 20_000) + "\n",
        encoding="utf-8",
    )

    route = Route(TaskType.FEATURE, Risk.HIGH, ContextClass.SMALL, ["general"], [])
    task = TaskContract("T-1", "do the thing", acceptance_criteria=["works"], route=route)
    builder = ContextBuilder(global_root)
    diff = "diffmarker-" + ("d" * 17000)
    findings = "findingsmarker-" + ("n" * 7000)

    text = builder.build(
        repo, task, "IMPLEMENTER", diff=diff, findings=findings, budget_role="IMPLEMENTER_REMEDIATION"
    )

    # Lowest-priority optional sections (decisions/learnings, both
    # drop_priority 0) are dropped entirely before the diff/findings, which
    # are kept longest among optional content.
    assert "# Relevant Decisions" not in text
    assert "# Relevant Learnings" not in text
    assert "# Current Diff" in text
    assert diff in text
    assert "# Findings To Address" in text
    assert findings in text
    assert TRUNCATION_NOTICE in text


def test_repository_index_is_truncated_or_omitted_under_a_tight_budget(tmp_path: Path):
    from aipipe.repo_index import RepoIndexCache
    from aipipe.util import run

    def git(cwd: Path, *args: str):
        r = run(["git", *args], cwd)
        assert r.ok, r.stderr
        return r

    global_root = tmp_path / "global"
    global_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    for i in range(40):
        (repo / f"module_{i}.py").write_text(f"def handler_{i}():\n    pass\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")

    task = _task(ContextClass.SMALL)
    cache = RepoIndexCache(tmp_path / "index-cache")
    builder = ContextBuilder(global_root, cache)

    text = builder.build(repo, task, "IMPLEMENTER", diff="e" * 5000, budget_role="IMPLEMENTER_REMEDIATION")

    # Must not raise, and the task contract must still be present regardless
    # of whether the index survived truncation.
    assert "# Task" in text
    budget = budget_for("IMPLEMENTER_REMEDIATION", ContextClass.SMALL)
    assert len(text) <= budget.total_chars + 2000


def test_task_contract_never_displaced_when_every_optional_section_is_huge(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "AGENT.md").write_text("agent rules", encoding="utf-8")
    (global_root / "LEARNINGS.md").write_text(
        "## general\nTags: general\nStatus: active\n" + ("l" * 30_000) + "\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("p" * 30_000, encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: general\nStatus: active\n" + ("d" * 30_000) + "\n",
        encoding="utf-8",
    )
    (repo / ".ai" / "LEARNINGS.md").write_text(
        "## general\nTags: general\nStatus: active\n" + ("k" * 30_000) + "\n",
        encoding="utf-8",
    )

    task = _task(
        ContextClass.SMALL,
        acceptance_criteria=["must not break auth"],
        out_of_scope=["billing"],
    )
    builder = ContextBuilder(global_root)

    text = builder.build(
        repo,
        task,
        "IMPLEMENTER",
        diff="f" * 100_000,
        findings="g" * 100_000,
        budget_role="IMPLEMENTER_REMEDIATION",
    )

    assert "do the thing" in text
    assert "must not break auth" in text
    assert "billing" in text
    assert "agent rules" in text


def test_safe_behavior_when_context_is_extremely_large(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "SECURITY.md").write_text("no secrets", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("p" * 20_000, encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: general\nStatus: active\n" + ("d" * 20_000) + "\n",
        encoding="utf-8",
    )

    route = Route(TaskType.SECURITY, Risk.HIGH, ContextClass.SMALL, ["general"], [])
    task = TaskContract(
        "T-big",
        "x" * 5000,
        acceptance_criteria=["a" * 500 for _ in range(20)],
        route=route,
    )
    builder = ContextBuilder(global_root)

    # Should not raise despite a pathologically large combined input.
    text = builder.build(
        repo,
        task,
        "IMPLEMENTER",
        diff="d" * 500_000,
        findings="n" * 500_000,
        budget_role="IMPLEMENTER_REMEDIATION",
    )
    assert "# Security Rules" in text
    assert "# Task" in text
    assert "a" * 500 in text
    assert TRUNCATION_NOTICE in text


def test_maximal_task_map_stays_bounded_and_does_not_crowd_out_other_protected_sections(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "AGENT.md").write_text("agent rules body", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("p" * 20_000, encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: general\nStatus: active\n" + ("d" * 20_000) + "\n",
        encoding="utf-8",
    )

    task = _task(
        ContextClass.SMALL,
        acceptance_criteria=["must not break auth"],
        out_of_scope=["billing"],
    )
    builder = ContextBuilder(global_root)
    oversized_task_map = TaskMap(
        relevant_files=tuple(f"src/module_{i}.py" * 5 for i in range(100)),
        relevant_symbols=tuple(f"Symbol{i}" * 5 for i in range(100)),
        likely_tests=tuple(f"tests/test_{i}.py" * 5 for i in range(100)),
        constraints=tuple(f"constraint {i}" * 5 for i in range(100)),
        risks=tuple(f"risk {i}" * 5 for i in range(100)),
        out_of_scope=tuple(f"out of scope {i}" * 5 for i in range(100)),
    )

    text = builder.build(
        repo,
        task,
        "IMPLEMENTER",
        plan="Goal\nDo the thing.\n",
        task_map=oversized_task_map,
        diff="d" * 100_000,
        findings="f" * 100_000,
    )

    budget = budget_for("IMPLEMENTER", ContextClass.SMALL)
    assert len(text) <= budget.total_chars + 3000
    assert "do the thing" in text
    assert "must not break auth" in text
    assert "billing" in text
    assert "agent rules body" in text
    assert "# Task Map" in text


def test_backward_compatible_with_existing_small_normal_tasks(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "AGENT.md").write_text("minimal", encoding="utf-8")
    (global_root / "SECURITY.md").write_text("secure", encoding="utf-8")
    (global_root / "LEARNINGS.md").write_text("", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("project", encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: auth\nStatus: active\nKeep auth server-side.\n",
        encoding="utf-8",
    )
    (repo / ".ai" / "LEARNINGS.md").write_text("", encoding="utf-8")
    route = Route(TaskType.FEATURE, Risk.HIGH, ContextClass.NORMAL, ["auth"], [])
    task = TaskContract("T-1", "auth thing", acceptance_criteria=["works"], route=route)

    text = ContextBuilder(global_root).build(repo, task, "IMPLEMENTER")

    assert "Keep auth server-side" in text
    assert "# Security Rules" in text
    assert TRUNCATION_NOTICE not in text
