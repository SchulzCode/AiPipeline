from __future__ import annotations

import json
from pathlib import Path

from .util import CommandResult, run, safe_process_env, truncate


def autodetect_quality(repo: Path) -> dict[str, str]:
    commands: dict[str, str] = {}
    package = repo / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        except Exception:
            scripts = {}
        for name in ["test", "lint", "typecheck", "build"]:
            if name in scripts:
                commands[name] = f"npm run {name}"
    elif (repo / "pyproject.toml").exists() or (repo / "pytest.ini").exists():
        commands = {"test": "python -m pytest"}
    elif (repo / "Cargo.toml").exists():
        commands = {"test": "cargo test", "build": "cargo build"}
    elif (repo / "go.mod").exists():
        commands = {"test": "go test ./...", "build": "go build ./..."}
    elif (repo / "pom.xml").exists():
        commands = {"test": "mvn test", "build": "mvn package -DskipTests"}
    elif (repo / "gradlew").exists():
        commands = {"test": "./gradlew test", "build": "./gradlew build -x test"}
    return commands



class QualityEngine:
    def __init__(self, commands: dict[str, str], timeout: int, runtime_env: dict[str, str] | None = None):
        self.commands = commands
        self.timeout = timeout
        self.runtime_env = runtime_env or {}

    def execute(self, repo: Path) -> list[tuple[str, CommandResult]]:
        commands = self.commands or autodetect_quality(repo)
        results = []
        for name, command in commands.items():
            result = run(command, repo, self.timeout, shell=True, env=safe_process_env(self.runtime_env), inherit_env=False)
            result.stdout = truncate(result.stdout)
            result.stderr = truncate(result.stderr)
            results.append((name, result))
            if not result.ok:
                break
        return results
