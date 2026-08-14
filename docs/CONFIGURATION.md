# Configuration

## Server environment

See `.env.example` for the complete control-center configuration.

Important variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL/SQLite control DB URL |
| `AIPIPE_REPOS_ROOT` | server repository/worktree data root |
| `AIPIPE_SESSION_SECRET` | signed web session secret |
| `AIPIPE_DEV_AUTH` | bypass GitHub login for local development only |
| `AIPIPE_ALLOWED_GITHUB_LOGINS` | comma-separated production operators |
| `GITHUB_APP_*` | App/OAuth/install token configuration |
| `GITHUB_WEBHOOK_SECRET` | webhook verification secret |
| `OPENAI_API_KEY` | Codex backend credential |
| `ANTHROPIC_API_KEY` | Claude backend credential |

## Repository configuration

`.ai/config.yml` is committed with the target repository.

```yaml
main_branch: main
agent: codex
ci_timeout_seconds: 1800
command_timeout_seconds: 1200

git:
  auto_merge: true
  merge_method: squash

quality:
  commands:
    test: python -m pytest
    lint: ruff check .

security:
  commands:
    dependency-audit: pip-audit

retries:
  implementation: 3
  verification: 3
  review: 2
  ci: 2

codex:
  binary: codex
  ignore_user_config: true
  network_access: false

claude:
  binary: claude
  permission_mode: auto
  max_budget_usd: 5
  max_turns: 20
```

Explicit project quality/security commands are preferred for production repositories. Autodetection is a fallback.
