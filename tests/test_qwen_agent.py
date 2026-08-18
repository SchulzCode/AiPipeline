import json
from pathlib import Path

from aipipe.agents.qwen import QwenAdapter, _parse_headless_output
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


def _array_option(cmd: list[str], name: str) -> list[str]:
    start = cmd.index(name) + 1
    values = []
    for value in cmd[start:]:
        if value.startswith("-"):
            break
        values.append(value)
    return values


def _assert_common_qwen_denies(values: list[str]) -> None:
    for tool in (
        "agent",
        "task",
        "list_agents",
        "skill",
        "enter_worktree",
        "exit_worktree",
        "tool_search",
        "web_fetch",
        "computer_use__*",
    ):
        assert tool in values


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
    assert "--safe-mode" not in cmd
    assert cmd[cmd.index("-e") + 1] == "none"
    assert "--chat-recording=false" in cmd
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
    assert _array_option(cmd, "--core-tools") == [
        "read_file",
        "grep_search",
        "glob",
        "list_directory",
    ]
    denied = _array_option(cmd, "--exclude-tools")
    _assert_common_qwen_denies(denied)
    assert "Bash(git *)" not in denied
    assert "Bash(gh *)" not in denied


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
    assert _array_option(cmd, "--core-tools") == [
        "read_file",
        "grep_search",
        "glob",
        "list_directory",
        "edit",
        "write_file",
        "run_shell_command",
    ]
    denied = _array_option(cmd, "--exclude-tools")
    _assert_common_qwen_denies(denied)
    assert "Bash(git *)" in denied
    assert "Bash(gh *)" in denied


def test_qwen_adapter_planner_prompt_is_repository_grounded_and_terse(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["cmd"] = cmd
        return CommandResult(cmd, 0, _result_payload("plan"), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({}).run("PLANNER", "plan it", tmp_path)

    cmd = captured["cmd"]
    system_prompt = cmd[cmd.index("--append-system-prompt") + 1]
    assert "workspace-relative paths" in system_prompt
    assert "Do not create subagents" in system_prompt
    assert "concrete implementation code" in system_prompt
    assert "merely restate the task requirements" in system_prompt
    assert "closest existing tests" in system_prompt
    assert "Do not narrate repository exploration" in system_prompt
    assert "do not search the repository for the issue number" in system_prompt
    assert "Do not read README files unless" in system_prompt
    assert "immediately produce the required plan" in system_prompt
    assert "Never call agent, task, list_agents" in system_prompt


def test_qwen_adapter_uses_ephemeral_system_settings(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        captured["env"] = dict(env or {})
        captured["qwen_home_exists"] = Path(env["QWEN_HOME"]).is_dir()
        settings_path = Path(env["QWEN_CODE_SYSTEM_SETTINGS_PATH"])
        captured["settings_path"] = settings_path
        captured["settings_path_exists"] = settings_path.is_file()
        captured["settings"] = json.loads(settings_path.read_text(encoding="utf-8"))
        return CommandResult(cmd, 0, _result_payload(), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    env = captured["env"]
    settings = captured["settings"]
    assert captured["qwen_home_exists"] is True
    assert captured["settings_path_exists"] is True
    assert env["QWEN_HOME"] == env["QWEN_RUNTIME_DIR"]
    assert Path(env["QWEN_HOME"]).name.startswith("aipipe-qwen-")
    assert Path(env["QWEN_CODE_SYSTEM_SETTINGS_PATH"]).parent == Path(env["QWEN_HOME"])
    assert settings["context"]["fileName"].startswith(".aipipe-context-disabled-aipipe-qwen-")
    assert settings["context"]["includeDirectories"] == []
    assert settings["context"]["loadFromIncludeDirectories"] is False
    assert settings["tools"]["computerUse"]["enabled"] is False
    assert settings["tools"]["toolSearch"]["enabled"] is False
    assert "task" in settings["tools"]["disabled"]
    assert "todo_write" in settings["tools"]["disabled"]
    assert settings["mcp"]["excluded"] == ["*"]
    assert settings["memory"]["enableManagedAutoMemory"] is False
    assert settings["memory"]["enableManagedAutoDream"] is False
    assert settings["memory"]["enableAutoSkill"] is False
    assert settings["memory"]["enableTeamMemory"] is False
    assert settings["memory"]["enableTeamMemorySync"] is False
    assert env["QWEN_USAGE_STATISTICS_ENABLED"] == "0"
    assert env["QWEN_TELEMETRY_ENABLED"] == "0"
    assert not Path(env["QWEN_HOME"]).exists()
    assert not captured["settings_path"].exists()


def test_qwen_adapter_system_settings_disable_write_tools_for_read_only_roles(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        settings_path = Path(env["QWEN_CODE_SYSTEM_SETTINGS_PATH"])
        captured["settings"] = json.loads(settings_path.read_text(encoding="utf-8"))
        return CommandResult(cmd, 0, _result_payload("plan"), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({}).run("PLANNER", "plan it", tmp_path)

    disabled = captured["settings"]["tools"]["disabled"]
    assert "edit" in disabled
    assert "write_file" in disabled
    assert "run_shell_command" in disabled


def test_qwen_adapter_system_settings_disable_project_skills(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    skill_dir = tmp_path / ".qwen" / "skills" / "folder-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: custom-skill\ndescription: test\n---\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_run(cmd, cwd, timeout, env=None, inherit_env=True):
        settings_path = Path(env["QWEN_CODE_SYSTEM_SETTINGS_PATH"])
        captured["settings"] = json.loads(settings_path.read_text(encoding="utf-8"))
        return CommandResult(cmd, 0, _result_payload(), "")

    monkeypatch.setattr("aipipe.agents.qwen.run", fake_run)
    QwenAdapter({}).run("IMPLEMENTER", "do it", tmp_path)

    disabled = captured["settings"]["skills"]["disabled"]
    assert "custom-skill" in disabled
    assert "folder-skill" in disabled


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


def test_qwen_headless_fallback_returns_only_final_assistant_text():
    payload = json.dumps(
        [
            {
                "type": "system",
                "session_id": "session-secret",
                "cwd": "/private/worktree",
                "tools": ["agent", "computer_use__click"],
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "intermediate narration"},
                        {"type": "tool_use", "name": "read_file", "input": {"path": "x"}},
                    ],
                    "usage": {"input_tokens": 101, "output_tokens": 5},
                },
            },
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "source"}]}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "private chain"},
                        {"type": "text", "text": "FINAL PLAN"},
                        {"type": "tool_use", "name": "agent", "input": {"prompt": "do more"}},
                    ],
                    "usage": {"input_tokens": 123, "output_tokens": 9},
                },
            },
        ]
    )

    final, input_tokens, output_tokens = _parse_headless_output(payload)

    assert final == "FINAL PLAN"
    assert input_tokens == 123
    assert output_tokens == 9
    assert "session-secret" not in final
    assert "/private/worktree" not in final
    assert "computer_use" not in final
    assert "private chain" not in final
    assert "intermediate narration" not in final


def test_qwen_headless_fallback_recovers_latest_nonzero_assistant_usage():
    payload = json.dumps(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "grep_search", "input": {}}],
                    "usage": {"input_tokens": 55, "output_tokens": 3},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        ]
    )

    assert _parse_headless_output(payload) == ("done", 55, 3)


def test_qwen_headless_fallback_ignores_empty_result_event():
    payload = json.dumps(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "actual final"}],
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                },
            },
            {"type": "result", "result": "", "usage": {"input_tokens": 99, "output_tokens": 99}},
        ]
    )

    assert _parse_headless_output(payload) == ("actual final", 12, 4)


def test_qwen_headless_fallback_keeps_raw_json_when_no_assistant_text():
    payload = json.dumps(
        [
            {"type": "system", "session_id": "abc"},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "grep_search", "input": {}}],
                    "usage": {"input_tokens": 11, "output_tokens": 2},
                },
            },
        ]
    )

    final, input_tokens, output_tokens = _parse_headless_output(payload)
    assert final == payload
    assert input_tokens == 0
    assert output_tokens == 0


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
