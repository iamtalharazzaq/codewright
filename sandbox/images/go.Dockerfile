# Codewright sandbox: Go toolchain. Modules download through the sandbox proxy (GOPROXY default).
# Runs as uid 10001 (the API's uid, so both can write workspaces); the runner adds a read-only root, tmpfs $HOME and limits.
FROM golang:1.26-bookworm
RUN groupadd --gid 10001 sandbox && useradd --create-home --uid 10001 --gid 10001 sandbox \
    && mkdir -p /go/pkg && chown -R sandbox /go
ENV GOFLAGS=-buildvcs=false GOTOOLCHAIN=local CGO_ENABLED=0
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
