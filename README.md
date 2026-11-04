# Codewright

A self-hosted AI software house in a chat app. You chat with it like Claude or ChatGPT; behind the chat, a team of AI roles works on your code in Python, Go, TypeScript/JavaScript and C++. It can create new projects and explain, fix, test, refactor, secure, upgrade and extend existing ones. It proves its work with tests and asks for your approval before changing anything.

## Run

Requires Docker Compose.

```
make up      # build and start, then open http://localhost:3000
make down    # stop
make logs    # follow logs
```

The LLM runs on a GPU you host. See [docs/setup/remote-gpu.md](docs/setup/remote-gpu.md).

## Checks

```
make check           # lint, types and tests, in containers
make check-sandbox   # templates and language packs in the real sandbox (needs make up)
```

## Layout

- `apps/web`: chat UI
- `apps/api`: API
- `agent`: playbooks, agents, language packs
- `sandbox`: isolated runner for builds and tests
- `templates`: scaffolds for new projects
- `evals`: evaluation suites
- `docs`: setup, architecture, ADRs

The full design is in [CODEWRIGHT.md](CODEWRIGHT.md).
