# Codewright sandbox: Python toolchain (CODEWRIGHT.md Section 8.3). Projects install their own dependencies.
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv
RUN pip install --no-cache-dir pytest==9.1.1 ruff==0.17.0 mypy==2.4.0 \
    && useradd --create-home --uid 1000 sandbox
ENV UV_LINK_MODE=copy PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
USER sandbox
WORKDIR /work
