# Codewright sandbox: Go toolchain. Modules download through the sandbox proxy (GOPROXY default).
FROM golang:1.26-bookworm
RUN useradd --create-home --uid 1000 sandbox \
    && mkdir -p /go/pkg && chown -R sandbox /go
ENV GOFLAGS=-buildvcs=false GOTOOLCHAIN=local CGO_ENABLED=0
USER sandbox
WORKDIR /work
