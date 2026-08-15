from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from aipipe.models import FailureCategory
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
            result = run(
                ["git", "clone", "--origin", "origin", project.repository_url, str(repo)],
                timeout=1200,
                env=safe_process_env(env) if env else None,
                inherit_env=not bool(env),
            )
            if not result.ok:
                raise RuntimeError(f"Failed to clone repository: {result.stderr}")
        else:
            result = run(
                ["git", "fetch", "origin", "--prune"],
                repo,
                timeout=1200,
                env=safe_process_env(env) if env else None,
                inherit_env=not bool(env),
            )
            if not result.ok:
                raise RuntimeError(f"Failed to update repository: {result.stderr}")
        return repo

    def execute(self, control_task_id: str) -> None:
        project_id: str | None = None
        previous_home = os.environ.get("AIPIPE_HOME")

        try:
            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if not task:
                    raise KeyError(control_task_id)
                project = db.get(Project, task.project_id)
                if not project:
                    raise RuntimeError("Task project no longer exists")

                if task.core_task_id:
                    raise PipelineBlocked(
                        f"Control task is already linked to {task.core_task_id}; refusing to create a duplicate core task.",
                        FailureCategory.STATE_INCONSISTENCY,
                    )

                task.started_at = task.started_at or datetime.now(timezone.utc)
                task.status = "PREPARING"
                task.error = None
                task.failure_category = None
                project.status = "BUSY"
                db.flush()

                project_id = project.id
                project_agent = project.agent
                project_model = project.model
                source = task.source
                source_ref = task.source_reference
                prompt = task.prompt

                # Detach only the values needed after this transaction closes.
                project_copy = Project(
                    id=project.id,
                    name=project.name,
                    repository_full_name=project.repository_full_name,
                    repository_url=project.repository_url,
                    local_path=project.local_path,
                    installation_id=project.installation_id,
                    default_branch=project.default_branch,
                    agent=project.agent,
                    model=project.model,
                )

            auth = self._auth(project_copy)
            repo = self._ensure_repo(project_copy, auth)
            observer = apply_core_observation(self.database, control_task_id)
            env_provider = auth.env if auth else None
            task_home = self.settings.repos_root / project_id / ".aipipe-home"
            task_home.mkdir(parents=True, exist_ok=True)
            os.environ["AIPIPE_HOME"] = str(task_home)

            orch = Orchestrator(
                repo,
                agent_override=project_agent,
                model_override=project_model,
                state_observer=observer,
                github_env_provider=env_provider,
            )

            if source == "github_issue":
                core_id, labels = orch.enqueue_issue_task(int(source_ref or "0"))
            elif source == "discovery":
                core_id = orch.enqueue_discovery_task(prompt)
                labels = None
            else:
                core_id = orch.enqueue_prompt_task(prompt)
                labels = None

            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if not task:
                    raise KeyError(control_task_id)
                if task.core_task_id and task.core_task_id != core_id:
                    raise PipelineBlocked(
                        f"Control task was concurrently linked to {task.core_task_id}; refusing to overwrite it with {core_id}.",
                        FailureCategory.STATE_INCONSISTENCY,
                    )
                task.core_task_id = core_id
                add_event(db, control_task_id, "CORE_TASK_CREATED", core_id)

            if source == "discovery":
                # Handoff never runs synchronously here: eligible candidates are
                # enqueued as ordinary QUEUED github_issue ControlTasks for a
                # worker to claim later, so discovery can never bypass the
                # normal Issue -> Task -> PR -> CI -> Merge gates itself.
                result = orch.run_discovery(core_id)
                if result.handoff_issue_numbers:
                    with self.database.session() as db:
                        for issue_number in result.handoff_issue_numbers:
                            handoff = ControlTask(
                                project_id=project_id,
                                source="github_issue",
                                source_reference=str(issue_number),
                                title=f"GitHub Issue #{issue_number}",
                                prompt=f"Implement GitHub Issue #{issue_number}",
                                discovery_task_id=control_task_id,
                            )
                            db.add(handoff)
                            db.flush()
                            add_event(
                                db,
                                handoff.id,
                                "QUEUED",
                                f"Auto-handoff from discovery task {control_task_id}",
                            )
                            add_event(db, control_task_id, "DISCOVERY_HANDOFF_CREATED", handoff.id)
            else:
                orch.run(core_id, labels=labels)

        except PipelineBlocked as exc:
            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if task:
                    task.status = "BLOCKED"
                    task.error = str(exc)
                    task.failure_category = exc.category.value
                    task.completed_at = datetime.now(timezone.utc)
                    add_event(db, control_task_id, "BLOCKED", str(exc))
            raise

        except Exception as exc:
            with self.database.session() as db:
                task = db.get(ControlTask, control_task_id)
                if task:
                    task.status = "FAILED"
                    task.error = str(exc)
                    task.failure_category = FailureCategory.TERMINAL_INTERNAL.value
                    task.completed_at = datetime.now(timezone.utc)
                    add_event(db, control_task_id, "FAILED", str(exc))
            raise

        finally:
            if previous_home is None:
                os.environ.pop("AIPIPE_HOME", None)
            else:
                os.environ["AIPIPE_HOME"] = previous_home

            if project_id is not None:
                with self.database.session() as db:
                    project = db.get(Project, project_id)
                    if project:
                        project.status = "IDLE"
                    task = db.get(ControlTask, control_task_id)
                    if task:
                        task.claimed_by = None
                        task.heartbeat_at = None
