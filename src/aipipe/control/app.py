from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import desc, select

from aipipe.agents import AGENT_MODELS

from .auth import (
    OAUTH_STATE_COOKIE,
    clear_session_cookie,
    current_user,
    exchange_code,
    login_url,
    oauth_state,
    set_session_cookie,
)
from .config import load_settings
from .db import Database
from .github_app import GitHubAppAuth, list_app_installations
from .models import ControlEvent, ControlTask, Project, User, WebhookDelivery
from .schemas import EventOut, IssueOut, IssueTaskCreate, ProjectCreate, ProjectOut, TaskCreate, TaskOut, UserOut
from .security import verify_github_signature
from .service import TERMINAL, add_event


settings = load_settings()
database = Database(settings)


def _startup_checks() -> None:
    if not settings.dev_auth:
        if settings.session_secret == "development-only-change-me" or len(settings.session_secret) < 32:
            raise RuntimeError("AIPIPE_SESSION_SECRET must be a strong random value when dev auth is disabled")
        if not settings.allowed_github_logins:
            raise RuntimeError("Set AIPIPE_ALLOWED_GITHUB_LOGINS for production GitHub login")
    settings.repos_root.mkdir(parents=True, exist_ok=True)
    database.create_all()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _startup_checks()
    yield


app = FastAPI(title="AIpipe Control API", version="1.0.1", lifespan=lifespan)
app.state.settings = settings
app.state.database = database
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Last-Event-ID"],
)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.url.path != "/github/webhook":
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in {x.rstrip("/") for x in settings.cors_origins}:
            return Response("Origin not allowed", status_code=403)
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.1"}


@app.get("/auth/github/login")
def github_login() -> Response:
    if settings.dev_auth:
        return RedirectResponse(settings.web_base_url)
    state_value = oauth_state()
    response = RedirectResponse(login_url(settings, state_value))
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state_value,
        httponly=True,
        secure=settings.web_base_url.startswith("https://"),
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@app.get("/auth/github/callback")
def github_callback(request: Request, code: str, state: str) -> Response:
    expected = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected or not __import__("hmac").compare_digest(expected, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    profile = exchange_code(settings, code)
    if settings.allowed_github_logins and profile.get("login", "").lower() not in settings.allowed_github_logins:
        raise HTTPException(status_code=403, detail="GitHub user is not an allowed AIpipe operator")
    with database.session() as db:
        user = db.scalar(select(User).where(User.github_id == int(profile["id"])))
        if not user:
            user = User(github_id=int(profile["id"]), login=profile["login"], avatar_url=profile.get("avatar_url"))
            db.add(user)
        else:
            user.login = profile["login"]
            user.avatar_url = profile.get("avatar_url")
        db.flush()
        user_id = user.id
    response = RedirectResponse(settings.web_base_url)
    set_session_cookie(response, settings, user_id)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@app.post("/auth/logout")
def logout(_: User = Depends(current_user)) -> Response:
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@app.get("/agents/models")
def agent_model_options(_: User = Depends(current_user)):
    return {
        name: [{"id": m.id, "label": m.label} for m in models]
        for name, models in AGENT_MODELS.items()
    }


@app.get("/projects", response_model=list[ProjectOut])
def list_projects(_: User = Depends(current_user)):
    with database.session() as db:
        return list(db.scalars(select(Project).order_by(Project.created_at.desc())).all())


@app.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, _: User = Depends(current_user)):
    if payload.local_path:
        path = __import__("pathlib").Path(payload.local_path).expanduser().resolve()
        if not path.exists():
            raise HTTPException(400, "local_path does not exist")
    if payload.installation_id and payload.repository_full_name:
        try:
            repos = GitHubAppAuth(settings, payload.installation_id).repositories()
            match = next((r for r in repos if r.get("full_name") == payload.repository_full_name), None)
            if not match:
                raise HTTPException(403, "GitHub App installation cannot access this repository")
            payload.default_branch = match.get("default_branch") or payload.default_branch
            payload.repository_url = match.get("clone_url") or payload.repository_url
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Could not validate GitHub App installation: {exc}")
    project = Project(**payload.model_dump())
    with database.session() as db:
        db.add(project)
        db.flush()
        db.expunge(project)
    return project


@app.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, _: User = Depends(current_user)):
    with database.session() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        db.expunge(project)
        return project


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, _: User = Depends(current_user)):
    with database.session() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        active = db.scalar(select(ControlTask).where(ControlTask.project_id == project_id, ControlTask.status.notin_(TERMINAL)).limit(1))
        if active:
            raise HTTPException(409, "Project has an active task")
        db.delete(project)
    return Response(status_code=204)


@app.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_project_tasks(project_id: str, _: User = Depends(current_user)):
    with database.session() as db:
        return list(db.scalars(select(ControlTask).where(ControlTask.project_id == project_id).order_by(ControlTask.created_at.desc()).limit(100)).all())


@app.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=202)
def create_prompt_task(project_id: str, payload: TaskCreate, _: User = Depends(current_user)):
    with database.session() as db:
        project = db.get(Project, project_id)
        if not project or not project.enabled:
            raise HTTPException(404, "Project not found or disabled")
        task = ControlTask(project_id=project_id, source="prompt", title=payload.prompt[:120], prompt=payload.prompt)
        db.add(task)
        db.flush()
        add_event(db, task.id, "QUEUED", "Prompt task queued")
        db.expunge(task)
        return task


@app.post("/projects/{project_id}/issue-tasks", response_model=TaskOut, status_code=202)
def create_issue_task(project_id: str, payload: IssueTaskCreate, _: User = Depends(current_user)):
    with database.session() as db:
        project = db.get(Project, project_id)
        if not project or not project.enabled:
            raise HTTPException(404, "Project not found or disabled")
        if not project.repository_full_name:
            raise HTTPException(400, "GitHub issues require a GitHub repository")
        task = ControlTask(
            project_id=project_id,
            source="github_issue",
            source_reference=str(payload.issue_number),
            title=f"GitHub Issue #{payload.issue_number}",
            prompt=f"Implement GitHub Issue #{payload.issue_number}",
        )
        db.add(task)
        db.flush()
        add_event(db, task.id, "QUEUED", f"Issue #{payload.issue_number} queued")
        db.expunge(task)
        return task


@app.get("/projects/{project_id}/issues", response_model=list[IssueOut])
def project_issues(project_id: str, _: User = Depends(current_user)):
    with database.session() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        full_name = project.repository_full_name
        installation_id = project.installation_id
    if not full_name or not installation_id:
        return []
    try:
        issues = GitHubAppAuth(settings, installation_id).issues(full_name)
    except Exception as exc:
        raise HTTPException(502, f"GitHub issue lookup failed: {exc}")
    return [
        IssueOut(number=i["number"], title=i["title"], state=i["state"], url=i["html_url"], labels=[x["name"] for x in i.get("labels", [])])
        for i in issues
    ]


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, _: User = Depends(current_user)):
    with database.session() as db:
        task = db.get(ControlTask, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        db.expunge(task)
        return task


@app.get("/tasks/{task_id}/events", response_model=list[EventOut])
def task_events(task_id: str, _: User = Depends(current_user)):
    with database.session() as db:
        return list(db.scalars(select(ControlEvent).where(ControlEvent.task_id == task_id).order_by(ControlEvent.id)).all())


@app.get("/tasks/{task_id}/stream")
async def task_stream(task_id: str, request: Request, _: User = Depends(current_user)):
    last = request.headers.get("last-event-id") or request.query_params.get("after") or "0"
    try:
        last_id = int(last)
    except ValueError:
        last_id = 0

    async def events():
        nonlocal last_id
        idle = 0
        while True:
            with database.session() as db:
                task = db.get(ControlTask, task_id)
                if not task:
                    yield "event: error\ndata: {\"detail\":\"Task not found\"}\n\n"
                    return
                rows = list(db.scalars(select(ControlEvent).where(ControlEvent.task_id == task_id, ControlEvent.id > last_id).order_by(ControlEvent.id)).all())
                terminal = task.status in TERMINAL
            if rows:
                idle = 0
                for event in rows:
                    last_id = event.id
                    payload = json.dumps({"id": event.id, "kind": event.kind, "detail": event.detail, "created_at": event.created_at.isoformat()}, ensure_ascii=False)
                    yield f"id: {event.id}\nevent: task\ndata: {payload}\n\n"
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": heartbeat\n\n"
            if terminal and not rows:
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/github/installations")
def github_installations(_: User = Depends(current_user)):
    try:
        installations = list_app_installations(settings)
        return [
            {
                "id": item["id"],
                "account": (item.get("account") or {}).get("login") or (item.get("account") or {}).get("name") or str(item["id"]),
                "target_type": item.get("target_type"),
            }
            for item in installations
        ]
    except Exception as exc:
        raise HTTPException(502, f"GitHub App installation lookup failed: {exc}")


@app.get("/github/installations/{installation_id}/repositories")
def installation_repositories(installation_id: int, _: User = Depends(current_user)):
    try:
        repos = GitHubAppAuth(settings, installation_id).repositories()
        return [{"id": r["id"], "name": r["name"], "full_name": r["full_name"], "private": r["private"], "default_branch": r.get("default_branch", "main")} for r in repos]
    except Exception as exc:
        raise HTTPException(502, f"GitHub App request failed: {exc}")


@app.post("/github/webhook", status_code=202)
async def github_webhook(request: Request):
    body = await request.body()
    if not settings.github_webhook_secret:
        raise HTTPException(503, "Webhook secret is not configured")
    if not verify_github_signature(settings.github_webhook_secret, body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Invalid webhook signature")
    event_name = request.headers.get("x-github-event", "unknown")
    delivery_id = request.headers.get("x-github-delivery", "unknown")
    payload = json.loads(body or b"{}")
    installation_id = (payload.get("installation") or {}).get("id")
    repo_name = (payload.get("repository") or {}).get("full_name")
    with database.session() as db:
        if not db.scalar(select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)):
            db.add(WebhookDelivery(
                delivery_id=delivery_id,
                event=event_name,
                installation_id=installation_id,
                repository_full_name=repo_name,
                payload=body.decode("utf-8", "replace")[:100000],
            ))
        if repo_name:
            project = db.scalar(select(Project).where(Project.repository_full_name == repo_name))
            if project:
                check_prs = (payload.get("check_suite") or {}).get("pull_requests") or []
                check_pr_number = check_prs[0].get("number") if check_prs else None
                pr_number = (payload.get("pull_request") or {}).get("number") or check_pr_number
                if pr_number:
                    task = db.scalar(select(ControlTask).where(ControlTask.project_id == project.id, ControlTask.pr_number == int(pr_number)).order_by(ControlTask.created_at.desc()))
                    if task:
                        add_event(db, task.id, f"github:{event_name}", json.dumps({"action": payload.get("action"), "delivery": delivery_id})[:4000])
    return {"accepted": True}


@app.get("/settings")
def public_settings(_: User = Depends(current_user)):
    return {
        "dev_auth": settings.dev_auth,
        "github_app_configured": bool(settings.github_app_id and settings.github_app_private_key),
        "github_login_configured": bool(settings.github_app_client_id and settings.github_app_client_secret),
        "database": "postgresql" if settings.database_url.startswith("postgresql") else "sqlite",
    }


def main() -> None:
    import uvicorn
    uvicorn.run("aipipe.control.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
