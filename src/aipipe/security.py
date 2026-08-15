from __future__ import annotations

import re
from pathlib import Path

from .util import CommandResult, execute_commands


SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("generic-secret", re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
]


def scan_added_diff(diff: str) -> list[str]:
    findings: list[str] = []
    current = "unknown"
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(f"{name} pattern in added line of {current}")
    return findings


class SecurityEngine:
    def __init__(self, commands: dict[str, str], timeout: int, runtime_env: dict[str, str] | None = None):
        self.commands = commands
        self.timeout = timeout
        self.runtime_env = runtime_env or {}

    def execute_commands(self, repo: Path) -> list[tuple[str, CommandResult]]:
        return execute_commands(self.commands, repo, self.timeout, self.runtime_env)
