from __future__ import annotations

from pathlib import Path
import hashlib
from collections.abc import Callable

from .util import require_binary, run, safe_process_env, slugify


class GitManager:
    def __init__(self, repo: Path, main_branch: str, worktree_root: Path, timeout: int = 1200, env_provider: Callable[[], dict[str, str]] | None = None):
        require_binary("git")
        self.repo = repo.resolve()
        self.main_branch = main_branch
        self.worktree_root = worktree_root
        self.timeout = timeout
        self.env_provider = env_provider

    def _env(self) -> dict[str, str] | None:
        return self.env_provider() if self.env_provider else None

    def _run_auth(self, cmd: list[str], cwd: Path, timeout: int | None = None):
        auth = self._env()
        if auth is None:
            return run(cmd, cwd, timeout or self.timeout)
        return run(cmd, cwd, timeout or self.timeout, env=safe_process_env(auth), inherit_env=False)

    def ensure_repo(self) -> None:
        r = run(["git", "rev-parse", "--show-toplevel"], self.repo)
        if not r.ok:
            raise RuntimeError("Current path is not inside a Git repository.")

    def remote_url(self) -> str | None:
        r = run(["git", "remote", "get-url", "origin"], self.repo)
        return r.stdout.strip() if r.ok else None

    def prepare(self, task_id: str, title: str) -> tuple[str, Path]:
        self.ensure_repo()
        fetched = self._run_auth(["git", "fetch", "origin", self.main_branch], self.repo)
        if not fetched.ok:
            raise RuntimeError(f"Failed to fetch origin/{self.main_branch}:\n{fetched.stderr}")
        branch = f"ai/{task_id}-{slugify(title)}"
        project_key = f"{slugify(self.repo.name, 24)}-{hashlib.sha256(str(self.repo).encode()).hexdigest()[:8]}"
        worktree = (self.worktree_root / project_key / task_id).resolve()
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if worktree.exists():
            raise RuntimeError(f"Worktree already exists: {worktree}")
        base = f"origin/{self.main_branch}"
        r = run(["git", "worktree", "add", "-b", branch, str(worktree), base], self.repo, self.timeout)
        if not r.ok:
            raise RuntimeError(f"Failed to create worktree:\n{r.stderr}")
        return branch, worktree

    def _intent_to_add_untracked(self, worktree: Path) -> None:
        # Make new untracked files visible to pre-commit diff review and secret scanning
        # without staging their contents.
        run(["git", "add", "-N", "--", "."], worktree, self.timeout)

    def diff(self, worktree: Path) -> str:
        self._intent_to_add_untracked(worktree)
        r = run(["git", "diff", "--no-ext-diff", f"origin/{self.main_branch}"], worktree, self.timeout)
        return r.stdout

    def diff_non_ai(self, worktree: Path) -> str:
        self._intent_to_add_untracked(worktree)
        r = run(["git", "diff", "--no-ext-diff", f"origin/{self.main_branch}", "--", ".", ":(exclude).ai/**"], worktree, self.timeout)
        return r.stdout

    def status(self, worktree: Path) -> str:
        return run(["git", "status", "--short"], worktree).stdout

    def changed_files(self, worktree: Path) -> list[str]:
        r = run(["git", "diff", "--name-only", f"origin/{self.main_branch}"], worktree)
        return [x for x in r.stdout.splitlines() if x.strip()]

    def commit(self, worktree: Path, message: str) -> str:
        add = run(["git", "add", "-A"], worktree)
        if not add.ok:
            raise RuntimeError(add.stderr)
        if not self.status(worktree).strip():
            raise RuntimeError("Agent produced no repository changes.")
        c = run([
            "git",
            "-c", "user.name=AIpipe Bot",
            "-c", "user.email=aipipe@localhost",
            "commit", "-m", message,
        ], worktree, self.timeout)
        if not c.ok:
            raise RuntimeError(c.stderr)
        sha = run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
        return sha

    def push(self, worktree: Path, branch: str) -> None:
        r = self._run_auth(["git", "push", "-u", "origin", branch], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr)

    def cleanup(self, worktree: Path, branch: str) -> None:
        run(["git", "worktree", "remove", "--force", str(worktree)], self.repo, self.timeout)
        run(["git", "branch", "-D", branch], self.repo, self.timeout)
