from .base import ModelOption
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .qwen import QwenAdapter

# Model lists live on each adapter (the agent abstraction); this registry is
# just a lookup so callers never need agent-specific branching to find them.
AGENT_MODELS: dict[str, list[ModelOption]] = {
    "claude": ClaudeAdapter.MODELS,
    "codex": CodexAdapter.MODELS,
    "qwen": QwenAdapter.MODELS,
}


def agent_models(name: str) -> list[ModelOption]:
    if name not in AGENT_MODELS:
        raise ValueError(f"Unsupported agent backend: {name}")
    return AGENT_MODELS[name]


def build_agent(name: str, config, timeout: int = 3600, runtime_env: dict[str, str] | None = None, model: str | None = None):
    if name == "claude":
        agent_config = {**config.claude, "model": model} if model else config.claude
        return ClaudeAdapter(agent_config, timeout, runtime_env=runtime_env)
    if name == "codex":
        agent_config = {**config.codex, "model": model} if model else config.codex
        return CodexAdapter(agent_config, timeout, runtime_env=runtime_env)
    if name == "qwen":
        agent_config = {**config.qwen, "model": model} if model else config.qwen
        return QwenAdapter(agent_config, timeout, runtime_env=runtime_env)
    raise ValueError(f"Unsupported agent backend: {name}")
