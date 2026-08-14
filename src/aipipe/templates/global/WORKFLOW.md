# AIpipe Workflow

Normal task lifecycle:

QUEUED -> ROUTING -> PREPARING -> DISCOVERY -> PLANNING -> IMPLEMENTING -> VERIFYING -> REVIEWING -> PR_OPEN -> CI -> MERGING -> POST_MERGE -> DONE

Exception states: BLOCKED, NEEDS_INPUT, FAILED, CANCELLED.

Principles:
- Chats/sessions are disposable; structured task state and repository knowledge persist.
- Deterministic tools own objective gates such as Git state, tests, build results, secret scanning and CI state.
- AI is used for software reasoning, implementation, semantic review and security reasoning.
- New agent sessions receive compact state, relevant knowledge and current diffs rather than old transcripts.
- Retry loops are bounded.
