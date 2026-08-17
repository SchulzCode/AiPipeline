import io
import json
from urllib import error as urlerror

import pytest

from aipipe.agents.qwen import QwenAdapter
from aipipe.agents.qwen_readiness import LocalModelReadiness, QwenReadinessError, probe_local_model_endpoint
from aipipe.cli import _doctor, build_parser
from aipipe.util import CommandResult


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]


def test_probe_reports_ready_model(monkeypatch):
    monkeypatch.setattr(
        "aipipe.agents.qwen_readiness.urlrequest.urlopen",
        lambda req, timeout: _Response({"data": [{"id": "qwen-local"}]}),
    )
    result = probe_local_model_endpoint(
        "http://localhost:8080/v1",
        api_key="secret",
        model="qwen-local",
        timeout_seconds=1,
    )
    assert result.ok
    assert result.category == "ready"
    assert result.models == ("qwen-local",)
    assert "secret" not in result.detail


def test_probe_distinguishes_auth_failure(monkeypatch):
    def fail(req, timeout):
        raise urlerror.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO())

    monkeypatch.setattr("aipipe.agents.qwen_readiness.urlrequest.urlopen", fail)
    result = probe_local_model_endpoint("http://localhost:8080/v1", api_key="bad", model="qwen-local")
    assert not result.ok
    assert result.category == "auth_failure"
    assert "401" in result.detail
    assert "bad" not in result.detail


def test_probe_distinguishes_unreachable_endpoint(monkeypatch):
    def fail(req, timeout):
        raise urlerror.URLError("connection refused")

    monkeypatch.setattr("aipipe.agents.qwen_readiness.urlrequest.urlopen", fail)
    result = probe_local_model_endpoint("http://localhost:8080/v1", model="qwen-local")
    assert not result.ok
    assert result.category == "unreachable"
    assert "connection refused" in result.detail


def test_probe_detects_model_mismatch(monkeypatch):
    monkeypatch.setattr(
        "aipipe.agents.qwen_readiness.urlrequest.urlopen",
        lambda req, timeout: _Response({"data": [{"id": "different-model"}]}),
    )
    result = probe_local_model_endpoint("http://localhost:8080/v1", model="qwen-local")
    assert not result.ok
    assert result.category == "model_mismatch"
    assert "qwen-local" in result.detail
    assert "different-model" in result.detail


def test_probe_reports_missing_configuration_without_network_call(monkeypatch):
    called = False

    def should_not_run(req, timeout):
        nonlocal called
        called = True
        raise AssertionError("unexpected network call")

    monkeypatch.setattr("aipipe.agents.qwen_readiness.urlrequest.urlopen", should_not_run)
    result = probe_local_model_endpoint("", model="qwen-local")
    assert not result.ok
    assert result.category == "not_configured"
    assert called is False


def test_qwen_adapter_fails_before_work_when_readiness_probe_fails(monkeypatch):
    monkeypatch.setattr("aipipe.agents.qwen.require_binary", lambda name: None)
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_MODEL", "qwen-local")
    monkeypatch.setattr(
        "aipipe.agents.qwen.probe_local_model_endpoint",
        lambda *args, **kwargs: LocalModelReadiness(False, "unreachable", "Local model endpoint is unreachable: refused"),
    )

    with pytest.raises(QwenReadinessError, match="unreachable"):
        QwenAdapter({})


def test_cli_parser_accepts_qwen_agent_override():
    args = build_parser().parse_args(["--agent", "qwen", "doctor"])
    assert args.agent == "qwen"


def test_doctor_reports_qwen_binary_and_local_endpoint(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".ai").mkdir()
    (repo / ".ai" / "config.yml").write_text("agent: qwen\n", encoding="utf-8")
    monkeypatch.setenv("AIPIPE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("AIPIPE_LOCAL_LLM_MODEL", "qwen-local")
    monkeypatch.setattr("aipipe.cli.build_identity", lambda repo: {"version": "test"})
    monkeypatch.setattr("aipipe.cli.require_binary", lambda name: None)
    monkeypatch.setattr(
        "aipipe.cli.run",
        lambda cmd, cwd=None, timeout=1200, **kwargs: CommandResult(cmd, 0, "ok\n", ""),
    )
    monkeypatch.setattr(
        "aipipe.cli.probe_local_model_endpoint",
        lambda *args, **kwargs: LocalModelReadiness(True, "ready", "Local model endpoint is reachable and model 'qwen-local' is available.", ("qwen-local",)),
    )

    report, ok = _doctor(repo, None)

    assert ok
    assert report["agent"] == "qwen"
    checks = report["checks"]
    assert checks["binary:qwen"]["status"] == "ok"
    assert checks["local_model_endpoint"]["status"] == "ok"
    assert "qwen-local" in checks["local_model_endpoint"]["detail"]
