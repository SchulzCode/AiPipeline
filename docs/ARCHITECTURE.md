# AIpipe Control Center v1.0 Architecture

## Design rule

The control center is not the engineering agent. It submits intent and displays state. The Python orchestrator owns workflow and deterministic policy; Codex/Claude own only the software reasoning assigned to an agent run.

## Components

### Web (`web/`)

Next.js App Router UI. It contains no Git, merge, or agent-execution logic. It calls FastAPI with cookie credentials and subscribes to per-task SSE streams.

Views in v1.0:

- project dashboard;
- add project;
- project detail + prompt input;
- open GitHub issues + run action;
- task detail / pipeline timeline / token count;
- non-secret runtime settings.

### Control API (`src/aipipe/control/app.py`)

FastAPI owns authentication, project/task CRUD, SSE, GitHub App discovery, and webhook ingestion. Long-running engineering work is never performed inside an HTTP request.

### Control state

PostgreSQL stores projects, queued/running tasks, task events, operator users, webhook delivery IDs, and denormalized token totals. PostgreSQL row locking with `SKIP LOCKED` allows multiple workers to claim different tasks.

SQLite is retained for local core/CLI task state.

### Worker (`src/aipipe/control/worker.py`)

A worker claims a queued control task and invokes `TaskExecutor`, which prepares the project repository and invokes the normal `Orchestrator`. Multiple worker processes can be deployed against the same PostgreSQL database.

### Core orchestrator (`src/aipipe/orchestrator.py`)

State machine:

```text
QUEUED → ROUTING → PREPARING → DISCOVERY → PLANNING → IMPLEMENTING
       → VERIFYING → REVIEWING → PR_OPEN → CI → MERGING → POST_MERGE → DONE
```

Failure terminals:

```text
BLOCKED / FAILED / CANCELLED / NEEDS_INPUT
```

The core emits observations into the control database; the API exposes them over SSE.

### Agent adapters

`CodexAdapter` and `ClaudeAdapter` implement the same logical role interface. Agent selection is per project and can be overridden by CLI.

Roles used by v1.0:

- IMPLEMENTER
- REVIEWER (MEDIUM/HIGH)
- SECURITY_REVIEWER (HIGH)

Routing is deterministic to avoid a dedicated LLM call. Durable project knowledge is updated by the implementer only when relevant, so there is no always-on knowledge-agent run.

### Context builder

The builder composes a minimal prompt from:

- task/acceptance criteria;
- global agent rules;
- compact project context;
- active decisions/learnings matching task scopes;
- security policy only for relevant risk levels;
- current diff and findings when repairing/reviewing.

It never forwards old chat transcripts between roles.

### Git manager

Each task starts from `origin/<main_branch>` in `ai/<task-id>-<slug>` and gets a separate worktree. Git branch/commit/push/cleanup are orchestrator operations, not agent responsibilities.

### Quality/security engines

Objective checks are shell commands, not LLM questions. Repository commands execute with an allowlisted environment that intentionally strips control-plane secrets.

The built-in secret scan analyzes every added diff line, including untracked files made visible via intent-to-add.

### GitHub integration

A GitHub App installation token is created on demand. The same short-lived token is injected only into Git/`gh` operations that require it. The control API can list installations/repositories and ingest signed webhooks.

The core currently polls GitHub PR checks during an active CI phase; webhooks enrich the audit/live event stream. This keeps v1.0 simple and recoverable even if a webhook is delayed.

### Merge controller

Merge is deterministic and requires the applicable evidence object to be green. It does not accept an LLM override and does not use admin bypass.

## Control plane vs execution plane

```text
CONTROL PLANE                EXECUTION PLANE
Next.js                      Worker
FastAPI                      Git worktrees
PostgreSQL                   Codex / Claude
GitHub OAuth/App             target build/test commands
```

The default Compose topology separates these into services. It is not a per-task microVM boundary; see the threat model for trust assumptions.
