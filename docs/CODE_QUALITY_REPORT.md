# Code Quality & Architecture Pass — Report

This documents a repository-wide code-quality review of AIpipe (complementing
#12's runtime-reliability work). The codebase was reviewed file-by-file
across the orchestrator, control plane (API/executor/worker/DB), Git/GitHub
integration, setup/quality/security engines, agent adapters, and the Next.js
frontend, plus tests and `.ai` project knowledge.

**Overall finding:** the backend had already been through prior hardening
passes (see git history: "End-to-end pipeline hardening and self-healing
execution", "Fix worker heartbeat resilience"). Module boundaries, error
taxonomy (`FailureCategory`), retry/backoff logic and the orchestrator's
stage helpers were already well-factored — most candidate "big" refactors
(splitting `Orchestrator`, generalizing agent capability handling, unifying
task/control state translation) turned out, on inspection, to already be
implemented cleanly and did not need changing. The remaining work was
targeted duplicate-code consolidation, dead-code removal, and one stale
`.ai/PROJECT.md`. No user-visible behavior changes; all 97 backend tests plus
`next build`/`eslint` pass.

## Consolidated code

- **`aipipe.util.execute_commands`** — `SetupEngine.execute`,
  `QualityEngine.execute` and `SecurityEngine.execute_commands` each ran an
  identical "scrub env → run each named shell command → truncate stdout/
  stderr → stop at first failure" loop. Extracted to one shared helper;
  each engine keeps its own command *selection* logic (autodetection,
  `.ai/config.yml` overrides). `setup_engine.py`'s pre-existing 9000-char
  truncation limit (vs. the other two engines' 12000-char default) is now an
  explicit `output_limit` parameter instead of accidental drift.
  See `.ai/DECISIONS.md` D-001.
- **`aipipe.agents.base.collect_env` / `finalize_result`** — `ClaudeAdapter`
  and `CodexAdapter` each independently built an allowlisted auth
  environment from a list of provider env-var names, ran the CLI, appended
  truncated stderr, and truncated the combined output into an
  `AgentResult`, using identical code. That glue now lives once in
  `agents/base.py`; command construction and stdout/token parsing (which
  really do differ — Claude returns one JSON object, Codex streams JSONL
  events) remain in each adapter. See `.ai/DECISIONS.md` D-002.
- **`GitHubAdapter._api_get`** — `_api_check_runs_for_ref` and
  `_api_workflow_runs_for_head` each hand-built an identical `gh api
  --method GET ... -H ... -H ... -f ...` command, ran it, and parsed the
  JSON envelope. Extracted to one `_api_get(path, fields, context,
  error_prefix)` helper; verified byte-for-byte identical command
  construction before/after.
- **Frontend `agentLabel`** — the agent/model display label
  (`"Codex"`/`"Claude" · model`) was implemented once in
  `tasks/[id]/page.tsx` and re-implemented slightly differently (raw
  lowercase agent id, `"Default model"` instead of omitting it) inline in
  `projects/[id]/page.tsx`. Moved to `web/lib/format.ts` and used by both
  pages, so the two project/task views can no longer drift on how they
  describe the same field.

## Simplified code

- `QualityEngine.execute` / `SecurityEngine.execute_commands` /
  `SetupEngine.execute` shrank from ~15-30 lines of loop-and-truncate
  boilerplate each to a single `execute_commands(...)` call.
- `GitHubAdapter._api_check_runs_for_ref` / `_api_workflow_runs_for_head`
  shrank by ~10 lines each; the only per-call-site logic remaining is the
  path/fields/error text, which is the part that's actually
  endpoint-specific.

## Removed dead/stale code

- `control/app.py`: replaced two `__import__("hmac")` /
  `__import__("pathlib").Path` call-site imports with normal top-level
  imports (no behavior change, just non-idiomatic style masking a real
  dependency).
- Unused imports removed (confirmed via `pyflakes`, cross-checked with
  `grep`): `sqlalchemy.desc` and `urllib.parse.quote` and
  `datetime.datetime/timezone` in `control/app.py`; `json` in `state.py`;
  `shutil` in `bootstrap.py`; `fastapi.Depends`, `sqlalchemy.orm.Session`,
  `.config.load_settings` in `control/auth.py`; `os`, `datetime.timezone` in
  `control/github_app.py`. `control/db.py`'s two `from . import models  #
  noqa: F401` side-effect imports are intentional (they register SQLAlchemy
  models on `Base.metadata` before `create_all`/`inspect`) and were left in
  place.
- `agents/codex.py`: removed `raw_events = []` / `raw_events.append(event)`
  — accumulated every parsed JSONL event but the list was never read.
- Stale `.ai/PROJECT.md` placeholder ("To be refined from repository
  evidence...", "Python (pyproject.toml)") replaced with an accurate
  description of the actual stack/architecture (see below) — this isn't
  source code, but it is knowledge every future AIpipe-on-AIpipe task reads
  as context, so leaving it a placeholder was actively misleading.

## Robustness/testability improvements

- Added `tests/test_util.py` covering `execute_commands` directly (ordering,
  fail-fast, truncation, env scrubbing) — this exact behavior previously had
  no direct unit test, only indirect coverage through
  `QualityEngine`/`SecurityEngine`/`SetupEngine`-specific tests.
- Added direct tests for `agents.base.collect_env` and `finalize_result` in
  `tests/test_agents.py` (env forwarding, stderr-append formatting, ok/token
  passthrough) — previously only exercised indirectly through the two
  adapters.
- Verified the `GitHubAdapter._api_get` refactor produces byte-identical `gh
  api` command lists to the pre-refactor code (manual script, plus existing
  `test_github_adapter.py` assertions on command prefixes still pass).
- `.ai/DECISIONS.md` and `.ai/PROJECT.md` updated so future tasks
  (implemented by AIpipe on its own repository) get accurate architecture
  context and understand *why* the two consolidations above exist, instead
  of rediscovering it from scratch or accidentally re-diverging the
  adapters/engines again.

## Performance/token-efficiency improvements

None targeted directly in this pass — no obvious redundant repo
scans/fetches, N+1 queries, or duplicated subprocess work were found in the
reviewed modules. `GitHubAdapter.checks()` already avoids the Checks API
fallback call when `gh pr checks` returns usable data; `SetupEngine`/
`QualityEngine`/`SecurityEngine` already fail-fast on the first broken
command rather than running the rest. The consolidations above are net
negative lines of code, which marginally reduces prompt/diff-review surface
for future tasks touching these files, but that is a readability benefit
more than a runtime one.

## Deferred architectural opportunities (not implemented in this pass)

These were identified but intentionally **not** implemented, because the
benefit is smaller than the review/regression risk, or because it's a
genuinely separate initiative:

1. **Unify the orchestrator's polling loops.** `_wait_for_pr_head`,
   `_wait_for_ci`, and the inline post-merge "wait for MERGED" loop in
   `Orchestrator.run()` share a "compute deadline, poll, sleep, handle
   transient errors" shape but differ enough in what they poll for and how
   they classify failure (`FailureCategory`) that a generic helper would
   need several behavior parameters to stay correct. This is core
   merge-critical control flow that has already been through a hardening
   pass (self-healing execution, PR #15) with the current shape carefully
   tuned; a mechanical "reduce duplication" refactor here has a
   disproportionate regression/review cost for a readability-only gain.
   **Recommendation:** only revisit this together with any future change to
   CI/merge polling semantics, not as a standalone refactor.
2. **Unify `StateStore._ensure_column` (raw `sqlite3`, `state.py`) and
   `Database._ensure_column`/`_column_exists` (SQLAlchemy, `control/db.py`).**
   Both implement the same "add a column if the table exists and doesn't
   already have it, tolerate a concurrent racer" idea, but operate on two
   different database layers (stdlib `sqlite3` for the core `StateStore`,
   SQLAlchemy for the control plane) with no other shared dependency between
   them. A shared abstraction would need a lowest-common-denominator DDL
   interface across two DB APIs — added indirection for two ~15-line
   methods. **Recommendation:** leave as-is; if/when the control plane's
   schema keeps growing, move `control/db.py` to Alembic instead (this is
   already flagged as a known limitation in `.ai/PROJECT.md`/prior
   learnings, not new information from this pass).
3. **`quality.py` formatting.** The file uses an unusual one-argument-per-line
   style inconsistent with the rest of the codebase (visibly different from
   `security.py`/`setup_engine.py`, which this pass also touched). Purely
   cosmetic — reformatting would touch nearly every line in the file for a
   pure style change with no functional or duplication benefit, which the
   guardrails for this pass explicitly discourage ("do not change behavior
   merely to make code look cleaner" / keep diffs reviewable).
   **Recommendation:** reformat opportunistically the next time the file is
   touched for a substantive change, not as a standalone diff.
4. **Frontend test coverage.** `web/` has no component/unit test framework
   (only `eslint` + `next build`/`tsc`). Logic like the pipeline-stage
   progress calculation (`tasks/[id]/page.tsx`'s `currentIndex` memo) and the
   activity-feed rendering only get exercised by TypeScript's structural
   checks, not behavioral tests. **Recommendation:** track as a follow-up
   issue to introduce a lightweight test setup (e.g. Vitest + React Testing
   Library) scoped to the highest-value components, rather than adding a
   test framework as an incidental part of this pass.
5. **GitHub Checks/Actions API pagination.** `_api_workflow_runs_for_head`
   requests a single page (`per_page=100`) of workflow runs; a commit with
   more than 100 associated runs (unusual, but possible with matrix builds
   across many workflows) would silently miss older runs when picking
   `failed_run_logs`. Not fixed here because it changes external-call
   behavior (more `gh api` calls) rather than being a pure consolidation,
   and the practical likelihood is low. **Recommendation:** file as a
   follow-up if CI-log retrieval is ever seen to miss a failing workflow run
   in practice.

## Follow-up issues to file separately

- Introduce Alembic (or an equivalent) for the control-plane database instead
  of the hand-written `_COLUMN_MIGRATIONS` list in `control/db.py`, once
  schema growth outpaces what a short additive-column list can express
  safely (see deferred item 2).
- Add a lightweight frontend test setup for `web/` scoped to
  `tasks/[id]/page.tsx`'s stage-progress and activity-feed logic (see
  deferred item 4).
- Investigate whether `failed_run_logs`/`_api_workflow_runs_for_head` need
  pagination for repositories with unusually high per-commit workflow-run
  counts (see deferred item 5).

## Verification performed

- `python -m pytest` — 97 passed (90 pre-existing + 7 new), 0 failed, 0
  skipped, before and after each change.
- `npm run lint` (eslint) — clean.
- `npx tsc --noEmit` — clean.
- `npm run build` (`next build`, Turbopack) — compiled and generated all
  routes successfully.
- Manual verification that `GitHubAdapter._api_get`-based command
  construction is byte-identical to the pre-refactor inline commands.
