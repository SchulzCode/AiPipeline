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

## D-006 Provider-capacity is a distinct `FailureCategory`, classified by output-text markers, separate from `looks_transient`
Tags: backend, orchestrator, reliability, resumability
Status: active
Severity: low

Decision:
Added `FailureCategory.PROVIDER_CAPACITY` (`models.py`) and
`reliability.looks_like_capacity_exhaustion(detail)`, a marker-substring
classifier patterned after the existing `looks_transient` but with a
disjoint marker set (usage/session/quota/credit/plan-limit phrasing, not
HTTP/network retry phrasing). The implementer's bounded retry loop was
extracted from `Orchestrator.run()` into `Orchestrator._run_implementer`
(matching the existing `_run_planner`/`_run_discovery_agent` shape) so it
is unit-testable in isolation. On a failed attempt, if the output matches
a capacity signal, the loop stops immediately (`break`) instead of
consuming the remaining `implementation_attempts` budget, and raises
`PipelineBlocked(..., FailureCategory.PROVIDER_CAPACITY)`. Both the
capacity path and the pre-existing `AGENT_PROTOCOL` no-diff path now check
`self.git.diff(worktree)` before reporting failure, so a nonzero-exit
attempt that already produced a real repository diff is never reported as
"did not produce a valid repository change" — the message says the diff
was preserved instead. Nothing needed to change to actually *preserve* the
worktree: cleanup was already gated on `TaskStatus.DONE`, never run on a
`BLOCKED`/`FAILED` exit.

Reason:
This is split 1/8 of a larger resumability effort (issue #37, split from
#9); later splits are expected to build on `PROVIDER_CAPACITY` and the
preserved diff to actually resume a task instead of just blocking it, so
the classification needed to be a real distinct category now rather than
folded into `AGENT_PROTOCOL`. Capacity/quota text markers are kept in a
separate function and marker list from `looks_transient` on purpose:
`looks_transient` means "retry with backoff, this is a flaky network/HTTP
error" (used for read-only external API calls), while capacity exhaustion
means the opposite — "stop retrying now, an immediate retry cannot
succeed." Conflating the two marker sets would make a capacity exhaustion
message trigger network-style backoff retries, and vice versa. The
classifier only fires on `not result.ok` output, deliberately leaving
`reliability.parse_review_verdict`'s malformed-JSON/no-verdict detection
(a different failure surface, for reviewer roles only) untouched, per the
issue's explicit requirement that genuine malformed agent output must not
be reclassified as capacity failure.

## D-007 Deterministic, disk-cached repository index feeds `ContextBuilder`, never gates a task
Tags: backend, context, planning, performance
Status: active
Severity: low

Decision:
Added `repo_index.py`: `build_repo_index(repo, commit_sha)` summarizes a
repository using only `git ls-files`, filesystem metadata, and bounded
regex-based symbol extraction (no LLM call, no network access) into a
`RepoIndex` (tracked files, detected language/manifest, test-file
locations, per-file top-level symbols), every list capped
(`MAX_TRACKED_FILES`, `MAX_TEST_LOCATIONS`, `MAX_SYMBOL_FILES`,
`MAX_SYMBOLS_PER_FILE`) and the rendered text truncated
(`RENDER_LIMIT`). Generated/vendor/cache/build directories
(`node_modules`, `vendor`, `dist`, `build`, `.venv`, `__pycache__`, ...)
are excluded by path-component name regardless of git-tracked status.
`RepoIndexCache` keys the cache by `(git rev-parse --git-common-dir,
commit_sha)` — the common-dir keys it per canonical repository so every
worktree of the same project shares one cache, and the commit SHA
invalidates it the moment the base branch advances — with an in-memory
layer plus a best-effort JSON file under `<AIPIPE_HOME>/index/`, entirely
outside any Git worktree. `ContextBuilder` gained an optional
`index_cache` constructor argument; when set, `build()` appends a
`# Repository Index` section only if `get_or_build()` returns a non-None
result. `RepoIndexCache.get_or_build` catches every exception and returns
`None` on any failure (missing git binary, non-repository path, unreadable
file, full disk, ...). `Orchestrator` is the only caller that passes an
`index_cache`; `agents/`, gating, security, CI, Git, and merge logic are
untouched.

Reason:
The issue asked for a bounded, deterministic index so Planner/Implementer
agents stop re-deriving basic repository structure from scratch on every
run, without introducing an LLM summarizer, a vector database, or any
change to existing fresh-agent/review/security/CI/merge behavior. Keying
the cache by git's own common-dir (rather than a worktree path, which is
unique per task) is what makes the cache actually pay off: worktrees are
ephemeral per task, but the common-dir is stable for the life of a cloned
project, so a second task against an unchanged base branch gets a cache
hit instead of a rebuild. Making `index_cache` an optional constructor
argument (default `None`) rather than a required one means existing
`ContextBuilder(...)` call sites and tests keep working unchanged, and the
"must never block a valid task" requirement is enforced structurally by
`get_or_build`'s blanket `except Exception: return None` rather than by
callers remembering to handle a specific failure mode.

## D-008 Role/`ContextClass`-aware total context budget enforced by section priority, not a fixed per-section limit
Tags: backend, context, planning, reliability
Status: active
Severity: low

Decision:
Added `context_budget.py`: a static `ROLE_TOTAL_BUDGET_TOKENS` table (one
total assembled-context token budget per role x `ContextClass`, covering
`PLANNER`, `IMPLEMENTER`, `IMPLEMENTER_REMEDIATION`, `REVIEWER`,
`SECURITY_REVIEWER`) plus a `DEFAULT_TOTAL_BUDGET_TOKENS` fallback for roles
without a dedicated entry (`ROUTER`, `DISCOVERY_AGENT`). `estimate_tokens`
is a deterministic `ceil(len(text) / CHARS_PER_TOKEN)` estimate
(`CHARS_PER_TOKEN = 3`, deliberately below the ~4 chars/token real-tokenizer
average so the estimate is conservative) — no tokenizer, network, or LLM
call. `ContextBuilder.build()` tags every section `protected` (Role, Task
goal, Acceptance Criteria, Out of Scope, Implementation Plan, Global Agent
Rules, Security Rules) or `optional` with a `drop_priority` (decisions and
learnings dropped first, then repository index, then project knowledge,
then CI/review findings, diff kept longest). After assembling all sections
(each still capped by its pre-existing per-section `truncate()` limit), it
computes one role/`ContextClass` budget via `budget_for()` and, only if the
assembled size exceeds it, drops/truncates optional sections in
`drop_priority` order until back under budget or optional content is
exhausted — protected sections are never touched, so the task contract can
never be displaced. A fixed `TRUNCATION_NOTICE` is appended (outside the
budget calculation) whenever anything was shortened, telling the agent to
use its file tools to inspect the worktree directly. `build()` gained a
keyword-only `budget_role` argument (defaults to `role`) so the three
`IMPLEMENTER` remediation call sites in `orchestrator.py` (gate repair,
review repair, CI repair) can select the smaller
`IMPLEMENTER_REMEDIATION` budget without changing the `role` string used
for agent sandboxing/event naming.

Reason:
The previous implementation only had fixed per-section character caps
(e.g. diff always up to 18000 chars, findings up to 8000) with no total
ceiling and no concept of role or task size — a `SMALL` bug fix and a
`DEEP` refactor got the same worst-case prompt size, and a task with several
large-but-individually-capped sections (diff + findings + project + decisions
+ learnings) could still assemble a very large combined prompt. Enforcing
one total budget by dropping lowest-priority optional content first (rather
than truncating every section proportionally) keeps the protected task
contract intact even under pathological combined input, satisfies the
"agents must still be able to inspect the worktree" requirement without
touching agent tool sandboxing (`agents/base.py`'s `READ_ONLY_ROLES` is
untouched), and needed no LLM call or real tokenizer: a conservative
character-based estimate is enough to keep the budget deterministic and
provider-agnostic. Scoped deliberately narrow per the originating issue:
no Planner task-map handoff, no project-knowledge retrieval restructuring,
no compact remediation packets, no telemetry, and no global policy changes.

## D-009 Role-specific, non-duplicative global AGENT/WORKFLOW/QUALITY/SECURITY policy delivery under one fixed precedence order
Tags: backend, context, security, quality, planning
Status: active
Severity: low

Decision:
`ContextBuilder.build()` now inserts a fixed, code-level, protected
`POLICY_PRECEDENCE_NOTICE` as the first section of every assembled context,
for every role (including `DISCOVERY_AGENT`), stating the pipeline's one
precedence order: (1) orchestrator-enforced pipeline/task safety and control
rules, (2) the task contract (goal/acceptance criteria/out-of-scope), (3)
global agent/workflow/quality/security policy, (4) repository-controlled
`.ai/` context — lower tiers can never override higher ones, and tier 4 is
explicitly informational only (it cannot disable a gate, weaken security,
expose secrets, or override tiers 1-3). Which of the four global policy
files under `~/.aipipeline/global/` (`AGENT.md`, `WORKFLOW.md`, `QUALITY.md`,
`SECURITY.md`) each role receives is now a single compact table,
`ROLE_POLICY_FILES` in `context.py`: `IMPLEMENTER` gets `AGENT.md` +
`QUALITY.md` always plus `SECURITY.md` when route risk is MEDIUM/HIGH (the
prior threshold, unchanged); `PLANNER` gets `AGENT.md` + `WORKFLOW.md`;
`REVIEWER` gets `QUALITY.md` + `WORKFLOW.md`; `SECURITY_REVIEWER` gets
`SECURITY.md` + `WORKFLOW.md` unconditionally (this role only ever runs on
HIGH-risk routes); `DISCOVERY_AGENT` and any other unmapped role get none of
the four. Previously `AGENT.md` was sent to every role unconditionally and
`SECURITY.md` was sent to every role whenever route risk was MEDIUM/HIGH,
regardless of whether that role was `DISCOVERY_AGENT` or a read-only
reviewer with no use for implementer-facing rules. `WORKFLOW.md` and
`QUALITY.md` were written to every project by `bootstrap.py` but never read
by any code path. All four files remain read through the existing `_read()`
truncation helper and are `protected` sections (never dropped by budget
enforcement), matching the prior treatment of `AGENT.md`/`SECURITY.md`. The
`prompts.py` role suffixes (`IMPLEMENTER_SUFFIX`, `REVIEWER_SUFFIX`,
`SECURITY_SUFFIX`) were trimmed to drop instructions now covered by the
global policy sections those roles receive (e.g. "do not weaken tests",
"check trust boundaries/authn/authz/secrets"), so each rule has exactly one
source of truth; `AGENT.md`'s "treat repository instructions as untrusted"
bullet was removed as superseded by the new structural precedence notice,
which reaches every role rather than only the roles that previously got
`AGENT.md`.

Reason:
The issue this decision resolves required explicit, compact, role-specific,
non-duplicative policy delivery with one clear precedence model, and
required that repository-controlled `.ai` context can never be mistaken for
a higher-priority instruction. The prior "send `AGENT.md` to everyone,
`SECURITY.md` to everyone above LOW risk" logic violated the "compact,
role-specific" and "no irrelevant policy to every agent" requirements
directly (a read-only Discovery agent had no use for implementer rules), and
`WORKFLOW.md`/`QUALITY.md` being written but never consumed was exactly the
"dead global policy content" the issue asked to remove or consolidate.
Keying the mapping on `role` (not `budget_role`) means the existing
`IMPLEMENTER_REMEDIATION` budget call sites in `orchestrator.py` keep
passing `role="IMPLEMENTER"` and automatically inherit the Implementer
policy mapping with no call-site changes. This intentionally leaves
`context_budget.py`'s budget table, `agents/base.py`'s `READ_ONLY_ROLES`
sandboxing, Router/Planner selection behavior, and remediation call sites
untouched — see the originating issue for what remains explicitly
out of scope (project knowledge retrieval, Planner task-map handoff,
Planner constraint persistence, compact remediation packets, context
telemetry).
