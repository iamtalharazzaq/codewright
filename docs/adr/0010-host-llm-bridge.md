# 0010. Reaching a host-only llama-server from Docker

- **Status:** accepted
- **Date:** 2026-10-26
- **Phase:** 1

## Context
The user's local llama-server listens on `127.0.0.1:8080` (and the embedding server on `:8081`). Containers reach the
host through `host.docker.internal` (the Docker bridge address, `172.17.0.1`), which a loopback-only server doesn't
answer. The user wants the model used "through an API, just replace the URL", without changing their server.

## Decision
An opt-in compose profile `host-llm-bridge`: an `alpine/socat` container on the host network that listens **only on
the Docker bridge address** and forwards to the host's loopback ports. Enabled here via `COMPOSE_PROFILES` in `.env`.
Nothing is exposed beyond the machine. Users whose server already listens on a reachable address don't need it.

## Consequences
Verified: from the API container, `local_cpu` health is `ok` (4 slots × 4096 tokens). If the bridge address differs on
another machine, set `MONOSHIFT_DOCKER_BRIDGE_IP`.
