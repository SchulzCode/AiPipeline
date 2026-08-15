from __future__ import annotations

import json
from pathlib import Path

from .base import AgentResult, ModelOption, READ_ONLY_ROLES, collect_env, finalize_result
from ..util import require_binary, run, safe_process_env


class ClaudeAdapter:
    name = "claude"

    # Claude Code CLI model aliases, resolved by the CLI itself to its
    # current underlying model. Using aliases (rather than dated model ids)
    # keeps this list stable as Anthropic ships new model versions.
    MODELS = [
        ModelOption(id=None, label="Default (automatic)"),
        ModelOption(id="sonnet", label="Sonnet"),
        ModelOption(id="opus", label="Opus"),
    ]

    def __init__(self, config: dict, timeout: int = 3600, runtime_env: dict[str, str] | None = None):
        self.config = config
        self.timeout = timeout
        self.runtime_env = runtime_env or {}
        require_binary(config.get("binary", "claude"))

    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        binary = self.config.get("binary", "claude")
        cmd = [binary, "-p", "--no-session-persistence", "--output-format", "json"]
        if role in READ_ONLY_ROLES:
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
        auth_env = collect_env((
            "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
            "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
            "GOOGLE_APPLICATION_CREDENTIALS", "CLOUD_ML_REGION",
        ))
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
        return finalize_result(r, final or r.stdout, input_tokens, output_tokens)
