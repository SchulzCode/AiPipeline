import json
from pathlib import Path

from aipipe.agents.codex import CodexAdapter
from aipipe.agents.claude import ClaudeAdapter


def test_agent_classes_expose_names():
    assert CodexAdapter.name == "codex"
    assert ClaudeAdapter.name == "claude"
