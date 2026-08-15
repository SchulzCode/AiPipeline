# AIpipe Control Center v1.0 Architecture

## Design rule

The control center is not the engineering agent. It submits intent and displays state. The Python orchestrator owns workflow and deterministic policy; Codex/Claude own only the software reasoning assigned to an agent run.

## Components

### Web (`web/`)

Next.js App Router UI. It contains no Git, merge, or agent-execution logic. It calls FastAPI with cookie credentials and subscribes to per-task SSE streams. See `docs/DESIGN_SYSTEM.md` for the visual/interaction design system (tokens, status semantics, motion policy) established alongside these views.

Views in v1.1 (issue #21 overhaul):

- **Overview** (`/`) — cross-project operations dashboard: "Happening now" (active tasks across all projects), "Needs attention" (blocked/failed/needs-input tasks), stat tiles, and a searchable/filterable/sortable project grid. Replaces the v1.0 flat project list.
- **Add project** (`/projects/new`).
- **Project workspace** (`/projects/[id]`) — project identity, an "Active now" banner when a task is running, the prompt-task form, feature discovery launch action, a filterable/searchable task list, and open GitHub issues with a "Run with AIpipe" action.
- **Project settings** (`/projects/[id]/settings`) — typed, validated UI over the project's `.ai/config.yml` (agent/model, branch, merge behavior, planner policy, retry budgets, timeouts, discovery limits, setup/quality/security commands). Backed by `GET`/`PATCH /projects/{id}/config` and, for the agent/model fields specifically, `PATCH /projects/{id}` (see below). Never exposes secrets.
- **Task detail** (`/tasks/[id]`) — the pipeline lifecycle visualization (Routing → ... → Done, with completed/current/pending/skipped/failed states), current-activity card, blocker banner, checks/review/security/CI summary, human-readable activity timeline, and an expandable raw-events technical panel. Discovery-sourced tasks render the discovery-specific panel (ranked candidates, duplicates, created issues, handoff tasks) in place of the pipeline visualization, unchanged from v1.0.
- **Tasks** (`/tasks`) — global cross-project task list with status/source/text filtering, backed by the new `GET /tasks` endpoint.
- **Diagnostics** (`/diagnostics`) — system health (project/task counts by status, inferred active-worker count, GitHub App/login configuration presence, database backend), replacing the v1.0 raw-JSON settings page. Backed by `GET /system/health`.

### Control API (`src/aipipe/control/app.py`)

FastAPI owns authentication, project/task CRUD, SSE, GitHub App discovery, and webhook ingestion. Long-running engineering work is never performed inside an HTTP request.

Additive endpoints for the v1.1 UI overhaul (issue #21), all read-through the existing `ControlTask`/`Project` tables — no new tables:

- `GET /tasks` — cross-project task listing (`status`/`project_id`/`source` filters, bounded `limit`) for the Overview and Tasks views. Enriches `TaskOut` with `project_name`/`project_agent`/`project_model` to avoid N+1 calls from the frontend.
- `GET /system/health` — aggregated project/task counts by status, and an `active_workers` count inferred from distinct `claimed_by` values on non-terminal tasks with a heartbeat newer than `worker_stale_seconds`. This is inference from existing task state, not a real worker/process registry — the UI must present it as such.
- `GET`/`PATCH /projects/{id}/config` — typed read/write of the project's `.ai/config.yml`, via `src/aipipe/control/project_config.py`. For `local_path` projects this reads/writes the file directly; for GitHub-backed projects it uses the GitHub Contents API (`GitHubAppAuth.get_contents`/`put_contents` in `github_app.py`) and **commits directly to the project's default branch — no PR, no review gate** (this is operational pipeline config, not agent-generated code, so it intentionally bypasses the code-change gates). Patches merge into the existing raw YAML document (unknown keys and other top-level sections are preserved; YAML comments are not, since `yaml.safe_dump` doesn't round-trip them). `aipipe.config.PipelineConfig` is reused as the source of truth via two new pure functions, `merge_config_layers`/`config_from_merged`, extracted from `load_config` — the control plane never forks the config schema.
- `PATCH /projects/{id}` — updates a project's `agent`/`model`/`name`/`enabled`. Exists separately from the config endpoint above because `Project.agent`/`Project.model` (the control-plane DB columns the executor actually reads, see `executor.py`) are distinct from the `agent` field inside `.ai/config.yml` (which only matters for the standalone CLI/core flow, not control-plane task execution) — exposing the YAML field as editable in the per-project settings UI would silently do nothing.

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

### Feature-discovery workflow (`src/aipipe/discovery.py`, `Orchestrator.run_discovery`)

A separate, bounded workflow — not a phase of the state machine above — driven by
`Orchestrator.run_discovery()` through its own `DISCOVERING → DONE/BLOCKED/FAILED`
lifecycle (`TaskStatus.DISCOVERING`, a distinct value from the pre-existing
no-op `DISCOVERY` phase in `run()`). It:

1. runs a single read-only `DISCOVERY_AGENT` role (sandboxed via
   `agents.base.READ_ONLY_ROLES`, enforced with the same diff-hash tripwire as
   PLANNER/REVIEWER) that explores the repository and returns a
   `{"candidates":[...]}` JSON envelope — never a code change;
2. normalizes, scores and ranks candidates deterministically in
   `discovery.py` (no LLM call for scoring/ranking/dedup — see D-004);
3. deduplicates against existing GitHub issues/PRs, first by an exact
   `<!-- aipipe-discovery:{key} -->` marker match, then by title/body
   similarity (`difflib.SequenceMatcher`);
4. files the remaining candidates (bounded by `discovery.max_new_issues`) as
   structured, implementation-ready GitHub issues via
   `GitHubAdapter.create_issue` (idempotent on the marker, so a retried or
   re-run discovery task never double-files an issue);
5. computes an optional, bounded handoff selection (bounded by
   `discovery.max_auto_implement`, filtered by `discovery.max_risk` /
   `discovery.max_context_class`) and returns the eligible GitHub issue
   numbers — it never implements anything itself or calls `run()`/enters the
   normal pipeline directly.

`discovery.max_auto_implement` defaults to `0`, so by default discovery only
proposes and files issues; nothing is auto-implemented until a project
explicitly raises the limit. A generated `DISCOVERY_CANDIDATES` event is
recorded before any GitHub call, so a partial GitHub failure (a duplicate
lookup or one failed `create_issue` among several) never loses the generated
proposals — the task is recoverable from that event, and remaining
candidates are still processed. The workflow never commits, pushes, opens a
PR, or merges, so it can always finish successfully (`DONE`) without
modifying repository code, and there is no discovery-triggers-discovery loop
or scheduler.

At the control-plane layer, a discovery `ControlTask` (`source="discovery"`)
never calls `Orchestrator.run()` for its handoff candidates; instead
`TaskExecutor.execute()` enqueues each eligible issue as an ordinary
`QUEUED` `github_issue` `ControlTask` (linked back via `discovery_task_id`)
for a worker to claim later through the normal claim/heartbeat loop. This
keeps handoff subject to every existing quality/security/review/CI/merge
gate — discovery can propose and queue work, never bypass how it gets
implemented.

### Agent adapters

`CodexAdapter` and `ClaudeAdapter` implement the same logical role interface. Agent selection is per project and can be overridden by CLI. Each adapter also exposes its own `MODELS` list (a Default/Automatic option plus the concrete models it supports); a project may pin one of those, stored alongside its agent choice and forwarded to the adapter's `model` config key. Leaving it unset preserves the adapter's own default behavior.

Roles used by v1.0:

- PLANNER (DEEP context, or another configured `planning.context_classes` threshold; read-only)
- IMPLEMENTER
- REVIEWER (MEDIUM/HIGH)
- SECURITY_REVIEWER (HIGH)
- DISCOVERY_AGENT (read-only; runs only inside the feature-discovery workflow, never during a normal task)

Routing is deterministic to avoid a dedicated LLM call. Durable project knowledge is updated by the implementer only when relevant, so there is no always-on knowledge-agent run.

The Planner is conditional on `context_class`, not `risk` — the two stay independent: an architecturally complex but low-risk task can still get a plan, while a high-risk small change can require security review without one. It runs once, during `PLANNING`, in the same read-only sandbox as REVIEWER/SECURITY_REVIEWER (`agents/base.py:READ_ONLY_ROLES`) and is bounded by `retries.planner` (default 2) with no code-mutation retry loop — a failed Planner run blocks the task (`PLANNING_FAILURE`) rather than silently skipping planning. Its output is stored as a `PLAN` event and threaded into the Implementer's context under an `# Implementation Plan` section.

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
