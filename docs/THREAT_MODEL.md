# Threat model

## Security objective

AIpipe must make it difficult for an agent, repository change, failing test, or prompt-injection attempt to bypass the evidence required for merge or obtain unrelated control-plane secrets.

## Trusted in v1.0

- the AIpipe host/operator;
- the baseline repositories registered in one worker trust domain;
- GitHub and configured agent providers;
- explicitly configured build/security tools.

## Untrusted inputs

- task prompts;
- GitHub issue titles/bodies/comments;
- generated model output;
- code changes produced by an agent;
- branch/CI output;
- repository input data used by tests;
- webhook payloads until signature verification succeeds.

## Key controls

### Deterministic merge gate

Agents cannot declare their own work merge-ready. Quality, security, CI, PR state, and applicable review evidence are evaluated by orchestrator code.

### No admin bypass

The GitHub adapter never adds an admin bypass flag. Repository protection/rules remain authoritative.

### Environment isolation

Agent and repository command subprocesses are launched from an explicit allowlist environment. Control-plane variables such as `DATABASE_URL`, GitHub App private keys, session secrets, and webhook secrets are not inherited by these child processes.

Git/`gh` commands get only the short-lived installation token plus the safe process environment.

This limits accidental environment leakage but is **not equivalent to a hostile-code sandbox**.

### Secret scan

New and modified added lines are scanned before commit. Untracked files are included by intent-to-add before diff generation.

### Bounded retries

Each repair loop has a fixed budget. Exhaustion produces BLOCKED instead of an unbounded model loop.

### Auth/web security

- GitHub OAuth state is checked.
- production operators are GitHub-login allowlisted.
- sessions are signed and HttpOnly.
- HTTPS configuration enables Secure cookies.
- mutating browser calls are origin-checked.
- CORS is explicit, not wildcard-with-credentials.
- GitHub webhooks require HMAC SHA-256 signature verification and delivery IDs are deduplicated.

## Important v1.0 boundary: repository execution

Build/test/lint/security commands execute repository-controlled programs in the worker service. The Compose worker is a separate execution service, but it is a persistent container and may contain workspaces for multiple projects over time.

Therefore, **do not register arbitrary hostile third-party repositories in the same default worker trust domain**.

For that threat model, add a disposable per-task VM/container/microVM runner which mounts only the current worktree and receives only task-scoped credentials. This is intentionally left outside v1.0 rather than claiming that Git worktrees or an LLM sandbox provide equivalent isolation.

## Agent credentials

An agent process necessarily receives credentials required to call its own provider (for example an API key). Treat an intentionally malicious provider/tool process as outside the v1.0 threat model. Do not place unrelated credentials in the agent environment.

## Deployment boundary

AIpipe v1.0 ends at guarded merge to the repository main branch. Production deployment credentials and target production infrastructure should remain outside AIpipe unless a future deployment subsystem introduces its own explicit security model and gates.
