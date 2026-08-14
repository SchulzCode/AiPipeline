# GitHub App setup

AIpipe uses a GitHub App rather than a long-lived personal access token for repository automation.

## URLs

For a localhost setup:

- Homepage URL: `http://localhost:3000`
- Callback URL: `http://localhost:8000/auth/github/callback`
- Webhook URL: `http://localhost:8000/github/webhook`

For a real deployment, use HTTPS public URLs and set the matching `AIPIPE_WEB_BASE_URL`, `AIPIPE_API_BASE_URL`, `AIPIPE_CORS_ORIGINS`, and `NEXT_PUBLIC_API_URL` values.

## Repository permissions

Grant only what the repositories/workflow need. A practical AIpipe installation normally needs permission to:

- read/write repository contents (branches/commits pushed by the App token);
- read/write pull requests;
- read issues;
- read Actions/check status and failed run logs;
- read repository metadata.

If your pipeline intentionally modifies workflow files or needs additional protected capabilities, add only those explicit permissions.

## Webhooks

Set a strong webhook secret and configure `GITHUB_WEBHOOK_SECRET` to the exact same value. Useful events include pull request and check/workflow events. The core does not rely exclusively on webhook delivery for CI progression in v1.0; it also polls required PR checks.

## Credentials

Copy the App ID, client ID, client secret, and private key into `.env`. Prefer the base64 private-key option:

Linux GNU coreutils:

```bash
base64 -w0 your-app.private-key.pem
```

Portable alternative:

```bash
base64 < your-app.private-key.pem | tr -d '\n'
```

Store the resulting value as `GITHUB_APP_PRIVATE_KEY_B64`.

Do not commit `.env` or the PEM key.

## Installation

Install the App only on repositories AIpipe is allowed to modify. Once configured, the **Add project** screen lists App installations and the repositories visible to each installation.

## Operator login

The same GitHub App client credentials are used for the web login flow. For production, set:

```env
AIPIPE_DEV_AUTH=false
AIPIPE_ALLOWED_GITHUB_LOGINS=your-login
```

Multiple comma-separated operator logins are accepted, but v1.0 is an operator-allowlist model rather than full team RBAC.
