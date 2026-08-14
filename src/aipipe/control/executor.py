from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from aipipe.orchestrator import Orchestrator, PipelineBlocked
from aipipe.util import run, safe_process_env

from .config import ControlSettings
from .db import Database
from .github_app import GitHubAppAuth
from .models import ControlTask, Project
from .service import add_event, apply_core_observation


class TaskExecutor:
    def __init__(self, database: Database, settings: ControlSettings):
        self.database = database
        self.settings = settings

    def _auth(self, project: Project) -> GitHubAppAuth | None:
        if project.installation_id:
            return GitHubAppAuth(self.settings, project.installation_id)
        return None

    def _ensure_repo(self, project: Project, auth: GitHubAppAuth | None) -> Path:
        if project.local_path:
            repo = Path(project.local_path).expanduser().resolve()
            if not (repo / ".git").exists():
                raise RuntimeError(f"Local project is not a Git repository: {repo}")
            return repo
        if not project.repository_url:
            raise RuntimeError("Project has no repository source")
        repo = self.settings.repos_root / project.id / "repository"
        repo.parent.mkdir(parents=True, exist_ok=True)
        env = auth.env() if auth else None
        if not repo.exists():
            result = run(["git", "clone", "--origin", "origin", project.repository_url, str(repo)], timeout=1200, env=safe_process_env(env) if env else None, inherit_env=not bool(env))
            if not result.ok:
                raise RuntimeError(f"Failed to clone repository: {result.stderr}")
        else:
            result = run(["git", "fetch", "origin", "--prune"], repo, timeout=1200, env=safe_process_env(env) if env else None, inherit_env=not bool(env))
            if not result.ok:
                raise RuntimeError(f"Failed to update repository: {result.stderr}")
        return repo

    def execute(self, control_task_id: str) -> None:
        with self.database.session() as db:
            task = db.get(ControlTask, control_task_id)
            if not task:
                raise KeyError(control_task_id)
            project = db.get(Project, task.project_id)
            if not project:
                raise RuntimeError("Task project no longer exists")
            task.started_at = task.started_at or datetime.now(timezone.utc)
            task.status = "PREPARING"
            project.status = "BUSY"
            db.flush()
            project_id = project.id
            project_agent = project.agent
            source = task.source
            source_ref = task.source_reference
            prompt = task.prompt
            # detach values before session closes
            project_copy = Project(
                id=project.id,
                name=project.name,
                repository_full_name=project.repository_full_name,
                repository_url=project.repository_url,
                local_path=project.local_path,
                installation_id=project.installation_id,
                default_branch=project.default_branch,
                agent=project.agent,
            )

        auth = self._auth(project_copy)
        repo = self._ensure_repo(project_copy, auth)
        observer = apply_core_observation(self.database, control_task_id)
        env_provider = auth.env if auth else None
        previous_home = os.environ.get("AIPIPE_HOME")
        task_home = self.settings.repos_root / project_id / ".aipipe-home"
        task_home.mkdir(parents=True, exist_ok=True)
        os.environ["AIPIPE_HOME"] = str(task_home)
        try:
            orch = Orchestrator(repo, agent_override=project_agent, state_observer=observer, github_env_provider=env_provider)
            if source == "github_issue":
                core_id, labels = orch.enqueue_issue_task(int(source_ref or "0"))
            else:
                core_id = orch.enqueue_prompt_task(prompt)
                labels = None
            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if task:
                    task.core_task_id = core_id
                    add_event(db, control_task_id, "CORE_TASK_CREATED", core_id)
            orch.run(core_id, labels=labels)
        except PipelineBlocked as exc:
            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if task:
                    task.status = "BLOCKED"
                    task.error = str(exc)
                    task.completed_at = datetime.now(timezone.utc)
                    add_event(db, control_task_id, "BLOCKED", str(exc))
            raise
        except Exception as exc:
            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if task:
                    task.status = "FAILED"
                    task.error = str(exc)
                    task.completed_at = datetime.now(timezone.utc)
                    add_event(db, control_task_id, "FAILED", str(exc))
            raise
        finally:
            if previous_home is None:
                os.environ.pop("AIPIPE_HOME", None)
            else:
                os.environ["AIPIPE_HOME"] = previous_home
            with self.database.session() as db:
                project = db.get(Project, project_id)
                if project:
                    project.status = "IDLE"
                task = db.get(ControlTask, control_task_id)
                if task:
                    task.claimed_by = None
                    task.heartbeat_at = None
