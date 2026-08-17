from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .base import AgentResult, ModelOption, READ_ONLY_ROLES, finalize_result
from .qwen_readiness import QwenReadinessError, probe_local_model_endpoint
from ..util import require_binary, run, safe_process_env


_AIPIPE_SYSTEM_PROMPT = """You are running inside AIpipe's managed task workspace.
AIpipe owns Git history and remote lifecycle operations. Do not commit, push, merge,
rebase, create pull requests, change branches, or modify remotes. Work only inside
the supplied workspace. Implementation and repair roles may edit source files and
run relevant local verification. Read-only roles must not modify the workspace.
"""

# AIpipe deliberately does not set provider-generic OPENAI_* endpoint variables
# in the worker environment. They are translated only for the Qwen subprocess so
# the existing Codex adapter can continue using its normal provider endpoint.
_LOCAL_ENV_MAP = {
    "AIPIPE_LOCAL_LLM_BASE_URL": "OPENAI_BASE_URL",
    "AIPIPE_LOCAL_LLM_API_KEY": "OPENAI_API_KEY",
    "AIPIPE_LOCAL_LLM_MODEL": "OPENAI_MODEL",
}
_LOCAL_MODEL_ALIAS = os.environ.get("AIPIPE_LOCAL_LLM_MODEL", "qwen-local").strip() or "qwen-local"


def _local_settings(runtime_env: dict[str, str]) -> dict[str, str]:
    source = dict(os.environ)
    source.update(runtime_env)
    return {
        key: value
        for key in _LOCAL_ENV_MAP
        if (value := source.get(key))
    }


def _local_subprocess_env(runtime_env: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    source = dict(os.environ)
    source.update(runtime_env)
    mapped = {
        provider_key: value
        for aipipe_key, provider_key in _LOCAL_ENV_MAP.items()
        if (value := source.get(aipipe_key))
    }
    # Do not expose the AIpipe-specific source variables to the child process;
    # only the translated provider variables are needed by Qwen Code.
    passthrough = {key: value for key, value in runtime_env.items() if key not in _LOCAL_ENV_MAP}
    passthrough.update(mapped)
    return safe_process_env(passthrough), mapped


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

    # The model alias is deployment-specific and comes from the same setting the
    # worker uses to reach the local server. A stable fallback keeps local dev and
    # the model-listing API useful before a custom alias is configured.
    MODELS = [
        ModelOption(id=None, label="Default (automatic)"),
        ModelOption(id=_LOCAL_MODEL_ALIAS, label=f"Local Qwen ({_LOCAL_MODEL_ALIAS})"),
    ]

    def __init__(self, config: dict, timeout: int = 3600, runtime_env: dict[str, str] | None = None):
        self.config = config
        self.timeout = timeout
        self.runtime_env = runtime_env or {}
        binary = config.get("binary", "qwen")
        require_binary(binary)

        local = _local_settings(self.runtime_env)
        base_url = local.get("AIPIPE_LOCAL_LLM_BASE_URL", "")
        if base_url and config.get("readiness_check", True):
            model = str(config.get("model") or local.get("AIPIPE_LOCAL_LLM_MODEL", ""))
            readiness = probe_local_model_endpoint(
                base_url,
                api_key=local.get("AIPIPE_LOCAL_LLM_API_KEY", ""),
                model=model,
                timeout_seconds=float(config.get("readiness_timeout_seconds", 3.0)),
            )
            if not readiness.ok:
                raise QwenReadinessError(readiness.detail)

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

        process_env, local_env = _local_subprocess_env(self.runtime_env)
        auth_type = self.config.get("auth_type") or ("openai" if local_env.get("OPENAI_BASE_URL") else None)
        if auth_type:
            cmd += ["--auth-type", str(auth_type)]
        model = self.config.get("model") or local_env.get("OPENAI_MODEL")
        if model:
            cmd += ["--model", str(model)]

        result = run(
            cmd,
            workspace,
            self.timeout,
            env=process_env,
            inherit_env=False,
        )
        final, input_tokens, output_tokens = _parse_headless_output(result.stdout)
        return finalize_result(result, final or result.stdout, input_tokens, output_tokens)
