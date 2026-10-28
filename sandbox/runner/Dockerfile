# Codewright sandbox runner and gateway (ADR 0020). Build context: repo root.
# One image, two services: `sandbox-runner` (holds the Docker socket, runs uvicorn) and `sandbox-gateway`
# (egress proxy + preview forwarder, no socket, runs `python -m codewright_sandbox.gateway`).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY sandbox/runner/pyproject.toml sandbox/runner/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package codewright-sandbox --no-install-workspace

COPY sandbox/runner sandbox/runner
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package codewright-sandbox

ENV PATH=/app/.venv/bin:$PATH SANDBOX_CONFIG=/app/config/sandbox.yaml
EXPOSE 8200
CMD ["uvicorn", "codewright_sandbox.app:app", "--host", "0.0.0.0", "--port", "8200"]
