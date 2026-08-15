# Project

## Purpose
AIpipe: an autonomous, agent-agnostic software engineering pipeline. A Python
core (`src/aipipe`) routes a task, runs an implementer/reviewer agent
(Claude or Codex) in an isolated Git worktree, enforces deterministic
quality/security/CI gates, and guards merge. A FastAPI control plane +
Next.js web UI (`src/aipipe/control`, `web/`) wrap the core for multi-project,
multi-user use with GitHub App auth and webhook ingestion.

## Stack
- Python 3.11+ core (`src/aipipe`): stdlib + PyYAML only, no framework.
- Optional `server`/`dev` extras add FastAPI, SQLAlchemy 2.x, httpx, PyJWT,
  itsdangerous for the control plane (`src/aipipe/control`).
- Next.js 16 / React 19 / Tailwind 4 frontend in `web/` (App Router, no
  separate test runner — verified via `next build` + `eslint`).
- SQLite by default for both the core `StateStore` (raw `sqlite3`) and the
  control-plane `Database` (SQLAlchemy); Postgres supported via
  `DATABASE_URL` for the control plane only.

## Architecture
- `orchestrator.py` is the single state machine driving a task through
  ROUTING → PREPARING → ... → DONE (see `docs/ARCHITECTURE.md`); each phase
  gate (local quality/security, semantic review, CI) is a helper method
  rather than a nested branch inside `run()`.
- `agents/` holds one adapter per coding-agent CLI (`claude.py`, `codex.py`)
  behind the `AgentAdapter` protocol in `agents/base.py`; shared
  CLI-invocation glue (auth-env collection, output truncation) lives in
  `agents/base.py` — see `.ai/DECISIONS.md` D-002. Per-adapter `MODELS` is
  the one source of truth for available models, looked up via
  `agents.agent_models()`.
- `quality.py` / `security.py` / `setup_engine.py` each own command
  *selection* (autodetection or `.ai/config.yml` overrides) but share one
  command *execution* primitive, `util.execute_commands()` — see
  `.ai/DECISIONS.md` D-001.
- `control/` is a thin FastAPI + SQLAlchemy wrapper: `app.py` (HTTP routes),
  `worker.py`/`executor.py` (claims a `ControlTask` and drives an
  `Orchestrator` against it), `service.py` (mirrors core pipeline
  observations into control-plane rows/events), `activity.py` (turns raw
  events into the human-readable task-page feed).
- `web/` is presentation-only: no Git/merge/agent logic, talks to the
  control API over cookies + SSE (`/tasks/{id}/stream`).

## Testing and Build
- `python -m pytest` (pytest + pytest-cov, `pythonpath=src`, `testpaths=tests`).
- `web/`: `npm run lint` (eslint) and `npm run build` (`next build`, which
  also runs the TypeScript compiler); no separate frontend test suite exists.
- GitHub Actions CI is present and is the pipeline's own required-CI gate for
  its self-merged tasks.

## Constraints
- No Alembic/migration tooling for either database. Both `StateStore`
  (`state.py`) and the control-plane `Database` (`control/db.py`) grow
  schemas via small hand-written `ALTER TABLE ... ADD COLUMN` migrations run
  at startup; new columns must be nullable/defaulted so old rows stay valid.
- Subprocesses (agent CLIs, quality/security/setup commands, `git`, `gh`) run
  with an allowlisted environment (`util.safe_process_env`), not the full
  control-plane environment, so control-plane secrets are never inherited by
  untrusted repository code.
