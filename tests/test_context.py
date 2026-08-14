from pathlib import Path

from aipipe.context import ContextBuilder
from aipipe.models import ContextClass, Risk, Route, TaskContract, TaskType


def test_context_retrieves_only_relevant_active_entries(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "AGENT.md").write_text("minimal", encoding="utf-8")
    (global_root / "SECURITY.md").write_text("secure", encoding="utf-8")
    (global_root / "LEARNINGS.md").write_text("", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai" / "PROJECT.md").write_text("project", encoding="utf-8")
    (repo / ".ai" / "DECISIONS.md").write_text(
        "## D-1\nTags: auth\nStatus: active\nKeep auth server-side.\n\n"
        "## D-2\nTags: ui\nStatus: active\nUse grid.\n\n"
        "## D-3\nTags: auth\nStatus: obsolete\nOld auth.\n",
        encoding="utf-8",
    )
    (repo / ".ai" / "LEARNINGS.md").write_text("", encoding="utf-8")
    route = Route(TaskType.FEATURE, Risk.HIGH, ContextClass.NORMAL, ["auth"], [])
    task = TaskContract("T-1", "auth thing", acceptance_criteria=["works"], route=route)
    text = ContextBuilder(global_root).build(repo, task, "IMPLEMENTER")
    assert "Keep auth server-side" in text
    assert "Use grid" not in text
    assert "Old auth" not in text
    assert "# Security Rules" in text
