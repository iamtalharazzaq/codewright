# Codewright sandbox: Python toolchain (CODEWRIGHT.md Section 8.3). Projects install their own dependencies.
# Runs as uid 10001 (the API's uid, so both can write workspaces); the runner adds a read-only root, tmpfs $HOME and limits.
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv
RUN pip install --no-cache-dir pytest==9.1.1 ruff==0.17.0 mypy==2.4.0 coverage==7.10.6 pip-audit==2.9.0 \
    && groupadd --gid 10001 sandbox && useradd --create-home --uid 10001 --gid 10001 sandbox
ENV UV_LINK_MODE=copy PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
