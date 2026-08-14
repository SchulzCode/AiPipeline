# Production Readiness / Quality Rules

A task may reach main only when all gates required by its routing policy have passed.

Minimum evidence:
- Requested behavior and acceptance criteria are satisfied.
- Relevant automated tests pass.
- Configured build/lint/type/static checks pass.
- Added diff contains no detected secrets.
- Configured security commands pass.
- Required independent semantic reviews pass.
- GitHub CI provides passing evidence; absence of CI is not treated as success for autonomous merge.
- The PR is mergeable and repository protection rules are honored.

Review priorities:
1. correctness and regressions
2. acceptance criteria
3. security and trust boundaries
4. tests for changed behavior
5. scope control and maintainability

Do not require unrelated cleanup as a condition of the task.
