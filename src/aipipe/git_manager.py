from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

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

    def _fetch_main(self) -> None:
        fetched = self._run_auth(["git", "fetch", "origin", self.main_branch], self.repo)
        if not fetched.ok:
            detail = (fetched.stderr or fetched.stdout or "unknown error").strip()
            raise RuntimeError(f"Failed to fetch origin/{self.main_branch}: {detail}")
        verified = run(["git", "rev-parse", "--verify", f"origin/{self.main_branch}"], self.repo)
        if not verified.ok:
            raise RuntimeError(f"Fetched remote does not contain origin/{self.main_branch}.")

    def preflight(self) -> None:
        self.ensure_repo()
        if not self.remote_url():
            raise RuntimeError("Repository has no origin remote.")
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        probe = self.worktree_root / ".aipipe-write-probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise RuntimeError(f"Worktree root is not writable: {self.worktree_root}: {exc}") from exc
        self._fetch_main()

    def _worktree_records(self) -> list[dict[str, str]]:
        result = run(["git", "worktree", "list", "--porcelain"], self.repo, self.timeout)
        if not result.ok:
            raise RuntimeError(result.stderr or "Failed to list Git worktrees.")
        records: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        if current:
            records.append(current)
        return records

    def _branch_ref(self, branch: str) -> str:
        return f"refs/heads/{branch}"

    def branch_exists(self, branch: str) -> bool:
        result = run(["git", "show-ref", "--verify", "--quiet", self._branch_ref(branch)], self.repo)
        return result.ok

    def branch_attached(self, branch: str) -> bool:
        ref = self._branch_ref(branch)
        return any(record.get("branch") == ref for record in self._worktree_records())

    def worktree_registered(self, worktree: Path) -> bool:
        target = str(worktree.resolve())
        return any(Path(record.get("worktree", "")).resolve() == Path(target) for record in self._worktree_records() if record.get("worktree"))

    def assert_worktree(self, worktree: Path, branch: str) -> None:
        target = worktree.resolve()
        ref = self._branch_ref(branch)
        for record in self._worktree_records():
            if record.get("worktree") and Path(record["worktree"]).resolve() == target:
                if record.get("branch") != ref:
                    raise RuntimeError(
                        f"Worktree {target} is attached to {record.get('branch')!r}, expected {ref!r}."
                    )
                if not target.exists():
                    raise RuntimeError(f"Registered worktree is missing on disk: {target}")
                return
        raise RuntimeError(f"Task worktree is not registered: {target}")

    def prepare(self, task_id: str, title: str) -> tuple[str, Path]:
        self.preflight()
        branch = f"ai/{task_id}-{slugify(title)}"
        project_key = f"{slugify(self.repo.name, 24)}-{hashlib.sha256(str(self.repo).encode()).hexdigest()[:8]}"
        worktree = (self.worktree_root / project_key / task_id).resolve()
        worktree.parent.mkdir(parents=True, exist_ok=True)

        if worktree.exists() or self.worktree_registered(worktree):
            raise RuntimeError(
                f"Task worktree already exists: {worktree}. Refusing to overwrite preserved task state."
            )
        if self.branch_exists(branch):
            raise RuntimeError(
                f"Task branch already exists: {branch}. Refusing to reuse it without checkpoint reconciliation."
            )

        base = f"origin/{self.main_branch}"
        r = run(["git", "worktree", "add", "-b", branch, str(worktree), base], self.repo, self.timeout)
        if not r.ok:
            raise RuntimeError(f"Failed to create worktree:\n{r.stderr}")
        self.assert_worktree(worktree, branch)
        return branch, worktree

    def _intent_to_add_untracked(self, worktree: Path) -> None:
        # Make new untracked files visible to pre-commit diff review and secret scanning
        # without staging their contents.
        run(["git", "add", "-N", "--", "."], worktree, self.timeout)

    def diff(self, worktree: Path) -> str:
        self._intent_to_add_untracked(worktree)
        r = run(["git", "diff", "--no-ext-diff", f"origin/{self.main_branch}"], worktree, self.timeout)
        if not r.ok:
            raise RuntimeError(r.stderr or "Failed to compute repository diff.")
        return r.stdout

    def diff_non_ai(self, worktree: Path) -> str:
        self._intent_to_add_untracked(worktree)
        r = run(["git", "diff", "--no-ext-diff", f"origin/{self.main_branch}", "--", ".", ":(exclude).ai/**"], worktree, self.timeout)
        if not r.ok:
            raise RuntimeError(r.stderr or "Failed to compute repository diff.")
        return r.stdout

    def status(self, worktree: Path) -> str:
        result = run(["git", "status", "--short"], worktree)
        if not result.ok:
            raise RuntimeError(result.stderr or "Failed to read Git status.")
        return result.stdout

    def changed_files(self, worktree: Path) -> list[str]:
        r = run(["git", "diff", "--name-only", f"origin/{self.main_branch}"], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr or "Failed to list changed files.")
        return [x for x in r.stdout.splitlines() if x.strip()]

    def head(self, worktree: Path) -> str:
        r = run(["git", "rev-parse", "HEAD"], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr or "Failed to resolve HEAD.")
        return r.stdout.strip()

    def remote_branch_sha(self, branch: str) -> str | None:
        result = self._run_auth(["git", "ls-remote", "--heads", "origin", branch], self.repo)
        if not result.ok:
            raise RuntimeError(result.stderr or f"Failed to read remote branch {branch}.")
        line = next((line for line in result.stdout.splitlines() if line.strip()), "")
        return line.split()[0] if line else None

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
        return self.head(worktree)

    def push(self, worktree: Path, branch: str) -> None:
        self.assert_worktree(worktree, branch)
        r = self._run_auth(["git", "push", "-u", "origin", branch], worktree)
        if not r.ok:
            raise RuntimeError(r.stderr)
        remote_sha = self.remote_branch_sha(branch)
        local_sha = self.head(worktree)
        if remote_sha != local_sha:
            raise RuntimeError(
                f"Remote branch {branch} points to {remote_sha or 'nothing'}, expected {local_sha}."
            )

    def cleanup(self, worktree: Path, branch: str) -> None:
        registered = self.worktree_registered(worktree)
        if registered:
            removed = run(["git", "worktree", "remove", "--force", str(worktree)], self.repo, self.timeout)
            if not removed.ok:
                raise RuntimeError(
                    f"Failed to remove task worktree safely: {removed.stderr or removed.stdout}"
                )
        elif worktree.exists():
            # Never recursively delete an unregistered directory: it may contain
            # preserved work that Git no longer knows about.
            raise RuntimeError(
                f"Task worktree directory exists but is not registered; refusing destructive cleanup: {worktree}"
            )

        if self.branch_attached(branch):
            raise RuntimeError(
                f"Refusing to delete branch {branch}; it is still attached to a worktree."
            )

        if self.branch_exists(branch):
            deleted = run(["git", "branch", "-D", branch], self.repo, self.timeout)
            if not deleted.ok:
                raise RuntimeError(
                    f"Failed to remove local task branch {branch}: {deleted.stderr or deleted.stdout}"
                )
