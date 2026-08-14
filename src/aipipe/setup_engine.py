from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .util import CommandResult, run, safe_process_env, truncate


@dataclass
class SetupOutcome:
    results: list[tuple[str, CommandResult]]
    runtime_env: dict[str, str]


class SetupEngine:
    """Prepare dependencies deterministically before an agent starts.

    Auto setup is intentionally conservative. Projects can override it with
    `.ai/config.yml` setup.commands or disable setup.auto.
    """

    def __init__(self, commands: dict[str, str], auto: bool, timeout: int, runtime_root: Path):
        self.commands = commands
        self.auto = auto
        self.timeout = timeout
        self.runtime_root = runtime_root

    def execute(self, repo: Path) -> SetupOutcome:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        runtime_env: dict[str, str] = {}
        commands = dict(self.commands)

        if not commands and self.auto:
            commands, runtime_env = self._autodetect(repo)

        results: list[tuple[str, CommandResult]] = []
        env = safe_process_env(runtime_env)
        for name, command in commands.items():
            result = run(command, repo, self.timeout, shell=True, env=env, inherit_env=False)
            result.stdout = truncate(result.stdout, 9000)
            result.stderr = truncate(result.stderr, 9000)
            results.append((name, result))
            if not result.ok:
                break
        return SetupOutcome(results, runtime_env)

    def _autodetect(self, repo: Path) -> tuple[dict[str, str], dict[str, str]]:
        # Node dependencies are project-local and therefore safe from cross-project
        # dependency contamination within the worker.
        if (repo / "package.json").exists():
            if (repo / "package-lock.json").exists() or (repo / "npm-shrinkwrap.json").exists():
                return {"npm-ci": "npm ci --no-audit --no-fund"}, {}
            # Do not create a new lockfile during autonomous setup.
            return {"npm-install": "npm install --no-package-lock --no-audit --no-fund"}, {}

        # Python uses a per-task virtual environment outside the Git worktree so
        # dependency setup cannot pollute either Git status or another project.
        if (repo / "requirements.txt").exists() or (repo / "pyproject.toml").exists():
            venv = self.runtime_root / "venv"
            create = run(
                [sys.executable, "-m", "venv", str(venv)],
                repo,
                self.timeout,
                env=safe_process_env(),
                inherit_env=False,
            )
            if not create.ok:
                detail = truncate(create.stderr or create.stdout or "unknown error", 3000)
                raise RuntimeError(f"Failed to create isolated Python environment: {detail}")
            if os.name == "nt":
                bin_dir = venv / "Scripts"
                python = bin_dir / "python.exe"
            else:
                bin_dir = venv / "bin"
                python = bin_dir / "python"
            runtime_env = {
                "VIRTUAL_ENV": str(venv),
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            }
            if (repo / "requirements.txt").exists():
                command = f'"{python}" -m pip install -r requirements.txt'
            else:
                command = f'"{python}" -m pip install -e .'
            return {"python-dependencies": command}, runtime_env

        # Rust/Go/Maven/Gradle resolve dependencies as part of their normal build/test
        # commands. Toolchain installation itself remains a worker-image concern.
        return {}, {}
