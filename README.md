# AIpipe Control Center v1.0

AIpipe is a self-hosted, agent-agnostic software-engineering control center. You register projects, submit a natural-language task or select a GitHub issue, and the backend drives the existing AIpipe pipeline through implementation, deterministic quality/security gates, independent AI review where required, pull request, GitHub CI, bounded repair loops, and guarded merge to the configured main branch.

The browser is deliberately **only a control plane**. Git, agent execution, quality gates, merge policy, task state, and project knowledge live in the Python pipeline/worker.

## What is included

- **Next.js + TypeScript + Tailwind** control-center UI
- **FastAPI** control API
- **PostgreSQL** multi-project/task/event state for server deployments
- **SSE** live task event stream
- separate **worker execution plane**
- GitHub App installation auth with short-lived installation tokens
- GitHub login for the operator (or dev auth locally)
- GitHub issue browser and one-click issue task creation
- Codex CLI and Claude Code adapters
- per-task Git branch + worktree isolation
- risk/context routing: LOW / MEDIUM / HIGH and SMALL / NORMAL / DEEP
- deterministic tests/build/lint/type-check gates
- added-diff secret scanning + configurable security commands
- independent semantic review for MEDIUM/HIGH tasks
- independent security review for HIGH tasks
- bounded implementation / verification / review / CI repair loops
- PR creation, GitHub Actions status/log inspection, and guarded auto-merge
- repository-versioned `.ai/` project knowledge
- per-run token accounting when the selected agent CLI exposes usage
- CLI mode from the original AIpipe core remains available

## Happy path

```text
Prompt / GitHub Issue
        │
        ▼
  Control Center
        │
        ▼
 PostgreSQL queue
        │
        ▼
      Worker
        │
        ├─ route risk/context
        ├─ create branch/worktree
        ├─ minimal context retrieval
        ├─ Codex / Claude implementation
        ├─ deterministic quality/security gates
        ├─ AI review(s) according to risk
        ├─ commit + push + PR
        ├─ GitHub CI / bounded repair
        └─ deterministic merge policy
                    │
                    ▼
                   main
```

A normal successful task requires no additional user interaction after submission.

## Quick start with Docker Compose

### 1. Copy configuration

```bash
cp .env.example .env
```

For a local UI smoke test you can leave:

```env
AIPIPE_DEV_AUTH=true
```

For real use set `AIPIPE_DEV_AUTH=false`, generate a strong `AIPIPE_SESSION_SECRET`, and set `AIPIPE_ALLOWED_GITHUB_LOGINS` to the GitHub account(s) allowed to operate the control center.

### 2. Configure one agent backend

Codex:

```env
OPENAI_API_KEY=...
```

or Claude Code:

```env
ANTHROPIC_API_KEY=...
```

`CLAUDE_CODE_OAUTH_TOKEN` is also exposed to the worker when you intentionally use that authentication method.

### 3. Configure the GitHub App

For GitHub projects, issue browsing, PR creation, CI inspection, and merge, configure a GitHub App and fill in:

```env
GITHUB_APP_ID=...
GITHUB_APP_CLIENT_ID=...
GITHUB_APP_CLIENT_SECRET=...
GITHUB_APP_PRIVATE_KEY_B64=...
GITHUB_WEBHOOK_SECRET=...
```

See [`docs/GITHUB_APP.md`](docs/GITHUB_APP.md).

### 4. Start

```bash
docker compose up --build
```

Open:

```text
http://localhost:3000
```

API health:

```text
http://localhost:8000/health
```

### 5. Add a project

In **Projects → Add project**:

1. choose a GitHub App installation;
2. choose one of the repositories visible to that installation;
3. choose `Codex` or `Claude Code`;
4. create the project.

For non-container/local development, a server-local repository path can also be registered. In Docker, such a path must be mounted into both API/worker environments to be usable.

### 6. Submit work

Inside a project, either type a task:

```text
Add CSV export for user-owned account data.
```

or choose an open GitHub issue and click **Run with AIpipe**.

The task page shows pipeline state, risk/context classification, PR number, recorded token usage, and a live event timeline.

## Local development

### Python/API/core

```bash
python -m pip install -e '.[dev,server]'
python -m pytest -q
```

Run API:

```bash
AIPIPE_DEV_AUTH=true aipipe-api
```

Run worker:

```bash
AIPIPE_DEV_AUTH=true aipipe-worker
```

### Web

```bash
cd web
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_URL` if the API is not at `http://localhost:8000`.

## CLI remains supported

The control center does not replace the core CLI:

```bash
aipipe --repo /path/to/repo doctor
aipipe --repo /path/to/repo task "Implement feature X"
aipipe --repo /path/to/repo issue 142
```

The CLI uses local SQLite state; the server control plane uses PostgreSQL.

## Control-plane architecture

```text
Browser
  │
  ▼
Next.js
  │ REST + SSE
  ▼
FastAPI ───────── GitHub App / OAuth / Webhooks
  │
  ▼
PostgreSQL
  │
  ▼
Worker
  │
  ▼
AIpipe Core
  ├── Git / worktrees
  ├── Codex adapter
  ├── Claude adapter
  ├── Quality engine
  ├── Security engine
  ├── Review engine
  └── Merge controller
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Security model

The merge decision is deterministic. An LLM cannot waive a failed required check, bypass branch protection, or force a red CI result through the merge gate.

Important properties in v1.0:

- GitHub App installation tokens are short-lived and generated on demand.
- webhook signatures are verified with HMAC SHA-256 before processing.
- production operator access is allowlisted by GitHub login.
- session cookies are HttpOnly; secure cookies are enabled when the configured web URL is HTTPS.
- browser write requests are origin-checked in addition to CORS.
- project/agent subprocesses receive a **scrubbed environment** rather than inheriting PostgreSQL credentials, GitHub App private keys, session secrets, or webhook secrets.
- new untracked files are made visible to pre-commit diff review and secret scanning.
- AIpipe never uses GitHub `--admin` merge bypass.
- workers use bounded retry budgets to prevent runaway agent loops.
- projects are serialized to one active engineering task at a time; worker heartbeats detect crashed/stale workers and fail closed instead of silently duplicating Git/PR side effects.

### Trust boundary

The supplied Docker Compose deployment separates API and worker processes, but the default worker is still a **persistent worker container**, not a per-task microVM. Repository build/test commands execute in that worker execution plane. v1.0 therefore assumes repositories registered in one worker trust domain are trusted baseline repositories.

For hostile/untrusted third-party repositories, use a stronger disposable VM/container runner boundary per task before treating the system as safe for that threat model. See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Token-efficiency rules

AIpipe intentionally avoids a “one agent for every step” architecture:

- the router is deterministic in v1.0;
- LOW-risk tasks do not get an independent reviewer;
- MEDIUM tasks get one semantic review loop;
- HIGH tasks add a security review;
- no old chat transcript is passed to new roles;
- reviewers receive task + relevant constraints + diff, not implementation history;
- project knowledge is retrieved by scope/tag relevance;
- CI and test logs are truncated to the failing evidence before agent repair;
- objective gates use tools rather than LLM judgment;
- durable `.ai/` knowledge is updated by the implementer only when useful, avoiding a separate knowledge-agent call;
- token usage is persisted per agent run and surfaced in the UI.

## Project knowledge

Each repository can carry:

```text
.ai/
├── PROJECT.md
├── DECISIONS.md
├── LEARNINGS.md
└── config.yml
```

`PROJECT.md` is current state, `DECISIONS.md` explains non-obvious architectural decisions, and `LEARNINGS.md` contains only reusable future-facing knowledge. Git/PR history remains the history of what happened.

## Project setup and quality configuration

Before the implementation agent starts, AIpipe performs a deterministic dependency setup step. By default it conservatively recognizes npm projects and Python projects. Python dependencies are installed into a per-task virtual environment outside the worktree; npm dependencies remain project-local. Rust/Go/Maven/Gradle normally resolve dependencies through their build commands, and the worker image must contain the required language toolchain.

For projects with a custom bootstrap, configure it explicitly:

```yaml
setup:
  auto: false
  commands:
    dependencies: ./scripts/bootstrap-ci.sh
```

Setup is required to leave Git-visible project files unchanged; otherwise the task is blocked rather than accidentally committing generated bootstrap output.

Example `.ai/config.yml`:

```yaml
main_branch: main
agent: codex

setup:
  auto: true
  commands: {}

git:
  auto_merge: true
  merge_method: squash

quality:
  commands:
    test: python -m pytest
    lint: ruff check .
    typecheck: mypy src

security:
  commands:
    dependency-audit: pip-audit

retries:
  implementation: 3
  verification: 3
  review: 2
  ci: 2
```

If quality commands are absent, conservative detection exists for Node, Python, Rust, Go, Maven, and Gradle. Production projects should explicitly define their normal checks and security scanners.

## Definition of merge-ready

The merge controller requires all applicable evidence to pass, including:

- a valid implementation change;
- configured/autodetected final quality commands;
- secret scan;
- configured security commands;
- semantic review when required;
- security review when required;
- GitHub CI evidence;
- open and mergeable PR;
- repository protection/rules permitting merge.

No CI checks means no autonomous merge in v1.0.

## Repository layout

```text
src/aipipe/              Python core + CLI
src/aipipe/control/      FastAPI control plane + worker
web/                     Next.js control center
docker/                  API/worker/web images
tests/                   Python tests
docs/                    Architecture, config, GitHub App, threat model
docker-compose.yml       Self-hosted v1 stack
```

## Validation

Run:

```bash
python -m pytest -q
python -m compileall -q src
```

The web build requires npm registry access for its dependencies:

```bash
cd web
npm install
npm run lint
npm run build
```

## Deliberately out of scope for v1.0

- production deployment of the target application;
- Kubernetes/distributed scheduler;
- vector database/embeddings;
- automatic processing of every newly-created issue;
- team/organization RBAC beyond the operator allowlist;
- per-task microVM execution;
- arbitrary untrusted repositories in the default worker trust domain.

Those are extension points, not prerequisites for validating the core autonomous engineering workflow.
