from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .base import AgentResult, ModelOption, READ_ONLY_ROLES, finalize_result
from .qwen_readiness import QwenReadinessError, probe_local_model_endpoint
from ..util import require_binary, run, safe_process_env


_READ_ONLY_CORE_TOOLS = (
    "read_file",
    "grep_search",
    "glob",
    "list_directory",
)
_WRITE_CORE_TOOLS = (
    *_READ_ONLY_CORE_TOOLS,
    "edit",
    "write_file",
    "run_shell_command",
)

# Qwen Code can surface orchestration/builtin tools that AIpipe never wants its
# bounded agents to use. Keep explicit permission-layer denies as defense in
# depth even though role core-tools and system settings also restrict registry
# exposure.
_COMMON_EXCLUDE_TOOLS = (
    "agent",
    "task",
    "list_agents",
    "task_stop",
    "send_message",
    "skill",
    "enter_worktree",
    "exit_worktree",
    "record_artifact",
    "get_goal",
    "update_goal",
    "tool_search",
    "web_fetch",
    "read_mcp_resource",
    "cron_create",
    "cron_list",
    "cron_delete",
    "loop_wakeup",
    "create_sub_session",
    "computer_use__*",
)

# Tools that should never be registered for an AIpipe-managed Qwen subprocess.
# Some are deferred/builtin capabilities and some are version-specific names
# observed in Qwen 0.21.x. Exact disabling complements --core-tools rather than
# replacing it.
_AMBIENT_DISABLED_TOOLS = (
    "agent",
    "task",
    "list_agents",
    "task_stop",
    "send_message",
    "skill",
    "enter_worktree",
    "exit_worktree",
    "record_artifact",
    "get_goal",
    "update_goal",
    "tool_search",
    "web_fetch",
    "read_mcp_resource",
    "cron_create",
    "cron_list",
    "cron_delete",
    "loop_wakeup",
    "create_sub_session",
    "notebook_edit",
    "read_many_files",
    "zoom_image",
    "todo_write",
    "monitor",
)

# AIpipe owns Git/worktree/remote lifecycle. Implementation roles still need a
# shell for tests and local build commands, so deny GitHub/Git lifecycle commands
# at Qwen's permission layer rather than removing shell access entirely.
_IMPLEMENTATION_EXCLUDE_TOOLS = (
    *_COMMON_EXCLUDE_TOOLS,
    "Bash(git *)",
    "Bash(gh *)",
)

_AIPIPE_SYSTEM_PROMPT = """You are one bounded agent inside AIpipe's managed task workspace.
The current working directory is already the correct AIpipe-managed worktree.
Always use workspace-relative paths; never reconstruct or guess the absolute workspace path.

AIpipe alone owns Git history, worktrees, branches, remotes, pull requests, CI, and merge lifecycle.
Never create, enter, exit, or remove worktrees. Never commit, push, merge, rebase, reset, switch
branches, modify remotes, or create pull requests. Do not create subagents or independent sessions.
Do not use web, computer-use, cron, memory, skill, goal-management, or artifact workflows. If Qwen
runtime metadata happens to mention such tools, treat them as unavailable and never call them.
Use only the tools intentionally exposed for your role.

Explore purposefully: search when the relevant file or symbol is unknown, read only task-relevant code,
avoid rereading unchanged content, and stop exploring once enough repository evidence exists to do the
assigned role. Implementation and repair roles may edit source files and run relevant local verification.
Read-only roles must never modify repository state.
"""

_PLANNER_SYSTEM_PROMPT = """
For PLANNER work, inspect concrete implementation code before producing the plan. Identify the relevant
symbols/functions/classes, their important call sites, and the closest existing tests to extend.

Do not narrate repository exploration or announce each tool call; use the read/search tools directly.
Never call agent, task, list_agents, enter_worktree, exit_worktree, skill, tool_search, computer-use, or
any session-management tool even if it appears in runtime metadata. The task contract already contains
the issue/task requirements, so do not search the repository for the issue number or try to rediscover
the issue description. Do not read README files unless the task directly concerns project documentation
or overview behavior. Prefer grep/glob to locate concrete symbols, then read only the relevant files or
sections. Once enough evidence exists, immediately produce the required plan.

Do not merely restate the task requirements. If repository evidence does not support a claimed file or
symbol, omit it rather than guessing. Do not write implementation code.
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


def _assistant_text(event: Any) -> tuple[str, tuple[int, int]]:
    """Return only user-visible text from one Qwen assistant event."""
    if not isinstance(event, dict) or event.get("type") != "assistant":
        return "", (0, 0)
    message = event.get("message")
    if not isinstance(message, dict):
        return "", (0, 0)
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    texts = [
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") == "text"
        and str(block.get("text", "")).strip()
    ]
    return "\n".join(texts).strip(), _usage_tokens(message.get("usage"))


def _latest_nonzero_assistant_usage(events: list[Any]) -> tuple[int, int]:
    for event in reversed(events):
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        usage = _usage_tokens(message.get("usage"))
        if usage != (0, 0):
            return usage
    return 0, 0


def _parse_headless_output(stdout: str) -> tuple[str, int, int]:
    """Parse Qwen Code's buffered ``--output-format json`` payload.

    Prefer the terminal result envelope when present. Qwen 0.21.x can also
    complete successfully with an event array that has no usable result event;
    in that case return only the final text-bearing assistant message. Never
    turn a successful structured session into persisted transcript/session
    metadata merely because the terminal envelope shape changed.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, 0, 0

    if isinstance(payload, list):
        for event in reversed(payload):
            if not isinstance(event, dict) or event.get("type") != "result":
                continue
            final = event.get("result")
            if isinstance(final, str) and final.strip():
                input_tokens, output_tokens = _usage_tokens(event.get("usage"))
                return final, input_tokens, output_tokens

        for event in reversed(payload):
            final, usage = _assistant_text(event)
            if not final:
                continue
            if usage == (0, 0):
                usage = _latest_nonzero_assistant_usage(payload)
            return final, usage[0], usage[1]

        return stdout, 0, 0

    if isinstance(payload, dict):
        input_tokens, output_tokens = _usage_tokens(payload.get("usage"))
        final = payload.get("result", payload.get("response", ""))
        if isinstance(final, str) and final.strip():
            return final, input_tokens, output_tokens

    return stdout, 0, 0


def _core_tools_for_role(role: str) -> tuple[str, ...]:
    return _READ_ONLY_CORE_TOOLS if role in READ_ONLY_ROLES else _WRITE_CORE_TOOLS


def _excluded_tools_for_role(role: str) -> tuple[str, ...]:
    return _COMMON_EXCLUDE_TOOLS if role in READ_ONLY_ROLES else _IMPLEMENTATION_EXCLUDE_TOOLS


def _project_skill_names(workspace: Path) -> list[str]:
    """Find project skill names so system settings can hard-disable them.

    Qwen 0.21.x supports hard-disabled skill names but not a discovery-level
    switch. Personal skills are eliminated by the ephemeral QWEN_HOME and
    extension skills by ``-e none``; this closes the remaining project-skill
    path without trusting project-controlled Qwen settings.
    """
    root = workspace / ".qwen" / "skills"
    if not root.is_dir():
        return []

    names: set[str] = set()
    for skill_file in root.glob("*/SKILL.md"):
        # Directory names are valid fallback identifiers even if frontmatter is
        # malformed or cannot be read.
        names.add(skill_file.parent.name)
        try:
            prefix = skill_file.read_text(encoding="utf-8", errors="replace")[:8192]
        except OSError:
            continue
        lines = prefix.splitlines()
        if not lines or lines[0].strip() != "---":
            continue
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if not line.lstrip().startswith("name:"):
                continue
            name = line.split(":", 1)[1].strip().strip("\"'")
            if name:
                names.add(name)
            break
    return sorted(names)


def _system_settings_for_role(
    role: str,
    context_filename: str,
    project_skill_names: list[str],
) -> dict[str, Any]:
    disabled_tools = list(_AMBIENT_DISABLED_TOOLS)
    if role in READ_ONLY_ROLES:
        disabled_tools.extend(("edit", "write_file", "run_shell_command"))

    return {
        # Use a per-run impossible-to-guess filename instead of the default
        # QWEN.md so repository/parent-directory instructional context is not
        # loaded into the bounded AIpipe subprocess.
        "context": {
            "fileName": context_filename,
            "includeDirectories": [],
            "loadFromIncludeDirectories": False,
        },
        "tools": {
            "disabled": sorted(set(disabled_tools)),
            "computerUse": {"enabled": False},
            "toolSearch": {"enabled": False},
        },
        "permissions": {
            "deny": list(_excluded_tools_for_role(role)),
        },
        "skills": {
            "disabled": project_skill_names,
        },
        "mcp": {"excluded": ["*"]},
        "memory": {
            "enableManagedAutoMemory": False,
            "enableManagedAutoDream": False,
            "enableAutoSkill": False,
            "enableTeamMemory": False,
            "enableTeamMemorySync": False,
        },
    }


def _system_prompt_for_role(role: str) -> str:
    if role == "PLANNER":
        return _AIPIPE_SYSTEM_PROMPT + _PLANNER_SYSTEM_PROMPT
    return _AIPIPE_SYSTEM_PROMPT


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
            "-e",
            "none",
            "--chat-recording=false",
            "--core-tools",
            *_core_tools_for_role(role),
            "--exclude-tools",
            *_excluded_tools_for_role(role),
            "--append-system-prompt",
            _system_prompt_for_role(role),
        ]

        process_env, local_env = _local_subprocess_env(self.runtime_env)
        auth_type = self.config.get("auth_type") or ("openai" if local_env.get("OPENAI_BASE_URL") else None)
        if auth_type:
            cmd += ["--auth-type", str(auth_type)]
        model = self.config.get("model") or local_env.get("OPENAI_MODEL")
        if model:
            cmd += ["--model", str(model)]

        # Every AIpipe agent run is intentionally ephemeral. System settings have
        # higher precedence than project/user settings, while QWEN_HOME removes
        # user state altogether. This gives --core-tools a real chance to filter
        # registration without safe-mode disabling the permission/tool settings.
        with tempfile.TemporaryDirectory(prefix="aipipe-qwen-") as qwen_home:
            process_env["QWEN_HOME"] = qwen_home
            process_env["QWEN_RUNTIME_DIR"] = qwen_home
            process_env["QWEN_USAGE_STATISTICS_ENABLED"] = "0"
            process_env["QWEN_TELEMETRY_ENABLED"] = "0"

            context_filename = f".aipipe-context-disabled-{Path(qwen_home).name}.md"
            settings_path = Path(qwen_home) / "system-settings.json"
            settings_path.write_text(
                json.dumps(
                    _system_settings_for_role(
                        role,
                        context_filename,
                        _project_skill_names(workspace),
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            process_env["QWEN_CODE_SYSTEM_SETTINGS_PATH"] = str(settings_path)

            result = run(
                cmd,
                workspace,
                self.timeout,
                env=process_env,
                inherit_env=False,
            )
        final, input_tokens, output_tokens = _parse_headless_output(result.stdout)
        return finalize_result(result, final or result.stdout, input_tokens, output_tokens)
