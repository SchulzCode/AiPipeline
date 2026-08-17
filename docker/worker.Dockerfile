FROM node:22-bookworm-slim

ARG CODEX_VERSION=0.147.0
ARG CLAUDE_CODE_VERSION=2.1.232
ARG QWEN_CODE_VERSION=0.21.2
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv git gh ca-certificates curl build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server]" \
    && npm install -g \
      "@openai/codex@${CODEX_VERSION}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@qwen-code/qwen-code@${QWEN_CODE_VERSION}"

CMD ["aipipe-worker"]
