# 0020: Language Packs, the sandbox runner and previews

Date: 2026-10-28 · Status: accepted · Phase 5

## Context

CODEWRIGHT.md Phase 5: the `LanguagePack` interface and the unsupported-language check, packs for Python, Go,
TypeScript, JavaScript and C++, a sandbox runner (toolchain images, limits, network allowlist, web and terminal
previews) and one template per language. Section 11 says code from a project or from the model is never trusted:
no production, no host network, no secrets. You chose a separate runner that holds the Docker socket; the API
never gets it.

## Decision

- **Language Packs** (`agent/language_packs/`): one `LanguagePack` per language (`NodePack` serves TypeScript and
  JavaScript). Each one detects its components (a project can have several: GoShop is a Go API at `.` plus a
  TypeScript web app at `web/`), reads their frameworks and entrypoints, and gives the commands for
  install / build / test / lint / run. `executor.py` runs those steps through the sandbox and turns test output
  (go test JSON, JUnit from pytest / Vitest / ctest) into one report shape (`reports.py`). `compose.py` reads the
  project's own docker-compose file for the services the app needs and its SQL migrations.
- **Unsupported languages**: the chat declines them by rule (Phase 2). `unsupported_project` also declines a
  project that is mostly in another language, with the same suggestions (`config/intake.yaml`), shown on the
  project home.
- **Sandbox runner** (`sandbox/runner`, service `sandbox-runner`, port 8200 on the compose network only): the only
  thing with the Docker socket. It speaks the Docker Engine API directly and only offers **sessions** (one per
  workspace: an internal network and the sidecars), **jobs** (one command, streamed) and **previews**. Every
  container: allowed image only, uid 10001, all capabilities dropped, read-only root filesystem with tmpfs `$HOME`
  and `/tmp`, CPU / memory / PID / time limits from `config/sandbox.yaml`, no host network, no host paths (only the
  workspace's `work/` folder and a cache volume). Docker's `no-new-privileges` stays off: on this host it makes every
  exec fail (EPERM), even in alpine; the images carry no setuid binaries instead.
- **Network**: session networks are `internal` (no route out). Install steps go through the **egress gateway**
  (`sandbox-gateway`, no Docker socket), an HTTP proxy that only allows the package registries in
  `egress.allow`; hosts that resolve to private, loopback or link-local addresses are refused, so sandboxed code
  can't reach Codewright, the database or the LAN. Each step says whether it needs the registries: installs and
  some builds do; tests, linters and the Node build run with no network at all.
- **Sidecars**: Postgres, Redis, MySQL and Mongo, only from the image repositories listed in the config, started
  from the project's compose file with its migrations applied, reachable by their compose names. Throwaway; the
  real databases are never touched.
- **Previews**: `web` previews are forwarded by the gateway to `127.0.0.1:41000-41009`; `terminal` previews are
  an interactive TTY (output over SSE, input and resize over POST), drawn with xterm.js in the Preview tab.
- **Templates** (`templates/apps/`): `cli-python`, `api-go`, `web-react-ts`, `web-react-js`, `cli-cpp`, each with a
  manifest, a guide and a Graphify setup. Turning a template into a project is part of Phase 13 (New app).

## Consequences

- The runner holds the Docker socket, which is root-equivalent on the host; its API is the boundary, so it only
  accepts the shapes above and never a raw Docker request.
- Sessions are removed after 2 hours idle; at most 4 at a time.
- Previews listen on 127.0.0.1 only; reaching them from another machine needs a tunnel, like the rest of the app.

## Acceptance (2026-10-28, live on the running stack)

- GoShop: Go build 4.5 s, web build 37 s; tests **342 Go + 7 Vitest passed**; run started Postgres (migration
  applied) and Redis, the API on :41000 (`/health` 200, `/api/v1/products` 200) and the web app on :41001, whose
  dev server passes `/api` through to the API.
- C++ CMake fixture: configure, build, **ctest 2 passed**; in the terminal preview `5`, `37`, `abc`, `quit` gave
  `total = 5`, `total = 42`, `not a number`, `bye, total 42`, exit 0.
- "Build me a REST API … in Java with Spring Boot" → declined: "I can do it in Go, TypeScript, Python (closest
  first)".
- Golden tests on fixtures for every pack (`agent/tests/language_packs/`).
