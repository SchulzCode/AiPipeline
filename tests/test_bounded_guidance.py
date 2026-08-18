"""Tests for bounded Planner guidance derivation from TaskMap.

This ensures that remediation only uses bounded, deterministic guidance
derived from TaskMap, not raw Planner transcripts.
"""

from unittest.mock import Mock

from aipipe.task_map import TaskMap
from aipipe.orchestrator import Orchestrator


def test_bounded_guidance_derivation_from_task_map():
    """Test that bounded guidance is correctly derived from a TaskMap."""
    # Create a TaskMap with constraints, risks, and out_of_scope fields
    task_map = TaskMap(
        relevant_files=("src/aipipe/orchestrator.py",),
        relevant_symbols=("Orchestrator.run",),
        likely_tests=("tests/test_orchestrator_hardening.py",),
        constraints=("Planner stays read-only", "No external API calls"),
        risks=("Must not block DEEP tasks without a map", "Potential performance issues"),
        out_of_scope=("#50 constraint persistence", "Security audit"),
    )
    
    # Directly test the method without creating an orchestrator instance
    # Create an instance just for testing the method
    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)
    
    # Verify that only the relevant fields are extracted
    assert "constraints" in bounded_guidance
    assert "risks" in bounded_guidance
    assert "out_of_scope" in bounded_guidance
    
    assert bounded_guidance["constraints"] == ["Planner stays read-only", "No external API calls"]
    assert bounded_guidance["risks"] == ["Must not block DEEP tasks without a map", "Potential performance issues"]
    assert bounded_guidance["out_of_scope"] == ["#50 constraint persistence", "Security audit"]


def test_bounded_guidance_with_empty_task_map():
    """Test that bounded guidance handles empty TaskMaps properly."""
    task_map = TaskMap()
    
    # Directly test the method without creating an orchestrator instance
    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)
    
    # Verify that empty guidance is returned
    assert bounded_guidance == {}


def test_bounded_guidance_with_partial_task_map():
    """Test that bounded guidance handles TaskMaps with partial fields."""
    task_map = TaskMap(
        relevant_files=("src/aipipe/orchestrator.py",),
        constraints=("Planner stays read-only",),
        risks=(),
        out_of_scope=("#50 constraint persistence",),
    )
    
    # Directly test the method without creating an orchestrator instance
    orchestrator = Orchestrator.__new__(Orchestrator)
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)
    
    # Verify that only the non-empty fields are included
    assert "constraints" in bounded_guidance
    assert "out_of_scope" in bounded_guidance
    assert "risks" not in bounded_guidance  # Empty field should not be included
    
    assert bounded_guidance["constraints"] == ["Planner stays read-only"]
    assert bounded_guidance["out_of_scope"] == ["#50 constraint persistence"]


def test_no_planner_result_degrades_safely():
    """Test that missing Planner results are handled gracefully."""
    # Directly test the method without creating an orchestrator instance
    orchestrator = Orchestrator.__new__(Orchestrator)
    
    # Test that None task_map produces empty bounded guidance
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(None)
    assert bounded_guidance == {}


def test_bounded_guidance_handles_none_fields():
    """Test that bounded guidance handles TaskMaps with None fields properly."""
    # Create a TaskMap with None values for some fields
    task_map = TaskMap(
        relevant_files=("src/aipipe/orchestrator.py",),
        relevant_symbols=("Orchestrator.run",),
        likely_tests=("tests/test_orchestrator_hardening.py",),
        constraints=None,
        risks=None,
        out_of_scope=None,
    )
    
    # Directly test the method without creating an orchestrator instance
    orchestrator = Orchestrator.__new__(Orchestrator)
    
    # Test with None fields
    bounded_guidance = orchestrator._derive_bounded_guidance_from_task_map(task_map)
    
    # Verify that no guidance is extracted (as all fields are empty)
    assert bounded_guidance == {}