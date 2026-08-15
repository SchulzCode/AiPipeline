# Project Learnings

<!-- Store only reusable future-facing knowledge. -->

- The control-plane DB (`src/aipipe/control/db.py`) has no Alembic/migration
  tooling; `Database.create_all()` only creates missing tables, not missing
  columns on existing tables. New nullable `Project`/`ControlTask` columns
  follow the existing convention (add the column, default `None`/a safe
  constant) so old rows keep working; there is no automated ALTER TABLE path
  for a live deployment with an existing SQLite/Postgres file.
- Per-agent capability data (e.g. available models) lives as a class
  attribute on each adapter in `src/aipipe/agents/*.py` (e.g. `MODELS` on
  `ClaudeAdapter`/`CodexAdapter`), looked up via `aipipe.agents.agent_models()`.
  Keep this pattern for future adapter-specific config so it isn't scattered
  across the orchestrator/control layers.
- SQLite silently drops tzinfo on round-trip for SQLAlchemy `DateTime
  (timezone=True)` columns (`ControlTask.heartbeat_at`, `.created_at`, etc.):
  a value written via `datetime.now(timezone.utc)` comes back naive. Any new
  code comparing a fetched timestamp against `datetime.now(timezone.utc)` in
  Python (not as a SQL-side filter, which is fine — the DB engine handles
  that symmetrically) must normalize with `dt.replace(tzinfo=timezone.utc)`
  first, or it raises "can't compare offset-naive and offset-aware
  datetimes" against a real SQLite-backed database despite passing against
  an in-memory fixture that never round-trips through the DB.
- A single color cannot simultaneously satisfy WCAG AA both as small text on
  a near-black background *and* as a solid button fill under white text —
  the luminance ranges that satisfy each constraint don't overlap. Frontend
  work introducing a "primary accent" needs at least two tokens (a lighter
  one for text/links/icons, a darker one for solid button fills), not one —
  see `docs/DESIGN_SYSTEM.md`'s contrast table for the AIpipe values.
- Tailwind v4's CSS-first `@theme` block is parsed by a real CSS optimizer at
  build time — a source comment containing a glob-looking token like
  `--font-*/--radius-*` (even inside `/* ... */`) can trip the optimizer
  ("Unexpected token Delim('*')" in `next build`'s CSS-optimization pass).
  Avoid `*`-suffixed CSS-variable-looking text in comments near an `@theme`
  block; spell out examples instead (`--font-sans`, not `--font-*`).
