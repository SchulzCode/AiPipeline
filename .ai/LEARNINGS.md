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
