# MonoShift API image. Build context: repo root (needs uv.lock and config/).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv

WORKDIR /app
# Dependencies first (cached layer), then the source.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package monoshift-api --no-install-workspace

COPY apps/api apps/api
COPY config config
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package monoshift-api

RUN useradd --system --uid 10001 --home-dir /app monoshift \
    && mkdir -p /app/workspaces && chown monoshift /app/workspaces
USER monoshift

ENV PATH=/app/.venv/bin:$PATH \
    MONOSHIFT_MODELS_CONFIG=/app/config/models.yaml \
    MONOSHIFT_WORKSPACES_DIR=/app/workspaces
WORKDIR /app/apps/api
EXPOSE 8000
# Migrations run on start so `docker compose up` is enough on a fresh machine.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn monoshift_api.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
