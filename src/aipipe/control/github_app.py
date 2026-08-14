from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

from .config import ControlSettings


API = "https://api.github.com"


@dataclass
class CachedToken:
    value: str
    expires_at: float


def app_jwt(settings: ControlSettings) -> str:
    if not settings.github_app_private_key:
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY(_FILE) is not configured")
    issuer = settings.github_app_client_id or settings.github_app_id
    if not issuer:
        raise RuntimeError("GITHUB_APP_CLIENT_ID or GITHUB_APP_ID is not configured")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": issuer}
    return jwt.encode(payload, settings.github_app_private_key, algorithm="RS256")


def list_app_installations(settings: ControlSettings) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt(settings)}",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{API}/app/installations", headers=headers, params={"per_page": 100})
        response.raise_for_status()
        return response.json()


class GitHubAppAuth:
    """GitHub App installation authentication with short-lived token caching."""

    def __init__(self, settings: ControlSettings, installation_id: int):
        self.settings = settings
        self.installation_id = installation_id
        self._token: CachedToken | None = None
        self._askpass: Path | None = None

    def _app_jwt(self) -> str:
        return app_jwt(self.settings)

    def token(self, force: bool = False) -> str:
        if not force and self._token and self._token.expires_at - time.time() > 120:
            return self._token.value
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._app_jwt()}",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        with httpx.Client(timeout=30.0) as client:
            r = client.post(f"{API}/app/installations/{self.installation_id}/access_tokens", headers=headers)
            r.raise_for_status()
            data = r.json()
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        self._token = CachedToken(data["token"], expires)
        return data["token"]

    def _askpass_script(self) -> Path:
        if self._askpass and self._askpass.exists():
            return self._askpass
        root = self.settings.repos_root / ".credentials"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"github-askpass-{self.installation_id}.sh"
        path.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
            "  *) printf '%s\\n' \"$AIPIPE_GITHUB_TOKEN\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self._askpass = path
        return path

    def env(self) -> dict[str, str]:
        token = self.token()
        return {
            "GH_TOKEN": token,
            "GITHUB_TOKEN": token,
            "AIPIPE_GITHUB_TOKEN": token,
            "GIT_ASKPASS": str(self._askpass_script()),
            "GIT_TERMINAL_PROMPT": "0",
        }

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self.token()
        headers = dict(kwargs.pop("headers", {}))
        headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
        })
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method, f"{API}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            token = self.token(force=True)
            headers["Authorization"] = f"Bearer {token}"
            with httpx.Client(timeout=30.0) as client:
                response = client.request(method, f"{API}{path}", headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def repositories(self) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self.request("GET", "/installation/repositories", params={"per_page": 100, "page": page}).json().get("repositories", [])
            repositories.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return repositories

    def issues(self, full_name: str) -> list[dict[str, Any]]:
        items = self.request("GET", f"/repos/{full_name}/issues", params={"state": "open", "per_page": 50}).json()
        return [x for x in items if "pull_request" not in x]
