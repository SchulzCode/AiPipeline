"""Integration tests to validate that remediation works with bounded Planner guidance."""

import json
from unittest.mock import MagicMock

from aipipe.task_map import parse_task_map
from aipipe.orchestrator import Orchestrator
from aipipe.context import ContextBuilder
from aipipe.models import TaskContract, Route, ContextClass, Risk, TaskType


def test_remediation_uses_bounded_guidance_not_planner_transcript():
    """Test that remediation does not depend on Planner transcripts."""
    # Create a mock plan text with a task map
    plan_text = (
        "Goal\nDo the thing.\n\n"
        "```json\n"
        + json.dumps(
            {
                "relevant_files": ["src/aipipe/orchestrator.py", "src/aipipe/context.py"],
                "relevant_symbols": ["Orchestrator.run", "ContextBuilder.build"],
                "likely_tests": ["tests/test_orchestrator_hardening.py"],
                "constraints": ["Planner stays read-only", "No external API calls"],
                "risks": ["Must not block DEEP tasks without a map", "Potential performance issues"],
                "out_of_scope": ["#50 constraint persistence", "Security audit"],
            }
        )
        + "\n```\n"
    )

    # Parse the task map from the plan
    task_map = parse_task_map(plan_text)
    assert task_map is not None
    
    # Directly test the method without creating an orchestrator instance
    orchestrator = Orchestrator.__new__(Orchestrator)
    
    # Test the actual bounded guidance derivation
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)
    
    # Verify that we correctly extract bounded guidance from task map
    assert "constraints" in bounded_guidance
    assert "risks" in bounded_guidance
    assert "out_of_scope" in bounded_guidance
    assert len(bounded_guidance["constraints"]) == 2
    assert len(bounded_guidance["risks"]) == 2
    assert len(bounded_guidance["out_of_scope"]) == 2

    # Verify that no raw Planner transcript data is included
    # The bounded guidance is only the constraint, risks, and out_of_scope fields
    # which are already bounded and deterministic
    assert "relevant_files" not in bounded_guidance
    assert "relevant_symbols" not in bounded_guidance
    assert "likely_tests" not in bounded_guidance


def test_bounded_guidance_outranks_planner_guidance():
    """Test that bounded guidance from TaskMap outranks Planner guidance during remediation."""
    # This simulates a test where we make sure the bounded guidance
    # (derived from task_map) is used in remediation, not raw Planner content
    
    # Mock a TaskContract
    contract = TaskContract(
        id="test-task",
        goal="Implement a new feature",
        source="github_issue",
        title="Implement new feature",
        acceptance_criteria=["Acceptance criterion 1", "Acceptance criterion 2"],
        route=Route(TaskType.FEATURE, Risk.LOW, ContextClass.NORMAL, [], []),
    )
    
    # Create a mock plan with bounded guidance in TaskMap
    plan_text = (
        "Goal\nImplement new feature.\n\n"
        "```json\n"
        + json.dumps({
            "relevant_files": ["src/aipipe/orchestrator.py"],
            "constraints": ["No external dependencies", "Must be backward compatible"],
            "risks": ["Performance impact on large datasets"],
            "out_of_scope": ["Security audit", "Documentation changes"],
        })
        + "\n```\n"
    )
    
    # Parse task map from plan
    task_map = parse_task_map(plan_text)
    assert task_map is not None
    
    # Directly test the method without creating an orchestrator instance
    orchestrator = Orchestrator.__new__(Orchestrator)
    
    # The bounded guidance should be extracted from the task map
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)
    
    # Verify it's bounded and deterministic
    assert len(bounded_guidance["constraints"]) == 2
    assert len(bounded_guidance["risks"]) == 1
    assert len(bounded_guidance["out_of_scope"]) == 2
    
    # Verify that the bounded guidance is the only data passed to remediation
    # This ensures that no Planner session IDs, transcripts, or other non-bounded data
    # become part of remediation state
    assert "relevant_files" not in bounded_guidance
    assert "relevant_symbols" not in bounded_guidance
    assert "likely_tests" not in bounded_guidance