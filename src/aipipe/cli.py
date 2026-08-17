from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agents.qwen_readiness import probe_local_model_endpoint
from .bootstrap import initialize_global, initialize_project
from .config import home_dir, load_config
from .local_canary import run_local_qwen_canary
from .orchestrator import Orchestrator, PipelineBlocked
from .reliability import build_identity
from .state import StateStore
from .util import require_binary, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aipipe", description="Autonomous guarded software engineering pipeline")
    p.add_argument("--repo", default=".", help="Git repository path (default: current directory)")
    p.add_argument("--agent", choices=["codex", "claude", "qwen"], help="Override configured agent backend")
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("task", help="Run a task prompt through the full pipeline")
    t.add_argument("prompt")
    i = sub.add_parser("issue", help="Implement a GitHub issue by number")
    i.add_argument("number", type=int)
    sub.add_parser(
        "discover",
        help="Run the read-only feature-discovery workflow and file ranked candidates as GitHub issues",
    )
    s = sub.add_parser("status", help="Show pipeline task state")
    s.add_argument("task_id", nargs="?")
    sub.add_parser("init", help="Initialize global and project AIpipe knowledge/config")
    sub.add_parser("doctor", help="Check execution, repository and integration prerequisites")
    sub.add_parser(
        "local-canary",
        help="Run an opt-in end-to-end canary against the configured local Qwen model server",
    )
    return p


def _doctor(repo: Path, agent_override: str | None) -> tuple[dict, bool]:
    cfg = load_config(repo)
    backend = agent_override or cfg.agent
    if backend == "codex":
        agent_binary = cfg.codex.get("binary", "codex")
    elif backend == "claude":
        agent_binary = cfg.claude.get("binary", "claude")
    elif backend == "qwen":
        agent_binary = cfg.qwen.get("binary", "qwen")
    else:
        raise ValueError(f"Unsupported agent backend: {backend}")

    report: dict[str, object] = {
        "build": build_identity(repo if (repo / ".git").exists() else None),
        "agent": backend,
        "checks": {},
    }
    checks: dict[str, dict[str, str]] = report["checks"]  # type: ignore[assignment]

    def record(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"status": "ok" if ok else "fail", "detail": detail}

    binaries = ["git", "gh", agent_binary]
    for binary in binaries:
        try:
            require_binary(binary)
            record(f"binary:{binary}", True, "available")
        except Exception as exc:
            record(f"binary:{binary}", False, str(exc))

    if backend == "qwen":
        base_url = str(cfg.qwen.get("base_url") or os.environ.get("AIPIPE_LOCAL_LLM_BASE_URL", ""))
        model = str(cfg.qwen.get("model") or os.environ.get("AIPIPE_LOCAL_LLM_MODEL", "qwen-local"))
        readiness = probe_local_model_endpoint(
            base_url,
            api_key=os.environ.get("AIPIPE_LOCAL_LLM_API_KEY", ""),
            model=model,
            timeout_seconds=float(cfg.qwen.get("readiness_timeout_seconds", 3.0)),
        )
        record("local_model_endpoint", readiness.ok, f"{readiness.category}: {readiness.detail}")

    if (repo / ".git").exists():
        top = run(["git", "rev-parse", "--show-toplevel"], repo, timeout=10)
        record("repository", top.ok, top.stdout.strip() if top.ok else (top.stderr or "not a Git repository").strip())

        origin = run(["git", "remote", "get-url", "origin"], repo, timeout=10)
        record("origin", origin.ok and bool(origin.stdout.strip()), origin.stdout.strip() if origin.ok else (origin.stderr or "origin missing").strip())

        main_ref = run(["git", "rev-parse", "--verify", f"origin/{cfg.main_branch}"], repo, timeout=10)
        record(
            "main_ref",
            main_ref.ok,
            f"origin/{cfg.main_branch} -> {main_ref.stdout.strip()}" if main_ref.ok else f"origin/{cfg.main_branch} is missing; run git fetch first",
        )
    else:
        record("repository", False, f"No .git directory at {repo}")

    worktree_root = home_dir() / "worktrees"
    try:
        worktree_root.mkdir(parents=True, exist_ok=True)
        probe = worktree_root / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record("worktree_root", True, str(worktree_root))
    except OSError as exc:
        record("worktree_root", False, str(exc))

    retries_ok = all([
        cfg.implementation_attempts >= 1,
        cfg.verification_attempts >= 0,
        cfg.review_attempts >= 0,
        cfg.ci_attempts >= 0,
        cfg.external_attempts >= 1,
        cfg.ci_timeout_seconds >= 1,
        cfg.ci_registration_grace_seconds >= 0,
    ])
    record("retry_configuration", retries_ok, "bounded retry values are valid" if retries_ok else "one or more retry/timeout values are invalid")

    if checks.get("binary:gh", {}).get("status") == "ok":
        auth = run(["gh", "auth", "status"], repo, timeout=30)
        record("github_auth", auth.ok, "authenticated" if auth.ok else (auth.stderr or auth.stdout or "authentication failed").strip())

    if backend == "claude" and checks.get(f"binary:{agent_binary}", {}).get("status") == "ok":
        auth = run([agent_binary, "auth", "status"], repo, timeout=30)
        record("agent_auth", auth.ok, "authenticated" if auth.ok else (auth.stderr or auth.stdout or "authentication failed").strip())

    ok = all(item["status"] == "ok" for item in checks.values())
    report["status"] = "ok" if ok else "degraded"
    return report, ok


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    initialize_global()
    if args.command == "init":
        initialize_project(repo)
        print(f"Initialized AIpipe at {home_dir()} and {repo / '.ai'}")
        return 0
    if args.command == "doctor":
        report, ok = _doctor(repo, args.agent)
        print(json.dumps(report, indent=2))
        return 0 if ok else 1
    if args.command == "local-canary":
        try:
            result = run_local_qwen_canary()
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.ok else 1
        except Exception as exc:
            print(json.dumps({"ok": False, "detail": str(exc)}, indent=2))
            return 1
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
            print(f"{task_id}: DONE")
        elif args.command == "issue":
            task_id = orch.create_issue_task(args.number)
            print(f"{task_id}: DONE")
        else:
            task_id = orch.enqueue_discovery_task()
            result = orch.run_discovery(task_id)
            print(json.dumps({"task_id": task_id, "status": "DONE", **result.to_dict()}, indent=2))
        return 0
    except PipelineBlocked as exc:
        print(f"BLOCKED [{exc.category.value}]: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
