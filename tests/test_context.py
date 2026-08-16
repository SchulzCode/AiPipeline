from pathlib import Path

from aipipe.context import ContextBuilder
from aipipe.models import ContextClass, Risk, Route, TaskContract, TaskType
from aipipe.repo_index import RepoIndexCache
from aipipe.util import run


def git(cwd: Path, *args: str):
    r = run(["git", *args], cwd)
    assert r.ok, r.stderr
    return r


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


def test_plan_is_included_when_provided_and_omitted_when_not(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    route = Route(TaskType.FEATURE, Risk.LOW, ContextClass.DEEP, ["general"], [])
    task = TaskContract("T-2", "rework the pipeline", acceptance_criteria=["works"], route=route)
    builder = ContextBuilder(global_root)

    with_plan = builder.build(repo, task, "IMPLEMENTER", plan="Goal\nDo the thing.\n")
    assert "# Implementation Plan" in with_plan
    assert "Do the thing." in with_plan

    without_plan = builder.build(repo, task, "IMPLEMENTER")
    assert "# Implementation Plan" not in without_plan


def test_repository_index_included_when_cache_available(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / "app.py").write_text("def handler():\n    pass\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")

    route = Route(TaskType.FEATURE, Risk.LOW, ContextClass.NORMAL, ["general"], [])
    task = TaskContract("T-3", "add a thing", acceptance_criteria=["works"], route=route)
    cache = RepoIndexCache(tmp_path / "index-cache")
    builder = ContextBuilder(global_root, cache)

    text = builder.build(repo, task, "IMPLEMENTER")
    assert "# Repository Index" in text
    assert "pyproject.toml" in text


def test_repository_index_omitted_without_cache(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    route = Route(TaskType.FEATURE, Risk.LOW, ContextClass.NORMAL, ["general"], [])
    task = TaskContract("T-4", "add a thing", acceptance_criteria=["works"], route=route)

    text = ContextBuilder(global_root).build(repo, task, "IMPLEMENTER")
    assert "# Repository Index" not in text


def test_repository_index_degrades_safely_when_repo_is_not_a_git_repository(tmp_path: Path):
    global_root = tmp_path / "global"
    global_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    route = Route(TaskType.FEATURE, Risk.LOW, ContextClass.NORMAL, ["general"], [])
    task = TaskContract("T-5", "add a thing", acceptance_criteria=["works"], route=route)
    cache = RepoIndexCache(tmp_path / "index-cache")
    builder = ContextBuilder(global_root, cache)

    text = builder.build(repo, task, "IMPLEMENTER")
    assert "# Repository Index" not in text
    assert "# Task" in text
