from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bootstrap import initialize_global, initialize_project
from .config import home_dir, load_config
from .orchestrator import Orchestrator, PipelineBlocked
from .state import StateStore
from .util import require_binary, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aipipe", description="Autonomous guarded software engineering pipeline")
    p.add_argument("--repo", default=".", help="Git repository path (default: current directory)")
    p.add_argument("--agent", choices=["codex", "claude"], help="Override configured agent backend")
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("task", help="Run a task prompt through the full pipeline")
    t.add_argument("prompt")
    i = sub.add_parser("issue", help="Implement a GitHub issue by number")
    i.add_argument("number", type=int)
    s = sub.add_parser("status", help="Show pipeline task state")
    s.add_argument("task_id", nargs="?")
    sub.add_parser("init", help="Initialize global and project AIpipe knowledge/config")
    sub.add_parser("doctor", help="Check external prerequisites")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    initialize_global()
    if args.command == "init":
        initialize_project(repo)
        print(f"Initialized AIpipe at {home_dir()} and {repo / '.ai'}")
        return 0
    if args.command == "doctor":
        cfg = load_config(repo)
        backend = args.agent or cfg.agent
        binary = cfg.codex.get("binary", "codex") if backend == "codex" else cfg.claude.get("binary", "claude")
        checks = {}
        for binary in ["git", "gh", binary]:
            try:
                require_binary(binary)
                checks[binary] = "ok"
            except Exception as exc:
                checks[binary] = str(exc)
        if checks.get("gh") == "ok":
            auth = run(["gh", "auth", "status"], repo)
            checks["github_auth"] = "ok" if auth.ok else "failed"
        if backend == "claude" and checks.get(cfg.claude.get("binary", "claude")) == "ok":
            auth = run([cfg.claude.get("binary", "claude"), "auth", "status"], repo)
            checks["claude_auth"] = "ok" if auth.ok else "failed"
        print(json.dumps(checks, indent=2))
        return 0 if all(v == "ok" for v in checks.values()) else 1
    if args.command == "status":
        store = StateStore(home_dir() / "state" / "pipeline.db")
        if args.task_id:
            item = store.task(args.task_id)
            item["usage"] = store.task_usage(args.task_id)
            print(json.dumps(item, indent=2, default=str))
        else:
            print(json.dumps(store.list_tasks(), indent=2, default=str))
        return 0

    try:
        orch = Orchestrator(repo, args.agent)
        if args.command == "task":
            task_id = orch.create_prompt_task(args.prompt)
        else:
            task_id = orch.create_issue_task(args.number)
        print(f"{task_id}: DONE")
        return 0
    except PipelineBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
