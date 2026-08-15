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
