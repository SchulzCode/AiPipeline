# Local Qwen backend

AIpipe can use Qwen Code as a local coding-agent backend while keeping AIpipe responsible for worktrees, deterministic quality/security gates, pull requests, CI, and merge policy.

The model server is intentionally **not bundled with AIpipe**. Run an OpenAI-compatible server on the host and let the worker connect to it.

## Recommended starting point

For a machine with roughly 32 GB system RAM and 8 GB NVIDIA VRAM, a practical starting model is:

- Qwen3-Coder-30B-A3B-Instruct
- Q4_K_M GGUF
- 32K context

Use a current CUDA-enabled `llama.cpp` build. A representative Windows command is:

```powershell
.\llama-server.exe `
  -m "C:\AI\models\Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" `
  --alias qwen-local `
  --host 0.0.0.0 `
  --port 8080 `
  --ctx-size 32768 `
  --n-gpu-layers auto `
  --fit on `
  --fit-target 1024 `
  --flash-attn auto `
  --cache-type-k q8_0 `
  --cache-type-v q8_0 `
  --api-key "replace-with-a-local-secret"
```

`llama.cpp` may change or tune inference flags over time. The important AIpipe contract is an OpenAI-compatible endpoint whose `/v1/models` response exposes the configured alias.

Because the AIpipe worker runs in Docker, the server must listen on an address reachable from the container. The supplied Compose configuration uses `host.docker.internal`.

## Configure AIpipe

Copy `.env.example` to `.env` and set:

```env
AIPIPE_LOCAL_LLM_BASE_URL=http://host.docker.internal:8080/v1
AIPIPE_LOCAL_LLM_API_KEY=replace-with-a-local-secret
AIPIPE_LOCAL_LLM_MODEL=qwen-local
```

Do **not** replace AIpipe's global `OPENAI_BASE_URL` with the local endpoint. The Qwen adapter translates the `AIPIPE_LOCAL_LLM_*` values only for its own subprocess so Codex remains independent.

Build/rebuild the worker after pulling a version that includes local-Qwen support:

```bash
docker compose up --build
```

The worker image already contains the pinned Qwen Code CLI. Model weights remain on the host.

## Readiness check

For a Qwen project, `aipipe doctor` checks both the `qwen` binary and the configured local `/models` endpoint. Inside the worker:

```bash
docker compose exec worker aipipe --agent qwen doctor
```

The readiness probe distinguishes an unreachable endpoint, authentication failure, malformed response, and configured-model mismatch without printing the API key.

## End-to-end canary

Before using Local Qwen on a real repository, run the opt-in canary:

```bash
docker compose exec worker aipipe local-canary
```

It creates a disposable Git repository and verifies the complete local-agent path:

```text
AIpipe
  -> Qwen Code
  -> configured OpenAI-compatible local model server
  -> read-only planning pass (workspace must remain unchanged)
  -> implementation pass (creates a known canary file)
  -> deterministic AIpipe QualityEngine verification
```

The temporary workspace is deleted automatically. The canary does not commit, push, create a pull request, or touch a registered project.

A successful result contains:

```json
{
  "ok": true,
  "read_only_ok": true,
  "implementation_ok": true,
  "verification_ok": true
}
```

It also reports the Qwen Code input/output token accounting when available.

## Control Center

When creating or editing a project, select:

```text
Agent: Local Qwen
Model: Local Qwen (qwen-local)
```

The displayed model alias follows `AIPIPE_LOCAL_LLM_MODEL`.

## Current scope

Local Qwen is a normal selectable backend. AIpipe still applies its normal setup, verification, review, security, CI, and merge rules.

Automatic local-first routing and cloud escalation are separate features. Until those are enabled, choosing Local Qwen means that project explicitly uses the local backend for its agent runs.
