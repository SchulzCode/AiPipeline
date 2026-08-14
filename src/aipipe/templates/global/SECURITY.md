# Security Rules

## Secrets
- Never commit credentials, API keys, access tokens, passwords or private keys.
- Use environment injection or a dedicated secret manager for runtime secrets.

## Trust boundaries
- Treat user, network, file, webhook, database and third-party input as untrusted at system boundaries.
- Validate inputs before privileged or persistent operations.

## Authentication and authorization
- Authentication proves identity; authorization must independently enforce allowed actions.
- Never trust client-side authorization, hidden UI elements, client-provided role claims or object ownership without server-side verification.
- Prefer deny-by-default behavior.

## Data
- Minimize collection and exposure of sensitive data.
- Do not log passwords, credentials, session tokens, private keys or unnecessary sensitive fields.

## Dependencies
- Avoid new dependencies unless they provide clear value.
- Do not suppress known vulnerability findings without explicit project policy and documented reasoning.

## Files and commands
- Normalize/validate user-controlled paths and prevent traversal outside intended roots.
- Avoid shell interpolation of untrusted values.

## Web/API
- Use parameterized queries and safe framework primitives.
- Apply appropriate CSRF, XSS, CORS, rate-limiting and request-size controls where the architecture requires them.
- Do not expose internal stack traces or secret configuration to clients.

## Cryptography
- Use maintained standard libraries and established protocols. Do not design custom cryptography.

## Production boundaries
- A task may prepare production-ready code, but it may not bypass branch protection, required checks, repository policy or external approvals.
