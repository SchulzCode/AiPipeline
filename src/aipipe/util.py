from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: list[str] | str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


SAFE_ENV_KEYS = {
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM",
    "TMP", "TEMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    "HOME", "USER", "LOGNAME", "USERPROFILE",
    "VIRTUAL_ENV", "PYTHONPATH", "JAVA_HOME", "GRADLE_USER_HOME",
    "GOPATH", "GOROOT", "CARGO_HOME", "RUSTUP_HOME", "PNPM_HOME",
    "NPM_CONFIG_CACHE", "YARN_CACHE_FOLDER", "CI",
}


def safe_process_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return an allowlisted environment for untrusted repository/agent subprocesses.

    Control-plane credentials (database URLs, GitHub App private keys, webhook
    secrets, session secrets, etc.) are intentionally not inherited.
    """
    result = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    if extra:
        result.update({str(k): str(v) for k, v in extra.items() if v is not None})
    return result


def run(cmd: list[str] | str, cwd: Path | None = None, timeout: int = 1200,
        env: dict[str, str] | None = None, shell: bool = False,
        inherit_env: bool = True) -> CommandResult:
    process_env = ({**os.environ, **(env or {})} if inherit_env else dict(env or {}))
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=process_env,
        shell=shell,
    )
    return CommandResult(cmd, proc.returncode, proc.stdout, proc.stderr)


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")


def slugify(text: str, limit: int = 48) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return (value or "task")[:limit].rstrip("-")


def truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...<truncated>...\n" + text[-half:]


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def execute_commands(
    commands: dict[str, str],
    cwd: Path,
    timeout: int,
    runtime_env: dict[str, str] | None = None,
    output_limit: int = 12000,
) -> list[tuple[str, CommandResult]]:
    """Run named shell commands in order, truncating output and stopping at the first failure.

    Shared by SetupEngine, QualityEngine and SecurityEngine so a broken
    prerequisite command produces one clear failure instead of a cascade of
    noisy or misleading downstream errors.
    """
    env = safe_process_env(runtime_env)
    results: list[tuple[str, CommandResult]] = []
    for name, command in commands.items():
        result = run(command, cwd, timeout, shell=True, env=env, inherit_env=False)
        result.stdout = truncate(result.stdout, output_limit)
        result.stderr = truncate(result.stderr, output_limit)
        results.append((name, result))
        if not result.ok:
            break
    return results
