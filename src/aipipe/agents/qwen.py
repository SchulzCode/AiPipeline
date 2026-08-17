from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentResult, ModelOption, READ_ONLY_ROLES, finalize_result
from ..util import CommandResult, require_binary, run, safe_process_env


_AIPIPE_SYSTEM_PROMPT = """You are running inside AIpipe's managed task workspace.
AIpipe owns Git history and remote lifecycle operations. Do not commit, push, merge,
rebase, create pull requests, change branches, or modify remotes. Work only inside
the supplied workspace. Implementation and repair roles may edit source files and
run relevant local verification. Read-only roles must not modify the workspace.
"""


def _usage_tokens(usage: Any) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    input_tokens = usage.get("input_tokens", usage.get("inputTokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("outputTokens", 0))
    try:
        input_count = int(input_tokens or 0)
    except (TypeError, ValueError):
        input_count = 0
    try:
        output_count = int(output_tokens or 0)
    except (TypeError, ValueError):
        output_count = 0
    return input_count, output_count


def _parse_headless_output(stdout: str) -> tuple[str, int, int]:
    """Parse Qwen Code's ``--output-format json`` payload.

    Current Qwen Code emits a JSON array whose final ``type=result`` event
    contains the terminal result and aggregate usage. A small dict fallback is
    retained so adapter failure output remains useful if the CLI shape changes.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, 0, 0

    if isinstance(payload, list):
        result_event = next(
            (event for event in reversed(payload) if isinstance(event, dict) and event.get("type") == "result"),
            None,
        )
        if result_event is not None:
            input_tokens, output_tokens = _usage_tokens(result_event.get("usage"))
            return str(result_event.get("result", "")), input_tokens, output_tokens

    if isinstance(payload, dict):
        input_tokens, output_tokens = _usage_tokens(payload.get("usage"))
        final = payload.get("result", payload.get("response", ""))
        return str(final), input_tokens, output_tokens

    return stdout, 0, 0


class QwenAdapter:
    name = "qwen"

    # Local/provider model ids are deployment-specific. Registration and
    # project-facing model configuration are added separately from this adapter.
    MODELS = [ModelOption(id=None, label="Default (automatic)")]

    def __init__(self, config: dict, timeout: int = 3600, runtime_env: dict[str, str] | None = None):
        self.config = config
        self.timeout = timeout
        self.runtime_env = runtime_env or {}
        require_binary(config.get("binary", "qwen"))

    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        binary = self.config.get("binary", "qwen")
        approval_mode = "plan" if role in READ_ONLY_ROLES else "yolo"
        cmd = [
            binary,
            "-p",
            prompt,
            "--approval-mode",
            approval_mode,
            "--output-format",
            "json",
            "--append-system-prompt",
            _AIPIPE_SYSTEM_PROMPT,
        ]

        auth_type = self.config.get("auth_type")
        if auth_type:
            cmd += ["--auth-type", str(auth_type)]
        model = self.config.get("model")
        if model:
            cmd += ["--model", str(model)]

        result = run(
            cmd,
            workspace,
            self.timeout,
            env=safe_process_env(self.runtime_env),
            inherit_env=False,
        )
        final, input_tokens, output_tokens = _parse_headless_output(result.stdout)
        return finalize_result(result, final or result.stdout, input_tokens, output_tokens)
