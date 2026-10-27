# Runs the Python checks (ruff, mypy, pytest) in Docker: `make check`. Build context: repo root.
# Unlike apps/api/Dockerfile this image includes the dev tools and the tests.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-install-workspace

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages

ENV PATH=/app/.venv/bin:$PATH
CMD ["sh", "-c", "python scripts/ensure_test_db.py && ruff check . && ruff format --check . && mypy && pytest"]
