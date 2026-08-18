"""Unit tests for `Orchestrator._derive_bounded_guidance_from_task_map` (#50).

This is the single derivation point for the bounded, structured Planner
guidance (`dict[str, list[str]]`) that `run()` threads into every later
remediation stage. These tests cover the pure derivation function in
isolation; see `test_remediation_guidance.py` for tests that exercise the
real orchestration paths (`_ensure_local_gates`, `_review_gate`,
`_semantic_gates_after_change`, `_run_ci_gate`, `run()`) that consume its
output.
"""

import json

from aipipe.orchestrator import Orchestrator
from aipipe.task_map import TaskMap, parse_task_map


def test_bounded_guidance_derivation_from_task_map():
    task_map = TaskMap(
        relevant_files=("src/aipipe/orchestrator.py",),
        relevant_symbols=("Orchestrator.run",),
        likely_tests=("tests/test_orchestrator_hardening.py",),
        constraints=("Planner stays read-only", "No external API calls"),
        risks=("Must not block DEEP tasks without a map", "Potential performance issues"),
        out_of_scope=("#50 constraint persistence", "Security audit"),
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)

    # Only constraints/risks/out_of_scope are relevant remediation guidance;
    # relevant_files/relevant_symbols/likely_tests are exploration aids the
    # initial Implementer prompt already covers via the rendered task map,
    # not something later remediation stages need repeated.
    assert set(bounded_guidance) == {"constraints", "risks", "out_of_scope"}
    assert bounded_guidance["constraints"] == ["Planner stays read-only", "No external API calls"]
    assert bounded_guidance["risks"] == ["Must not block DEEP tasks without a map", "Potential performance issues"]
    assert bounded_guidance["out_of_scope"] == ["#50 constraint persistence", "Security audit"]


def test_bounded_guidance_with_empty_task_map():
    orchestrator = Orchestrator.__new__(Orchestrator)
    assert orchestrator._derive_bounded_guidance_from_task_map(TaskMap()) == {}


def test_bounded_guidance_with_partial_task_map():
    task_map = TaskMap(
        relevant_files=("src/aipipe/orchestrator.py",),
        constraints=("Planner stays read-only",),
        risks=(),
        out_of_scope=("#50 constraint persistence",),
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)

    assert "risks" not in bounded_guidance
    assert bounded_guidance["constraints"] == ["Planner stays read-only"]
    assert bounded_guidance["out_of_scope"] == ["#50 constraint persistence"]


def test_missing_planner_result_degrades_safely_to_empty_guidance():
    """No Planner ran / no TaskMap: `task_map=None` degrades to `{}`, not an error."""
    orchestrator = Orchestrator.__new__(Orchestrator)
    assert orchestrator._derive_bounded_guidance_from_task_map(None) == {}


def test_bounded_guidance_handles_none_fields():
    task_map = TaskMap(
        relevant_files=("src/aipipe/orchestrator.py",),
        constraints=None,
        risks=None,
        out_of_scope=None,
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    assert orchestrator._derive_bounded_guidance_from_task_map(task_map) == {}


def test_bounded_guidance_never_carries_relevant_files_symbols_or_tests():
    """These fields are exploration aids for the initial prompt, not remediation state."""
    task_map = TaskMap(
        relevant_files=("a.py", "b.py"),
        relevant_symbols=("Foo.bar",),
        likely_tests=("tests/test_a.py",),
        constraints=("stay bounded",),
    )

    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)

    assert "relevant_files" not in bounded_guidance
    assert "relevant_symbols" not in bounded_guidance
    assert "likely_tests" not in bounded_guidance


def test_bounded_guidance_end_to_end_preserves_task_map_hard_caps():
    """Derivation must not widen TaskMap's own bounds (10 items/160 chars per field, #49/#50).

    Goes through the real `parse_task_map` -> `_derive_bounded_guidance_from_task_map`
    pipeline with an oversized Planner payload, the same as a real PLAN event
    would contain, to prove the caps survive the full path rather than only
    the `TaskMap` construction path already covered by `test_task_map.py`.
    """
    oversized_plan = (
        "Goal\nDo the thing.\n\n```json\n"
        + json.dumps(
            {
                "constraints": [f"constraint {i} " + "x" * 500 for i in range(50)],
                "risks": [f"risk {i} " + "y" * 500 for i in range(50)],
                "out_of_scope": [f"out of scope {i} " + "z" * 500 for i in range(50)],
            }
        )
        + "\n```\n"
    )

    task_map = parse_task_map(oversized_plan)
    assert task_map is not None

    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)

    for key in ("constraints", "risks", "out_of_scope"):
        assert len(bounded_guidance[key]) <= 10
        assert all(len(item) <= 160 for item in bounded_guidance[key])
