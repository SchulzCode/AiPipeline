from __future__ import annotations

import json
from pathlib import Path

from .base import AgentResult, ModelOption, READ_ONLY_ROLES, collect_env, finalize_result
from ..util import require_binary, run, safe_process_env, truncate


class CodexAdapter:
    name = "codex"

    # Codex CLI model names accepted by --model.
    MODELS = [
        ModelOption(id=None, label="Default (automatic)"),
        ModelOption(id="gpt-5-codex", label="GPT-5 Codex"),
        ModelOption(id="gpt-5", label="GPT-5"),
    ]

    def __init__(self, config: dict, timeout: int = 3600, runtime_env: dict[str, str] | None = None):
        self.config = config
        self.timeout = timeout
        self.runtime_env = runtime_env or {}
        require_binary(config.get("binary", "codex"))

    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        binary = self.config.get("binary", "codex")
        sandbox = "read-only" if role in READ_ONLY_ROLES else "workspace-write"
        cmd = [binary, "exec", "--ephemeral", "--json", "--sandbox", sandbox, "--ask-for-approval", "never"]
        if self.config.get("ignore_user_config", True):
            cmd.append("--ignore-user-config")
        if sandbox == "workspace-write" and self.config.get("network_access", False):
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        model = self.config.get("model")
        if model:
            cmd += ["--model", str(model)]
        cmd.append(prompt)
        auth_env = collect_env((
            "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID",
            "OPENAI_PROJECT_ID", "CODEX_HOME",
        ))
        r = run(cmd, workspace, self.timeout, env=safe_process_env({**self.runtime_env, **auth_env}), inherit_env=False)
        final = ""
        input_tokens = output_tokens = 0
        for line in r.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    final = item.get("text", final)
            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
                input_tokens += int(usage.get("input_tokens", 0) or 0)
                output_tokens += int(usage.get("output_tokens", 0) or 0)
        return finalize_result(r, final or truncate(r.stdout, 18000), input_tokens, output_tokens)
