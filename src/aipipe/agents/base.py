from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol


@dataclass
class AgentResult:
    ok: bool
    output: str
    returncode: int
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelOption:
    """A model an agent adapter accepts via its ``model`` config key.

    ``id`` is the literal value forwarded to the adapter's CLI invocation.
    ``id=None`` represents "Default/Automatic": no ``--model`` flag is passed
    and the underlying tool picks its own default, which is the pre-existing
    (backward-compatible) behavior for projects with no configured model.
    """

    id: str | None
    label: str


class AgentAdapter(Protocol):
    name: str
    MODELS: ClassVar[list[ModelOption]]
    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult: ...
