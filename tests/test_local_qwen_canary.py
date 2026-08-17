from pathlib import Path

from aipipe.agents.base import AgentResult
from aipipe.agents.claude import ClaudeAdapter
from aipipe.agents.codex import CodexAdapter
from aipipe.local_canary import run_local_qwen_canary


class _SuccessfulFakeQwen:
    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        if role == "PLANNER":
            return AgentResult(True, "Disposable local-Qwen test repository.", 0, 11, 4)
        if role == "IMPLEMENTER":
            (workspace / "canary_output.txt").write_text("LOCAL_QWEN_CANARY_OK\n", encoding="utf-8")
            return AgentResult(True, "Created the requested canary artifact.", 0, 17, 6)
        raise AssertionError(f"unexpected role: {role}")


class _ReadOnlyViolatingFakeQwen:
    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        if role == "PLANNER":
            (workspace / "unexpected.txt").write_text("should not exist", encoding="utf-8")
            return AgentResult(True, "I changed a file.", 0, 1, 1)
        raise AssertionError("implementation must not run after read-only violation")


class _BrokenImplementationFakeQwen:
    def run(self, role: str, prompt: str, workspace: Path) -> AgentResult:
        if role == "PLANNER":
            return AgentResult(True, "ok", 0, 1, 1)
        return AgentResult(True, "claimed success without creating the file", 0, 2, 2)


def test_local_canary_exercises_read_only_implementation_and_quality_verification():
    result = run_local_qwen_canary(adapter_factory=_SuccessfulFakeQwen)

    assert result.ok
    assert result.read_only_ok
    assert result.implementation_ok
    assert result.verification_ok
    assert result.input_tokens == 28
    assert result.output_tokens == 10
    assert "deterministic AIpipe verification" in result.detail


def test_local_canary_fails_if_read_only_role_mutates_workspace():
    result = run_local_qwen_canary(adapter_factory=_ReadOnlyViolatingFakeQwen)

    assert not result.ok
    assert not result.read_only_ok
    assert not result.implementation_ok
    assert not result.verification_ok
    assert "modified the workspace" in result.detail


def test_local_canary_fails_when_implementation_does_not_create_artifact():
    result = run_local_qwen_canary(adapter_factory=_BrokenImplementationFakeQwen)

    assert not result.ok
    assert result.read_only_ok
    assert not result.implementation_ok
    assert not result.verification_ok


def test_local_canary_is_qwen_specific_and_does_not_change_cloud_adapter_construction(monkeypatch):
    monkeypatch.setattr("aipipe.agents.codex.require_binary", lambda name: None)
    monkeypatch.setattr("aipipe.agents.claude.require_binary", lambda name: None)
    # If cloud adapter construction somehow crossed the local-Qwen readiness
    # boundary, this would fail the test immediately.
    monkeypatch.setattr(
        "aipipe.agents.qwen.probe_local_model_endpoint",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected local probe")),
    )

    codex = CodexAdapter({})
    claude = ClaudeAdapter({})
    assert codex.name == "codex"
    assert claude.name == "claude"
