import json
from pathlib import Path

from aipipe.agents.qwen import QwenAdapter
from aipipe.util import CommandResult


def _result_payload(result: str = "done", input_tokens: int = 11, output_tokens: int = 7) -> str:
    return json.dumps(
        [
            {"type": "system", "subtype": "session_start", "model": "local-model"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": result,
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            },
        ]
    )


def test_qwen_adapter_builds_headless_json_command(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return CommandResult(cmd, 0, _result_payload(), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({"model": "qwen-local", "auth_type": "openai"}).run(
        "IMPLEMENTER", "make the change", tmp_path
    )

    cmd = captured["cmd"]
    assert cmd[:3] == ["qwen", "-p", "make the change"]
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--model") + 1] == "qwen-local"
    assert cmd[cmd.index("--auth-type") + 1] == "openai"
    assert "--append-system-prompt" in cmd
    assert captured["cwd"] == tmp_path


def test_qwen_adapter_uses_plan_for_read_only_roles(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, _result_payload("plan"), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({}).run("PLANNER", "plan it", tmp_path)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--approval-mode") + 1] == "plan"


def test_qwen_adapter_uses_yolo_for_implementation_roles(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, _result_payload(), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--approval-mode") + 1] == "yolo"


def test_qwen_adapter_parses_final_result_and_token_usage(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        return CommandResult(cmd, 0, _result_payload("implemented", 123, 45), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    result = QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    assert result.ok
    assert result.output == "implemented"
    assert result.input_tokens == 123
    assert result.output_tokens == 45


def test_qwen_adapter_accepts_camel_case_usage_fields(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    payload = json.dumps(
        [
            {
                "type": "result",
                "result": "done",
                "usage": {"inputTokens": 8, "outputTokens": 3},
            }
        ]
    )

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        return CommandResult(cmd, 0, payload, "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    result = QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    assert result.input_tokens == 8
    assert result.output_tokens == 3


def test_qwen_adapter_preserves_nonzero_exit_and_stderr(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        return CommandResult(cmd, 55, _result_payload("budget exceeded", 20, 2), "limit hit")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    result = QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    assert not result.ok
    assert result.returncode == 55
    assert "budget exceeded" in result.output
    assert "STDERR:\nlimit hit" in result.output
    assert result.input_tokens == 20
    assert result.output_tokens == 2


def test_qwen_adapter_keeps_raw_stdout_when_json_is_malformed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        return CommandResult(cmd, 1, "not-json", "parse failed")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    result = QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    assert not result.ok
    assert "not-json" in result.output
    assert "parse failed" in result.output
    assert result.input_tokens == 0
    assert result.output_tokens == 0
