# Changelog

## 1.0.1

### Fixed

- Updated the PostgreSQL 18 Docker volume mount from `/var/lib/postgresql/data` to `/var/lib/postgresql`, matching the PostgreSQL 18+ official image layout and preventing startup failure on fresh Compose deployments.

## 1.0.0

### Control Center

- Next.js/TypeScript/Tailwind multi-project control-center UI.
- FastAPI control API with signed operator sessions and dev-auth mode.
- PostgreSQL project/task/event state and SSE live task streams.
- GitHub App installation/repository discovery, short-lived installation-token auth, issue listing, and signed webhook ingestion.
- Separate worker service with project-level task serialization, heartbeats, and stale-worker failure recovery.
- Docker Compose deployment for PostgreSQL, API, worker, and web.
- Task detail timeline with risk/context, PR state, and token totals.

### Pipeline Core

- Autonomous prompt/GitHub-issue intake to guarded GitHub merge.
- Codex CLI and Claude Code adapters behind the same orchestration interface.
- SQLite local core state with runs, checks, findings, events, and token usage.
- Risk/context router with LOW/MEDIUM/HIGH policies.
- Git worktree isolation and task branches.
- Token-conscious context builder with project decisions/learnings retrieval.
- Deterministic dependency/setup engine with project overrides.
- Deterministic quality gates and added-diff secret scanner.
- Independent semantic review and HIGH-risk security review.
- Bounded implementation/verification/review/CI repair loops.
- PR creation, GitHub CI observation/failure-log extraction, protected merge, and post-merge confirmation.
- Durable project knowledge versioned in `.ai/` without a mandatory extra knowledge-agent call.
- Scrubbed subprocess environments so repository/agent commands do not inherit control-plane secrets.
