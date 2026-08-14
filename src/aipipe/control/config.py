from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ControlSettings:
    database_url: str
    api_base_url: str
    web_base_url: str
    repos_root: Path
    worker_poll_seconds: float
    worker_stale_seconds: float
    github_app_id: str | None
    github_app_client_id: str | None
    github_app_private_key: str | None
    github_app_client_secret: str | None
    github_webhook_secret: str | None
    session_secret: str
    dev_auth: bool
    cors_origins: list[str]
    allowed_github_logins: list[str]


def _read_secret(value: str | None, file_value: str | None, b64_value: str | None = None) -> str | None:
    if value:
        return value.replace("\\n", "\n")
    if b64_value:
        return base64.b64decode(b64_value).decode("utf-8")
    if file_value:
        path = Path(file_value)
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def load_settings() -> ControlSettings:
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./aipipe-control.db")
    repos_root = Path(os.environ.get("AIPIPE_REPOS_ROOT", "./.aipipe-repos")).expanduser().resolve()
    private_key = _read_secret(
        os.environ.get("GITHUB_APP_PRIVATE_KEY"),
        os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE"),
        os.environ.get("GITHUB_APP_PRIVATE_KEY_B64"),
    )
    origins = [x.strip() for x in os.environ.get("AIPIPE_CORS_ORIGINS", "http://localhost:3000").split(",") if x.strip()]
    return ControlSettings(
        database_url=database_url,
        api_base_url=os.environ.get("AIPIPE_API_BASE_URL", "http://localhost:8000"),
        web_base_url=os.environ.get("AIPIPE_WEB_BASE_URL", "http://localhost:3000"),
        repos_root=repos_root,
        worker_poll_seconds=float(os.environ.get("AIPIPE_WORKER_POLL_SECONDS", "2")),
        worker_stale_seconds=float(os.environ.get("AIPIPE_WORKER_STALE_SECONDS", "300")),
        github_app_id=os.environ.get("GITHUB_APP_ID"),
        github_app_client_id=os.environ.get("GITHUB_APP_CLIENT_ID"),
        github_app_private_key=private_key,
        github_app_client_secret=os.environ.get("GITHUB_APP_CLIENT_SECRET"),
        github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET"),
        session_secret=os.environ.get("AIPIPE_SESSION_SECRET", "development-only-change-me"),
        dev_auth=os.environ.get("AIPIPE_DEV_AUTH", "false").lower() in {"1", "true", "yes"},
        cors_origins=origins,
        allowed_github_logins=[x.strip().lower() for x in os.environ.get("AIPIPE_ALLOWED_GITHUB_LOGINS", "").split(",") if x.strip()],
    )
