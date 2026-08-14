from __future__ import annotations

import os
import sys
import tomllib
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

    Python projects are installed into an isolated per-task virtual
    environment. Common development/test dependency definitions are detected
    so verification tools such as pytest are available without requiring the
    coding agent to repair the environment.
    """

    PYPROJECT_TEST_EXTRAS = (
        "dev",
        "test",
        "tests",
        "testing",
    )

    REQUIREMENTS_TEST_FILES = (
        "requirements-dev.txt",
        "requirements-test.txt",
        "test-requirements.txt",
    )

    def __init__(
        self,
        commands: dict[str, str],
        auto: bool,
        timeout: int,
        runtime_root: Path,
    ):
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
            result = run(
                command,
                repo,
                self.timeout,
                shell=True,
                env=env,
                inherit_env=False,
            )

            result.stdout = truncate(result.stdout, 9000)
            result.stderr = truncate(result.stderr, 9000)

            results.append((name, result))

            if not result.ok:
                break

        return SetupOutcome(results, runtime_env)

    def _autodetect(
        self,
        repo: Path,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Detect deterministic dependency setup for common project types."""

        # -------------------------------------------------------------
        # Node
        # -------------------------------------------------------------
        #
        # Node dependencies are project-local and therefore isolated by
        # the task worktree.
        #
        # Prefer npm ci when a lockfile exists. Without a lockfile, avoid
        # creating one during autonomous setup.
        package_json = repo / "package.json"

        if package_json.exists():
            if (
                (repo / "package-lock.json").exists()
                or (repo / "npm-shrinkwrap.json").exists()
            ):
                return {
                    "npm-ci": "npm ci --no-audit --no-fund",
                }, {}

            return {
                "npm-install": (
                    "npm install --no-package-lock --no-audit --no-fund"
                ),
            }, {}

        # -------------------------------------------------------------
        # Python
        # -------------------------------------------------------------
        #
        # Each task gets its own virtual environment outside the Git
        # worktree. This prevents dependencies from:
        #
        # - polluting Git status
        # - leaking between projects
        # - leaking between tasks
        #
        requirements = repo / "requirements.txt"
        pyproject = repo / "pyproject.toml"

        if requirements.exists() or pyproject.exists():
            return self._prepare_python(repo)

        # -------------------------------------------------------------
        # Other ecosystems
        # -------------------------------------------------------------
        #
        # Rust, Go, Maven and Gradle generally resolve dependencies as
        # part of their normal build/test commands.
        #
        # Installing toolchains remains the responsibility of the worker
        # image rather than autonomous project setup.
        return {}, {}

    def _prepare_python(
        self,
        repo: Path,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Create an isolated Python environment and determine install commands."""

        venv = self.runtime_root / "venv"

        create = run(
            [sys.executable, "-m", "venv", str(venv)],
            repo,
            self.timeout,
            env=safe_process_env(),
            inherit_env=False,
        )

        if not create.ok:
            detail = truncate(
                create.stderr
                or create.stdout
                or "unknown error",
                3000,
            )

            raise RuntimeError(
                f"Failed to create isolated Python environment: {detail}"
            )

        if os.name == "nt":
            bin_dir = venv / "Scripts"
            python = bin_dir / "python.exe"
        else:
            bin_dir = venv / "bin"
            python = bin_dir / "python"

        runtime_env = {
            "VIRTUAL_ENV": str(venv),
            "PATH": (
                str(bin_dir)
                + os.pathsep
                + os.environ.get("PATH", "")
            ),
        }

        commands: dict[str, str] = {}

        requirements = repo / "requirements.txt"
        pyproject = repo / "pyproject.toml"

        # -------------------------------------------------------------
        # requirements.txt projects
        # -------------------------------------------------------------

        if requirements.exists():
            commands["python-dependencies"] = (
                f'"{python}" -m pip install -r requirements.txt'
            )

            test_requirements = self._find_test_requirements(repo)

            if test_requirements is not None:
                commands["python-test-dependencies"] = (
                    f'"{python}" -m pip install '
                    f'-r "{test_requirements.name}"'
                )

            return commands, runtime_env

        # -------------------------------------------------------------
        # pyproject.toml projects
        # -------------------------------------------------------------

        if pyproject.exists():
            extra = self._find_pyproject_test_extra(pyproject)

            if extra is not None:
                commands["python-dependencies"] = (
                    f'"{python}" -m pip install -e ".[{extra}]"'
                )
            else:
                commands["python-dependencies"] = (
                    f'"{python}" -m pip install -e .'
                )

            return commands, runtime_env

        return {}, runtime_env

    def _find_test_requirements(
        self,
        repo: Path,
    ) -> Path | None:
        """Return a conventional development/test requirements file if present."""

        for filename in self.REQUIREMENTS_TEST_FILES:
            path = repo / filename

            if path.exists():
                return path

        return None

    def _find_pyproject_test_extra(
        self,
        pyproject: Path,
    ) -> str | None:
        """Detect a conventional test/development optional dependency group.

        This is intentionally deterministic. No LLM is used to decide which
        dependency group should be installed.
        """

        try:
            with pyproject.open("rb") as handle:
                config = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return None

        project = config.get("project")

        if not isinstance(project, dict):
            return None

        optional_dependencies = project.get("optional-dependencies")

        if not isinstance(optional_dependencies, dict):
            return None

        for extra in self.PYPROJECT_TEST_EXTRAS:
            dependencies = optional_dependencies.get(extra)

            if isinstance(dependencies, list):
                return extra

        return None