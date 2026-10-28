# 0028: DevOps deploy

Date: 2026-10-29 · Status: accepted · Phase 14

## Context

CODEWRIGHT.md 5.15: Dockerfiles, Compose, CI/CD, optional Kubernetes, observability, security review, verified in the
sandbox. The sandbox runner holds the Docker socket on purpose and offers no image builds to playbooks.

## Decision

- Files come from **templates per Language Pack** (`devops/files.py`), not from a model: base images, flags and
  users must be right every time. Deployable components, ports and health routes are read from the code; databases
  from dependency manifests. Existing files are never overwritten.
- CI is generated from the packs' own build, lint and test steps, so what CI runs is what Codewright already runs.
- Verification is honest about its limits: static checks on the files (pinned tags, non-root, COPY sources, YAML,
  secrets, Docker socket), then the same build and test commands run in the sandbox. **Images are not built.**
- Observability is health checks/probes from a health route found in the code, plus `OTEL_SERVICE_NAME`.

## Consequences

Deterministic and reviewable. A project with unusual start commands may need the Dockerfile edited by hand.
