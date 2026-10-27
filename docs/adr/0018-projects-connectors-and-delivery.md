# 0018: Projects, connectors and delivery

Date: 2026-10-27 · Status: accepted · Phase 3

## Context

CODEWRIGHT.md Phase 3: connect a project (GitHub, ZIP, Google Drive, local folder), give it a home with instructions
and memory, accept uploads in the chat, and deliver results where the user chooses (C7). Everything runs locally for
one user; the model sees project files and uploads as data, never as instructions.

## Decision

- **Workspace (Section 8.1).** `workspaces/<project>/source/` is the untouched original; `work/` is a git repository
  with the same files where every change happens on a branch. A GitHub clone keeps its history in `work/` so changes
  become a pull request; any other source starts a new repo with one commit. `agent/tools/workspace.py`.
- **Inputs (`connectors/inputs`).** Plain code, no LLM:
  - ZIP: every entry checked before anything is written: no `..` or absolute paths, no symlinks, at most 20,000
    files / 500 MB, and a per-file compression ratio of at most 200 (ZIP bombs). Upload limit 300 MB.
  - GitHub: `git clone --depth 1`; `GITHUB_TOKEN` (optional, for private repos) goes in an `http.extraHeader`, never
    in the URL or the saved remote.
  - Local folder: only folders under `LOCAL_SOURCE_DIR`, mounted read-only; paths are resolved and must stay inside.
  - Drive: a share link to a ZIP, downloaded with the user's Drive token, then the ZIP checks above.
  Imports run in the background (`importing` → `ready` / `failed` with a readable reason).
- **Secrets (`agent/tools/secrets.py`).** Pattern scan (private keys, cloud/GitHub/Slack/Stripe/OpenAI-style keys,
  JWTs, passwords in URLs, `secret = value` assignments, `.env` files) on every import and upload. Findings are shown
  on the project home; text going to a prompt is masked as `«secret»`. A safety net, not a guarantee.
- **Uploads.** Stored under `workspaces/_uploads/`, scanned, linked to the message. Text files go into the prompt
  masked and cut short (the GPU model has a 4K context); other files are named only.
- **Project context in the chat.** Name, file count, languages, top-level entries, the user's instructions and project
  memory go into the system prompt as data (capped at 1,500 characters). The project's main language becomes the
  default language for new code (C18).
- **Outputs (`connectors/outputs`) and `POST /api/deliver`.** The user picks one or more targets; each gets its own
  result line, so one failure doesn't hide the others:
  - ZIP: built without `.git`/`node_modules`/virtualenvs, downloaded from `/api/deliveries/<name>.zip`.
  - Local: copied into `ALLOWED_OUTPUT_DIRS` (mounted at `/data/outputs`) as `<name>-<time>/`.
  - GitHub: push of `work/` to a new `codewright/<time>` branch and a pull request through the REST API. Never
    pushes to the default branch.
  - Drive: the ZIP uploaded with the `drive.file` scope.
- **Google Drive OAuth.** The user's own OAuth client (`GOOGLE_OAUTH_CLIENT_FILE`), consent from Settings, redirect
  to `<PUBLIC_URL>/api/connectors/gdrive/callback`. The refresh token is stored in `app_settings`, encrypted with
  Fernet using a key derived from `SECRET_KEY`. Scopes: `drive.file` and `drive.readonly`.

## Consequences

- No new service: git runs in the API container (added to its image and to the checks image).
- GitHub delivery needs commits on `work/`; until later phases make changes, delivering an untouched project to GitHub
  reports "no commits between" from GitHub.
- Drive and private GitHub need the user's credentials in `.env`; without them those targets explain what to set
  instead of failing silently.
