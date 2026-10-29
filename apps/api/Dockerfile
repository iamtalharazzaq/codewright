# Codewright API image. Build context: repo root (needs uv.lock and config/).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv

# git: project imports (GitHub), change branches and delivery (CODEWRIGHT.md Section 8.1).
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Dependencies first (cached layer), then the source.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY sandbox/runner/pyproject.toml sandbox/runner/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package codewright-api --no-install-workspace

COPY agent agent
COPY connectors connectors
COPY apps/api apps/api
COPY config config
COPY templates templates
COPY skills/builtin skills/builtin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package codewright-api
RUN chmod +x apps/api/entrypoint.sh

RUN useradd --system --uid 10001 --home-dir /app codewright \
    && mkdir -p /app/workspaces /app/skills/user && chown codewright /app/workspaces /app/skills/user
USER codewright

ENV PATH=/app/.venv/bin:$PATH \
    MODELS_CONFIG=/app/config/models.yaml \
    WORKSPACES_DIR=/app/workspaces \
    SKILLS_DIR=/app/skills/user
WORKDIR /app/apps/api
EXPOSE 8000
# Migrations run on start so `docker compose up` is enough on a fresh machine. entrypoint.sh retries a handful of
# times with backoff if the database isn't reachable yet, instead of crash-looping forever (ADR 0034).
CMD ["./entrypoint.sh"]
