from .claude import ClaudeAdapter
from .codex import CodexAdapter


def build_agent(name: str, config, timeout: int = 3600, runtime_env: dict[str, str] | None = None):
    if name == "claude":
        return ClaudeAdapter(config.claude, timeout, runtime_env=runtime_env)
    if name == "codex":
        return CodexAdapter(config.codex, timeout, runtime_env=runtime_env)
    raise ValueError(f"Unsupported agent backend: {name}")
