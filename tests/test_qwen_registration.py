from aipipe.agents import agent_models, build_agent
from aipipe.agents.qwen import QwenAdapter
from aipipe.config import PipelineConfig, config_from_merged


def test_qwen_is_registered_as_agent_backend():
    assert agent_models("qwen") == QwenAdapter.MODELS


def test_qwen_config_loads_arbitrary_local_model_alias():
    cfg = config_from_merged({
        "agent": "qwen",
        "qwen": {"model": "qwen3-coder-local", "binary": "qwen-custom"},
    })
    assert cfg.agent == "qwen"
    assert cfg.qwen == {"model": "qwen3-coder-local", "binary": "qwen-custom"}


def test_build_qwen_uses_config_without_mutating_it(monkeypatch):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    cfg = PipelineConfig(agent="qwen", qwen={"binary": "qwen", "model": "local-default"})
    agent = build_agent("qwen", cfg)
    assert isinstance(agent, QwenAdapter)
    assert agent.config is cfg.qwen
    assert cfg.qwen["model"] == "local-default"


def test_build_qwen_model_override_is_non_mutating(monkeypatch):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    cfg = PipelineConfig(agent="qwen", qwen={"binary": "qwen", "model": "local-default"})
    agent = build_agent("qwen", cfg, model="project-local-alias")
    assert agent.config["model"] == "project-local-alias"
    assert cfg.qwen["model"] == "local-default"


def test_existing_agent_defaults_remain_unchanged():
    cfg = PipelineConfig()
    assert cfg.agent == "codex"
    assert cfg.codex == {}
    assert cfg.claude == {}
    assert cfg.qwen == {}
