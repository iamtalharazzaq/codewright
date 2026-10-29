# Codewright sandbox: Go toolchain. Modules download through the sandbox proxy (GOPROXY default).
# staticcheck (Phase 19: the spec's own table names "go vet, staticcheck" — only vet was wired until now).
# Runs as uid 10001 (the API's uid, so both can write workspaces); the runner adds a read-only root, tmpfs $HOME and limits.
FROM golang:1.26-bookworm
RUN GOBIN=/usr/local/bin go install golang.org/x/vuln/cmd/govulncheck@v1.1.4 \
    && GOBIN=/usr/local/bin go install honnef.co/go/tools/cmd/staticcheck@v0.8.2 \
    && groupadd --gid 10001 sandbox && useradd --create-home --uid 10001 --gid 10001 sandbox \
    && mkdir -p /go/pkg && chown -R sandbox /go
ENV GOFLAGS=-buildvcs=false GOTOOLCHAIN=local CGO_ENABLED=0
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
