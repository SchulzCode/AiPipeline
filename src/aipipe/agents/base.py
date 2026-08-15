from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from ..util import CommandResult, truncate


@dataclass
class AgentResult:
    ok: bool
    output: str
    returncode: int
    input_tokens: int = 0
    output_tokens: int = 0


def collect_env(keys: tuple[str, ...]) -> dict[str, str]:
    """Forward only the named, currently-set environment variables.

    Used to pass provider auth (API keys, tokens) through to a CLI subprocess
    without inheriting the rest of the control-plane process environment.
    """
    return {key: value for key in keys if (value := os.environ.get(key))}


def finalize_result(
    result: CommandResult,
    output: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> AgentResult:
    """Build the AgentResult an adapter returns from a finished CLI subprocess.

    Appends stderr (if any) to the parsed stdout output, then truncates the
    combined text so downstream prompts/events stay bounded regardless of how
    verbose a given provider's CLI is.
    """
    if result.stderr:
        output += "\nSTDERR:\n" + truncate(result.stderr, 6000)
    return AgentResult(result.ok, truncate(output, 24000), result.returncode, input_tokens, output_tokens)


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
