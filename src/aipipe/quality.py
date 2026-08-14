from __future__ import annotations

import json
from pathlib import Path

from .util import CommandResult, run, safe_process_env, truncate


QUALITY_SCRIPT_ORDER = ("test", "lint", "typecheck", "build")

IGNORED_PACKAGE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "vendor",
}


def _read_package_scripts(package_json: Path) -> dict[str, str]:
    """Read a package.json scripts object conservatively."""

    try:
        data = json.loads(
            package_json.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}

    scripts = data.get("scripts", {})

    if not isinstance(scripts, dict):
        return {}

    return {
        name: command
        for name, command in scripts.items()
        if isinstance(name, str)
        and isinstance(command, str)
    }


def _discover_package_jsons(
    repo: Path,
    max_depth: int = 3,
) -> list[Path]:
    """Find root and shallow nested Node projects deterministically.

    This covers common layouts such as:
    - package.json
    - web/package.json
    - frontend/package.json
    - apps/web/package.json
    - packages/ui/package.json

    Generated and dependency directories are skipped.
    """

    found: list[Path] = []

    root_package = repo / "package.json"

    if root_package.is_file():
        found.append(root_package)

    def walk(
        directory: Path,
        depth: int,
    ) -> None:
        if depth >= max_depth:
            return

        try:
            children = sorted(
                directory.iterdir(),
                key=lambda path: path.name.lower(),
            )
        except OSError:
            return

        for child in children:
            if child.name in IGNORED_PACKAGE_DIRS:
                continue

            if (
                child.is_symlink()
                or not child.is_dir()
            ):
                continue

            package_json = (
                child / "package.json"
            )

            if package_json.is_file():
                found.append(
                    package_json
                )

            walk(
                child,
                depth + 1,
            )

    walk(
        repo,
        0,
    )

    unique: list[Path] = []
    seen: set[Path] = set()

    for path in found:
        resolved = path.resolve()

        if resolved in seen:
            continue

        seen.add(resolved)
        unique.append(path)

    return unique


def _quote_path(
    path: Path,
) -> str:
    """Quote a relative path used in shell=True commands."""

    return (
        '"'
        + str(path).replace('"', '\\"')
        + '"'
    )


def _unique_name(
    commands: dict[str, str],
    preferred: str,
    prefix: str,
) -> str:
    if preferred not in commands:
        return preferred

    candidate = (
        f"{prefix}:{preferred}"
    )

    if candidate not in commands:
        return candidate

    index = 2

    while (
        f"{candidate}:{index}"
        in commands
    ):
        index += 1

    return (
        f"{candidate}:{index}"
    )


def _add_python_quality(
    repo: Path,
    commands: dict[str, str],
) -> None:
    has_python_project = (
        (repo / "pyproject.toml").exists()
        or (repo / "pytest.ini").exists()
        or (repo / "setup.cfg").exists()
        or (repo / "setup.py").exists()
    )

    if not has_python_project:
        return

    test_name = _unique_name(
        commands,
        "test",
        "python",
    )

    commands[test_name] = (
        "python -m pytest"
    )

    # Match the common CI syntax check when the project
    # uses a src/ layout.
    if (repo / "src").is_dir():
        compile_name = _unique_name(
            commands,
            "compile",
            "python",
        )

        commands[compile_name] = (
            "python -m compileall -q src"
        )


def _add_nested_node_quality(
    repo: Path,
    commands: dict[str, str],
) -> None:
    for package_json in (
        _discover_package_jsons(repo)
    ):
        package_dir = (
            package_json.parent
        )

        # Root Node scripts are handled separately so
        # existing behavior and command names stay stable.
        if package_dir == repo:
            continue

        scripts = _read_package_scripts(
            package_json
        )

        relevant_scripts = [
            name
            for name in QUALITY_SCRIPT_ORDER
            if name in scripts
        ]

        if not relevant_scripts:
            continue

        relative_dir = (
            package_dir.relative_to(repo)
        )

        path_label = (
            relative_dir.as_posix()
        )

        prefix = path_label.replace(
            "/",
            ":",
        )

        quoted_dir = _quote_path(
            relative_dir
        )

        # SetupEngine currently prepares the root ecosystem.
        # In mixed repositories such as Python + web/, a
        # nested Node project may not yet have node_modules.
        #
        # Install deterministically only when needed. The
        # command disappears on later verification passes
        # once node_modules exists.
        if not (
            package_dir / "node_modules"
        ).exists():
            dependency_name = (
                f"{prefix}:dependencies"
            )

            if (
                (
                    package_dir
                    / "package-lock.json"
                ).exists()
                or (
                    package_dir
                    / "npm-shrinkwrap.json"
                ).exists()
            ):
                commands[
                    dependency_name
                ] = (
                    f"npm --prefix {quoted_dir} "
                    "ci --no-audit --no-fund"
                )
            else:
                commands[
                    dependency_name
                ] = (
                    f"npm --prefix {quoted_dir} "
                    "install --no-package-lock "
                    "--no-audit --no-fund"
                )

        for name in relevant_scripts:
            commands[
                f"{prefix}:{name}"
            ] = (
                f"npm --prefix "
                f"{quoted_dir} run {name}"
            )


def autodetect_quality(
    repo: Path,
) -> dict[str, str]:
    """Autodetect quality gates for normal and monorepo layouts.

    Detection is additive instead of mutually exclusive:
    a repository can run Python checks and nested Node
    checks during the same verification pass.
    """

    commands: dict[str, str] = {}

    # Preserve the previous root Node behavior exactly:
    # existing scripts keep names such as "test" and "lint".
    root_package = (
        repo / "package.json"
    )

    if root_package.exists():
        scripts = _read_package_scripts(
            root_package
        )

        for name in QUALITY_SCRIPT_ORDER:
            if name in scripts:
                commands[name] = (
                    f"npm run {name}"
                )

    # Add Python independently instead of using elif.
    _add_python_quality(
        repo,
        commands,
    )

    # Add nested Node projects such as web/.
    _add_nested_node_quality(
        repo,
        commands,
    )

    # Other root ecosystems remain conservative. They are
    # selected only if no Python/Node quality gates were
    # detected.
    if not commands:
        if (
            repo / "Cargo.toml"
        ).exists():
            commands = {
                "test": "cargo test",
                "build": "cargo build",
            }

        elif (
            repo / "go.mod"
        ).exists():
            commands = {
                "test": "go test ./...",
                "build": "go build ./...",
            }

        elif (
            repo / "pom.xml"
        ).exists():
            commands = {
                "test": "mvn test",
                "build": (
                    "mvn package -DskipTests"
                ),
            }

        elif (
            repo / "gradlew"
        ).exists():
            commands = {
                "test": "./gradlew test",
                "build": (
                    "./gradlew build -x test"
                ),
            }

    return commands


class QualityEngine:
    def __init__(
        self,
        commands: dict[str, str],
        timeout: int,
        runtime_env: dict[str, str]
        | None = None,
    ):
        self.commands = commands
        self.timeout = timeout
        self.runtime_env = (
            runtime_env or {}
        )

    def execute(
        self,
        repo: Path,
    ) -> list[
        tuple[str, CommandResult]
    ]:
        commands = (
            self.commands
            or autodetect_quality(repo)
        )

        results: list[
            tuple[str, CommandResult]
        ] = []

        env = safe_process_env(
            self.runtime_env
        )

        for name, command in (
            commands.items()
        ):
            result = run(
                command,
                repo,
                self.timeout,
                shell=True,
                env=env,
                inherit_env=False,
            )

            result.stdout = truncate(
                result.stdout
            )

            result.stderr = truncate(
                result.stderr
            )

            results.append(
                (name, result)
            )

            # Fail fast so a broken prerequisite does not
            # produce noisy or misleading downstream errors.
            if not result.ok:
                break

        return results