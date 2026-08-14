FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[server]"
EXPOSE 8000
CMD ["uvicorn", "aipipe.control.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
