from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from urllib import error as urlerror
from urllib import request as urlrequest


@dataclass(frozen=True)
class LocalModelReadiness:
    ok: bool
    category: str
    detail: str
    models: tuple[str, ...] = ()


class QwenReadinessError(RuntimeError):
    """Raised when the configured local model endpoint is not ready for work."""


def probe_local_model_endpoint(
    base_url: str,
    *,
    api_key: str = "",
    model: str = "",
    timeout_seconds: float = 3.0,
) -> LocalModelReadiness:
    """Perform a bounded OpenAI-compatible `/models` readiness probe.

    The returned detail is intentionally credential-free so it can safely be
    shown in doctor output, task errors, and Control Center diagnostics.
    """
    base_url = base_url.strip()
    if not base_url:
        return LocalModelReadiness(
            False,
            "not_configured",
            "Local model endpoint is not configured; set AIPIPE_LOCAL_LLM_BASE_URL.",
        )

    url = f"{base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urlrequest.Request(url, headers=headers, method="GET")

    try:
        with urlrequest.urlopen(req, timeout=max(0.1, float(timeout_seconds))) as response:
            body = response.read(1024 * 1024)
    except urlerror.HTTPError as exc:
        if exc.code in {401, 403}:
            return LocalModelReadiness(
                False,
                "auth_failure",
                f"Local model endpoint rejected authentication (HTTP {exc.code}).",
            )
        return LocalModelReadiness(
            False,
            "http_error",
            f"Local model endpoint returned HTTP {exc.code} from /models.",
        )
    except (urlerror.URLError, TimeoutError, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return LocalModelReadiness(
            False,
            "unreachable",
            f"Local model endpoint is unreachable: {reason}",
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return LocalModelReadiness(
            False,
            "invalid_response",
            "Local model endpoint /models response is not valid JSON.",
        )

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return LocalModelReadiness(
            False,
            "invalid_response",
            "Local model endpoint /models response does not contain a model list.",
        )

    models = tuple(
        str(item.get("id"))
        for item in data
        if isinstance(item, dict) and item.get("id") is not None
    )
    if model and models and model not in models:
        return LocalModelReadiness(
            False,
            "model_mismatch",
            f"Configured local model '{model}' is not available; endpoint reports: {', '.join(models)}.",
            models,
        )
    if model and not models:
        return LocalModelReadiness(
            False,
            "model_missing",
            f"Configured local model '{model}' could not be verified because the endpoint reports no models.",
            models,
        )

    detail = (
        f"Local model endpoint is reachable and model '{model}' is available."
        if model
        else "Local model endpoint is reachable."
    )
    return LocalModelReadiness(True, "ready", detail, models)
