from __future__ import annotations

import json
import os
from pathlib import Path

from .base import AgentResult
from ..util import require_binary, run, safe_process_env, truncate


class ClaudeAdapter:
    name = "claude"

    def __init__(self, config: dict, timeout: int = 3600, runtime_env: dict[str, str] | None = None):
        self.config = config
        self.timeout = timeout
        self.runtime_env = runtime_env or {}
        require_binary(config.get("binary", "claude"))

    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        binary = self.config.get("binary", "claude")
        cmd = [binary, "-p", "--bare", "--no-session-persistence", "--output-format", "json"]
        if role in {"REVIEWER", "SECURITY_REVIEWER", "ROUTER"}:
            cmd += ["--tools", "Read,Grep,Glob", "--permission-mode", "auto"]
        else:
            cmd += ["--permission-mode", self.config.get("permission_mode", "auto")]
        model = self.config.get("model")
        if model:
            cmd += ["--model", str(model)]
        max_budget = self.config.get("max_budget_usd")
        if max_budget is not None:
            cmd += ["--max-budget-usd", str(max_budget)]
        max_turns = self.config.get("max_turns")
        if max_turns is not None:
            cmd += ["--max-turns", str(max_turns)]
        cmd.append(prompt)
        auth_keys = (
            "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
            "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
            "GOOGLE_APPLICATION_CREDENTIALS", "CLOUD_ML_REGION",
        )
        auth_env = {key: value for key in auth_keys if (value := os.environ.get(key))}
        r = run(cmd, workspace, self.timeout, env=safe_process_env({**self.runtime_env, **auth_env}), inherit_env=False)
        final = ""
        input_tokens = output_tokens = 0
        try:
            payload = json.loads(r.stdout)
            final = str(payload.get("result", ""))
            usage = payload.get("usage", {}) or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            # Whole-tree accounting may be available under modelUsage/model_usage.
            model_usage = payload.get("modelUsage") or payload.get("model_usage") or {}
            if isinstance(model_usage, dict) and model_usage:
                i = o = 0
                for u in model_usage.values():
                    if isinstance(u, dict):
                        i += int(u.get("inputTokens", u.get("input_tokens", 0)) or 0)
                        o += int(u.get("outputTokens", u.get("output_tokens", 0)) or 0)
                if i or o:
                    input_tokens, output_tokens = i, o
        except json.JSONDecodeError:
            final = r.stdout
        output = final or r.stdout
        if r.stderr:
            output += "\nSTDERR:\n" + truncate(r.stderr, 6000)
        return AgentResult(r.ok, truncate(output, 24000), r.returncode, input_tokens, output_tokens)
