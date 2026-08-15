# Decisions

<!-- Active decisions only are retrieved by default. -->

## D-001 Consolidate shell-command execution behind `util.execute_commands`
Tags: backend, quality, security, setup, refactor
Status: active
Severity: low

Decision:
`SetupEngine.execute`, `QualityEngine.execute` and `SecurityEngine.execute_commands`
each ran a `dict[str, str]` of named shell commands with identical semantics
(scrubbed env, sequential execution, fail-fast on the first non-zero exit,
stdout/stderr truncation). This is now one shared helper,
`aipipe.util.execute_commands(commands, cwd, timeout, runtime_env, output_limit)`,
used by all three engines. Each engine keeps its own command *selection*
(autodetection, defaults) — only the execution loop moved.

Reason:
Three independent copies of the same fail-fast/truncation loop meant a future
fix (e.g. a truncation bug, an env-scrubbing gap) could easily be applied to
one engine and forgotten in the others. `setup_engine.py`'s copy used a
9000-char truncation limit instead of the other two's implicit 12000-char
default; the shared helper takes that as an explicit `output_limit` parameter
so the difference stays intentional and visible instead of accidental drift.

## D-002 Share Claude/Codex CLI-invocation glue in `agents/base.py`
Tags: backend, agents, refactor
Status: active
Severity: low

Decision:
`ClaudeAdapter.run` and `CodexAdapter.run` each built an allowlisted auth env
from a list of provider-specific keys, ran the CLI, appended truncated
stderr, and truncated the combined output into an `AgentResult` — using
identical code. That glue is now `agents.base.collect_env(keys)` and
`agents.base.finalize_result(result, output, input_tokens, output_tokens)`.
Command construction and stdout/token parsing remain adapter-specific, since
those differ meaningfully between providers (Claude returns one JSON object;
Codex streams JSONL events).

Reason:
Keeps the two adapters from silently drifting on behavior that has nothing to
do with either provider (e.g. the stderr truncation limit), while leaving the
genuinely provider-specific parts untouched. Adding a third adapter only
needs to implement command construction + output parsing, not re-derive the
env/truncation glue.

## D-003 Gate the Planner role on `context_class`, not `risk`
Tags: backend, orchestrator, agents, planning
Status: active
Severity: low

Decision:
A `PLANNER` role runs once during the existing (previously no-op) `PLANNING`
status, only when `router.planner_required(route.context_class, config)` is
true — default: `context_class == DEEP` and `planning.enabled` (default
true); both are configurable per-project via `.ai/config.yml`
(`planning.context_classes`, `planning.enabled`) — see
`docs/CONFIGURATION.md`. It shares the read-only sandbox already used by
REVIEWER/SECURITY_REVIEWER/ROUTER, now centralized as
`agents.base.READ_ONLY_ROLES` instead of being duplicated per-adapter. Its
prompt reuses `ContextBuilder.build()` (no diff/whole-repo dump — the agent
explores the worktree itself with Read/Grep/Glob-only tools) plus a new
`PLANNER_SUFFIX`. Output is bounded by `retries.planner` (default 2, no
code-mutation remediation loop like IMPLEMENTER gets) and, on success, is
both recorded as a `PLAN` event and threaded into the Implementer's prompt
via `ContextBuilder.build(..., plan=...)`. Exhausting the retry budget raises
`PipelineBlocked(FailureCategory.PLANNING_FAILURE)` rather than silently
proceeding without a plan.

Reason:
Risk and complexity are different axes: a high-risk one-line credential
change doesn't need a plan, while a low-risk but architecturally broad
refactor benefits from one. Gating on `context_class` (already computed by
`route_task` but previously unused for anything except display) keeps that
distinction instead of coupling planning to the REVIEWER/SECURITY_REVIEWER
risk gates in `_semantic_gates_after_change`. Blocking (rather than
skipping) on exhausted Planner retries matches how every other gate in the
pipeline treats a bounded-retry failure, so a silently-skipped Planner never
masks a broken agent/CLI as normal operation.

## D-004 Feature discovery: deterministic ranking/dedup, handoff is an ordinary queued task, never a direct implementation
Tags: backend, orchestrator, discovery, github, control-plane
Status: active
Severity: medium

Decision:
The feature-discovery workflow (`discovery.py`, `Orchestrator.run_discovery`,
issue #8) is implemented as a separate lifecycle
(`TaskStatus.DISCOVERING → DONE/BLOCKED/FAILED`) from the normal `run()`
state machine, not a new branch inside it, and `TaskStatus.DISCOVERING` is a
new enum value distinct from the pre-existing no-op `TaskStatus.DISCOVERY`
phase already used by `run()` — the latter is untouched. Three design
choices matter for future maintainers:

1. Candidate scoring, ranking, and duplicate detection are plain
   deterministic Python (`discovery.score_candidate`/`rank_candidates`/
   `detect_duplicates`), not a second LLM call. Only one LLM role runs per
   discovery task (`DISCOVERY_AGENT`, read-only via
   `agents.base.READ_ONLY_ROLES`), and its sole job is proposing candidates,
   never scoring, ranking, deduplicating, or implementing them.
2. Duplicate detection matches first on an exact
   `<!-- aipipe-discovery:{key} -->` marker embedded in the issue body
   (idempotency across repeated discovery runs), then falls back to
   `difflib.SequenceMatcher` title/body similarity — no network/LLM call is
   needed to decide "have we already proposed this."
3. Handoff (`discovery.max_auto_implement`, default `0`) never calls
   `Orchestrator.run()` on itself. At the core layer, `run_discovery` only
   *selects* eligible issue numbers (bounded by
   `max_auto_implement`/`max_risk`/`max_context_class`) and returns them; at
   the control-plane layer, `TaskExecutor.execute()` turns each into an
   ordinary `QUEUED` `github_issue` `ControlTask` (linked back via
   `discovery_task_id`) for a worker to claim later through the existing
   claim/heartbeat loop.

Reason:
Keeping ranking/dedup/scoring deterministic keeps discovery bounded,
inspectable, and unit-testable without mocking an agent CLI, and avoids a
second unbounded LLM cost per run. Marker-based idempotency means a retried
or re-run discovery task can never double-file the same issue. Routing
handoff through the ordinary task queue (rather than an in-process call into
`run()`) means a discovered feature is subject to every existing
quality/security/review/CI/merge gate exactly like a human-filed issue would
be — discovery can propose and queue work, but can never implement it or
bypass how it gets implemented. `max_auto_implement` defaulting to `0` means
a project must opt in before anything is auto-implemented at all.

## D-005 v1.1 UI/UX overhaul: additive-only backend surface, canonical config reuse, unified frontend status model
Tags: frontend, control-plane, config, design-system
Status: active
Severity: medium

Decision:
Issue #21's full Control Center redesign (Overview/Tasks/project
workspace/task detail/project settings/diagnostics — see
`docs/DESIGN_SYSTEM.md` and `docs/ARCHITECTURE.md`) was implemented as a
frontend-heavy change with four small, additive backend endpoints, not an
orchestrator/control-plane rewrite:

1. `GET /tasks` (cross-project listing) and `GET /system/health`
   (diagnostics) are pure read aggregations over the existing
   `ControlTask`/`Project` tables — no new tables, no new columns.
2. `GET`/`PATCH /projects/{id}/config` reuses `aipipe.config.PipelineConfig`
   as the only source of truth for the YAML shape, via two new pure
   functions extracted from `load_config`: `merge_config_layers` (generic
   multi-layer YAML dict merge) and `config_from_merged` (the YAML->dataclass
   mapping, previously inlined in `load_config`). The control plane calls
   these directly instead of re-deriving the mapping, so there is exactly
   one place that knows what `.ai/config.yml`'s shape means.
3. `PATCH /projects/{id}` (agent/model/name/enabled) was added *separately*
   from the config endpoint, because `Project.agent`/`Project.model` (DB
   columns `executor.py` actually reads) are a different thing from the
   `agent` key inside `.ai/config.yml` (only consulted by the standalone
   CLI/core flow). Exposing the YAML field as an editable "agent" setting in
   the control-plane UI would silently do nothing when a task actually runs.
4. `web/lib/status.ts` is a new single mapping from every raw status string
   (project/task/activity-feed/discovery-candidate) to one of six UI tones.
   It replaced four independently-drifting color-tone tables that existed
   across `StatusBadge`, the task page's `TONES`, the discovery panel's
   `STATUS_TONE`, and an inline pipeline-stage tone ladder.

The `PipelineStages` component (`web/components/pipeline-stages.tsx`) only
visualizes phases present in `activity.py`'s existing `PHASE_ORDER` /
activity-feed items, marking a phase "skipped" (not "done") when it never
appeared in the feed but a later phase did. It deliberately does not invent
a UI node for security review (not a `TaskStatus` phase the backend
transitions through) — that stays a labeled tile in the existing Checks &
Review section instead.

Reason:
The issue explicitly required the smallest additive backend surface
sufficient for the UI, and forbade weakening control-plane boundaries or
fabricating progress the backend can't actually attest to. Reusing
`PipelineConfig` via extracted pure functions (rather than a second
hand-rolled YAML<->dict mapper in the control-plane) means the config
endpoint and the core `load_config()` can never silently drift on what a
given YAML key means. Separating project-identity fields (DB) from
pipeline-config fields (YAML) in two different PATCH endpoints reflects a
real, pre-existing split in what the executor actually reads — collapsing
them into one form would have shipped a control that looked functional but
wasn't.
