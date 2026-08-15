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
