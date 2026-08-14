from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class AgentResult:
    ok: bool
    output: str
    returncode: int
    input_tokens: int = 0
    output_tokens: int = 0


class AgentAdapter(Protocol):
    name: str
    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult: ...
