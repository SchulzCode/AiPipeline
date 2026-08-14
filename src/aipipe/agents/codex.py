from __future__ import annotations

import json
import os
from pathlib import Path

from .base import AgentResult, ModelOption
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
        sandbox = "read-only" if role in {"REVIEWER", "SECURITY_REVIEWER", "ROUTER"} else "workspace-write"
        cmd = [binary, "exec", "--ephemeral", "--json", "--sandbox", sandbox, "--ask-for-approval", "never"]
        if self.config.get("ignore_user_config", True):
            cmd.append("--ignore-user-config")
        if sandbox == "workspace-write" and self.config.get("network_access", False):
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        model = self.config.get("model")
        if model:
            cmd += ["--model", str(model)]
        cmd.append(prompt)
        auth_keys = (
            "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID",
            "OPENAI_PROJECT_ID", "CODEX_HOME",
        )
        auth_env = {key: value for key in auth_keys if (value := os.environ.get(key))}
        r = run(cmd, workspace, self.timeout, env=safe_process_env({**self.runtime_env, **auth_env}), inherit_env=False)
        final = ""
        input_tokens = output_tokens = 0
        raw_events = []
        for line in r.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_events.append(event)
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    final = item.get("text", final)
            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
                input_tokens += int(usage.get("input_tokens", 0) or 0)
                output_tokens += int(usage.get("output_tokens", 0) or 0)
        output = final or truncate(r.stdout, 18000)
        if r.stderr:
            output += "\nSTDERR:\n" + truncate(r.stderr, 6000)
        return AgentResult(r.ok, truncate(output, 24000), r.returncode, input_tokens, output_tokens)
