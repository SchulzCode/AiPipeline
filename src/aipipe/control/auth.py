from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from .config import ControlSettings
from .db import Database
from .models import User

SESSION_COOKIE = "aipipe_session"
OAUTH_STATE_COOKIE = "aipipe_oauth_state"
SESSION_MAX_AGE = 7 * 24 * 3600


def serializer(settings: ControlSettings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="aipipe-session-v1")


def login_url(settings: ControlSettings, state: str) -> str:
    if not settings.github_app_client_id:
        raise RuntimeError("GITHUB_APP_CLIENT_ID is not configured")
    query = urlencode({"client_id": settings.github_app_client_id, "state": state})
    return f"https://github.com/login/oauth/authorize?{query}"


def exchange_code(settings: ControlSettings, code: str) -> dict:
    if not settings.github_app_client_id or not settings.github_app_client_secret:
        raise RuntimeError("GitHub App client credentials are not configured")
    with httpx.Client(timeout=20.0) as client:
        token = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_app_client_id,
                "client_secret": settings.github_app_client_secret,
                "code": code,
            },
        )
        token.raise_for_status()
        data = token.json()
        if "access_token" not in data:
            raise RuntimeError(data.get("error_description") or "GitHub login failed")
        profile = client.get(
            "https://api.github.com/user",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {data['access_token']}"},
        )
        profile.raise_for_status()
        return profile.json()


def set_session_cookie(response: Response, settings: ControlSettings, user_id: str) -> None:
    token = serializer(settings).dumps({"user_id": user_id})
    secure = settings.web_base_url.startswith("https://")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def oauth_state() -> str:
    return secrets.token_urlsafe(32)


def current_user(request: Request) -> User:
    settings: ControlSettings = request.app.state.settings
    database: Database = request.app.state.database
    with database.session() as db:
        if settings.dev_auth:
            user = db.scalar(select(User).where(User.github_id == 0))
            if not user:
                user = User(github_id=0, login="dev-user")
                db.add(user)
                db.flush()
            db.expunge(user)
            return user
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        try:
            payload = serializer(settings).loads(raw, max_age=SESSION_MAX_AGE)
        except (BadSignature, SignatureExpired):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        user = db.get(User, payload.get("user_id"))
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
        db.expunge(user)
        return user
