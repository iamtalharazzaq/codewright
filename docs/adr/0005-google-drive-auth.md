# 0005. Google Drive access for one local user (verification V4)

- **Status:** proposed (waiting on the user: see the question in PROGRESS.md)
- **Date:** 2026-10-26
- **Phase:** 0 (implemented in Phase 2)

## Context
README C5/V4/Section 9.2: import from a Drive folder or ZIP link, and deliver to a Drive folder, for a single local
user. Sources: Drive API Python quickstart (developers.google.com/workspace/drive/api/quickstart/python) and the OAuth
2.0 overview (developers.google.com/identity/protocols/oauth2), 2026-10-26.

Facts:
- Libraries: `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`.
- Client type: **Desktop app** OAuth client; `InstalledAppFlow.from_client_secrets_file(...)` then
  `run_local_server(port=0)`; the token (access + refresh) is saved and reused.
- An External-user-type app in **"Testing"** status gets refresh tokens that **expire after 7 days** (unless only basic
  profile scopes are requested).
- Scopes: `drive.file` (files the app created or the user opened with it) is enough for **uploads**. Reading an
  arbitrary shared link needs `drive.readonly`, which is a restricted scope.

## Decision (proposed)
- The user creates their own Google Cloud project and a Desktop app OAuth client, then puts the client JSON path in
  `MONOSHIFT_GOOGLE_OAUTH_CLIENT_FILE`. Nothing is shared with any third party.
- The flow runs from Settings → "Connect Google Drive": the API starts the installed-app flow with a loopback redirect
  on a fixed port published on 127.0.0.1, and the user consents in their browser. The refresh token is stored encrypted
  (`MONOSHIFT_SECRET_KEY`).
- Scopes: `drive.file` + `drive.readonly`.
- **Open choice for the user:** (a) keep the app in Testing and reconnect about weekly, or (b) set the app to
  "In production" without verification (personal use; Google shows an "unverified app" warning) to get long-lived
  refresh tokens.

## Consequences
No service account and no hosted backend are needed. The weekly re-consent in option (a) is the main friction.
