from pathlib import Path

from aipipe.git_manager import GitManager
from aipipe.util import run


def git(cwd: Path, *args: str):
    r = run(["git", *args], cwd)
    assert r.ok, r.stderr
    return r


def test_worktree_isolation_and_diff(tmp_path: Path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    repo = tmp_path / "repo"
    git(tmp_path, "clone", str(remote), str(repo))
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", "initial")
    git(repo, "branch", "-M", "main")
    git(repo, "push", "-u", "origin", "main")

    gm = GitManager(repo, "main", tmp_path / "worktrees")
    branch, wt = gm.prepare("T-0001", "Change file")
    (wt / "a.txt").write_text("two\n", encoding="utf-8")
    (wt / "new.txt").write_text("brand new\n", encoding="utf-8")
    diff = gm.diff(wt)
    assert "two" in diff
    assert "new.txt" in diff
    assert "brand new" in diff
    assert (repo / "a.txt").read_text() == "one\n"
    gm.cleanup(wt, branch)
