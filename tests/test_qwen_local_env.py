from pathlib import Path

from aipipe.agents.codex import CodexAdapter
from aipipe.agents.qwen import QwenAdapter
from aipipe.util import CommandResult


_QWEN_OK = '[{"type":"result","result":"ok","usage":{}}]'


def test_qwen_translates_aipipe_local_endpoint_only_in_child_env(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_BASE_URL", "http://host.docker.internal:8080/v1")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_API_KEY", "local-secret")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_MODEL", "qwen-local")
    # A provider-generic endpoint in the parent process must not override the
    # AIpipe local settings used for Qwen.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://should-not-be-used.invalid/v1")
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["inherit_env"] = inherit_env
        return CommandResult(cmd, 0, _QWEN_OK, "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({"readiness_check": False}).run("IMPLEMENTER", "do it", tmp_path)

    env = captured["env"]
    cmd = captured["cmd"]
    assert env["OPENAI_BASE_URL"] == "http://host.docker.internal:8080/v1"
    assert env["OPENAI_API_KEY"] == "local-secret"
    assert env["OPENAI_MODEL"] == "qwen-local"
    assert not any(key.startswith("AIPIPE_LOCAL_LLM_") for key in env)
    assert captured["inherit_env"] is False
    assert cmd[cmd.index("--auth-type") + 1] == "openai"
    assert cmd[cmd.index("--model") + 1] == "qwen-local"


def test_qwen_runtime_env_can_override_process_local_settings(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_BASE_URL", "http://process:8080/v1")
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["env"] = env
        return CommandResult(cmd, 0, _QWEN_OK, "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter(
        {"readiness_check": False},
        runtime_env={
            "AIPIPE_LOCAL_LLM_BASE_URL": "http://runtime:9000/v1",
            "AIPIPE_LOCAL_LLM_API_KEY": "runtime-key",
            "AIPIPE_LOCAL_LLM_MODEL": "runtime-model",
        },
    ).run("IMPLEMENTER", "do it", tmp_path)

    assert captured["env"]["OPENAI_BASE_URL"] == "http://runtime:9000/v1"
    assert captured["env"]["OPENAI_API_KEY"] == "runtime-key"
    assert captured["env"]["OPENAI_MODEL"] == "runtime-model"


def test_explicit_qwen_model_still_wins_over_local_model_alias(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_BASE_URL", "http://host.docker.internal:8080/v1")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_MODEL", "env-model")
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, _QWEN_OK, "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({"model": "project-model", "readiness_check": False}).run("IMPLEMENTER", "do it", tmp_path)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--model") + 1] == "project-model"


def test_aipipe_local_settings_do_not_redirect_codex(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_BASE_URL", "http://host.docker.internal:8080/v1")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_API_KEY", "local-secret")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_MODEL", "qwen-local")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["env"] = env
        return CommandResult(cmd, 0, "", "")

    monkeypatch.setattr("aipipe.agents.codex.run", fake_run)
    CodexAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    env = captured["env"]
    assert "OPENAI_BASE_URL" not in env
    assert "OPENAI_API_KEY" not in env
    assert not any(key.startswith("AIPIPE_LOCAL_LLM_") for key in env)
