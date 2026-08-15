import json
from pathlib import Path

from aipipe.agents import agent_models, build_agent
from aipipe.agents.base import READ_ONLY_ROLES, collect_env, finalize_result
from aipipe.agents.codex import CodexAdapter
from aipipe.agents.claude import ClaudeAdapter
from aipipe.config import PipelineConfig
from aipipe.util import CommandResult


def test_collect_env_forwards_only_set_keys(monkeypatch):
    monkeypatch.setenv("AIPIPE_TEST_KEY_A", "value-a")
    monkeypatch.delenv("AIPIPE_TEST_KEY_B", raising=False)
    result = collect_env(("AIPIPE_TEST_KEY_A", "AIPIPE_TEST_KEY_B"))
    assert result == {"AIPIPE_TEST_KEY_A": "value-a"}


def test_finalize_result_appends_stderr_and_truncates():
    result = CommandResult(["cmd"], 0, "", "boom")
    agent_result = finalize_result(result, "output text")
    assert agent_result.ok
    assert "output text" in agent_result.output
    assert "STDERR:\nboom" in agent_result.output


def test_finalize_result_omits_stderr_section_when_empty():
    result = CommandResult(["cmd"], 1, "", "")
    agent_result = finalize_result(result, "output text", input_tokens=3, output_tokens=5)
    assert not agent_result.ok
    assert agent_result.output == "output text"
    assert agent_result.input_tokens == 3
    assert agent_result.output_tokens == 5


def test_agent_classes_expose_names():
    assert CodexAdapter.name == "codex"
    assert ClaudeAdapter.name == "claude"


def test_agent_models_expose_default_plus_agent_specific_options():
    claude_ids = {m.id for m in agent_models("claude")}
    codex_ids = {m.id for m in agent_models("codex")}
    assert None in claude_ids  # Default/Automatic option
    assert {"sonnet", "opus"} <= claude_ids
    assert None in codex_ids
    assert claude_ids != codex_ids  # available models depend on the agent


def test_agent_models_rejects_unknown_agent():
    try:
        agent_models("nonexistent")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_claude_adapter_passes_configured_model(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.claude.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, json.dumps({"result": "ok", "usage": {}}), "")

    monkeypatch.setattr("aipipe.agents.claude.run", fake_run)
    ClaudeAdapter({"model": "opus"}).run("IMPLEMENTER", "do it", tmp_path)
    cmd = captured["cmd"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"


def test_claude_adapter_omits_model_flag_when_unset(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.claude.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, json.dumps({"result": "ok", "usage": {}}), "")

    monkeypatch.setattr("aipipe.agents.claude.run", fake_run)
    ClaudeAdapter({}).run("IMPLEMENTER", "do it", tmp_path)
    assert "--model" not in captured["cmd"]


def test_codex_adapter_passes_configured_model(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, "", "")

    monkeypatch.setattr("aipipe.agents.codex.run", fake_run)
    CodexAdapter({"model": "gpt-5-codex"}).run("IMPLEMENTER", "do it", tmp_path)
    cmd = captured["cmd"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


def test_codex_adapter_omits_model_flag_when_unset(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, "", "")

    monkeypatch.setattr("aipipe.agents.codex.run", fake_run)
    CodexAdapter({}).run("IMPLEMENTER", "do it", tmp_path)
    assert "--model" not in captured["cmd"]


def test_build_agent_model_override_does_not_mutate_config(monkeypatch):
    monkeypatch.setattr("aipipe.agents.claude.require_binary", lambda name: None)
    cfg = PipelineConfig(agent="claude", claude={"binary": "claude"})
    agent = build_agent("claude", cfg, model="opus")
    assert agent.config["model"] == "opus"
    assert "model" not in cfg.claude


def test_build_agent_without_model_override_is_backward_compatible(monkeypatch):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    cfg = PipelineConfig(agent="codex", codex={"binary": "codex"})
    agent = build_agent("codex", cfg)
    assert agent.config is cfg.codex
    assert "model" not in agent.config


def test_planner_role_is_in_the_shared_read_only_role_set():
    assert "PLANNER" in READ_ONLY_ROLES
    assert "IMPLEMENTER" not in READ_ONLY_ROLES


def test_claude_adapter_restricts_planner_to_read_only_tools(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.claude.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, json.dumps({"result": "plan", "usage": {}}), "")

    monkeypatch.setattr("aipipe.agents.claude.run", fake_run)
    ClaudeAdapter({}).run("PLANNER", "plan it", tmp_path)
    cmd = captured["cmd"]
    assert "--tools" in cmd
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob"
    assert "--permission-mode" in cmd


def test_claude_adapter_keeps_implementer_write_capable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.claude.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, json.dumps({"result": "ok", "usage": {}}), "")

    monkeypatch.setattr("aipipe.agents.claude.run", fake_run)
    ClaudeAdapter({}).run("IMPLEMENTER", "do it", tmp_path)
    assert "--tools" not in captured["cmd"]


def test_codex_adapter_sandboxes_planner_as_read_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, "", "")

    monkeypatch.setattr("aipipe.agents.codex.run", fake_run)
    CodexAdapter({}).run("PLANNER", "plan it", tmp_path)
    cmd = captured["cmd"]
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"


def test_codex_adapter_keeps_implementer_workspace_write(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, "", "")

    monkeypatch.setattr("aipipe.agents.codex.run", fake_run)
    CodexAdapter({}).run("IMPLEMENTER", "do it", tmp_path)
    cmd = captured["cmd"]
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
