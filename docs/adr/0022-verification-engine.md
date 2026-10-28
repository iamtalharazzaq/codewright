# 0022: Verification engine

Date: 2026-10-28 · Status: accepted · Phase 7

## Context

CODEWRIGHT.md Phase 7: test runner integration with coverage, characterization test generation by a QA sub-agent,
a traffic recorder/replay/semantic-diff/noise-rules engine (Section 5.18), benchmarks (k6) and screenshot comparison
(Playwright), and an eval harness skeleton. The acceptance is behavioral: GoShop recorded and replayed with 0
diffs, and every check must also pass on a benchmark of a different language and type (Section 15.0) — so a second
fixture, `evals/repos/notes-api-python` (FastAPI/SQLAlchemy/Postgres), was written as a synthetic benchmark (the
real-world candidates tried first pinned wheels too old for Python 3.12, or had no compose file).

## Decision

- **Traffic model** (`agent/verification/traffic.py`): `Body` (none/json/text/binary, from a `Content-Type`),
  `Request`/`Response`/`Exchange`/`Recording`, saved as JSON. `from_har` reads a browser's exported HAR; `is_api_call`
  drops static assets, HTML pages and dev-server internals so a recording holds only the app's own API calls.
- **Noise rules** (`noise.py`): a difference between two answers that isn't a change in behavior — generated IDs
  (UUID/ULID/ObjectId), timestamps (ISO 8601, HTTP dates, epoch numbers under time-like keys), tokens (JWTs, random
  strings under token-like keys), float rounding (tolerance), array order (off by default: order is often behavior).
  Built-ins the user can switch off; a project can add its own rule (a JSON-path-like pattern, `**`/`*` glob,
  `header:*` for response headers). Every noise verdict names the rule, so the user can see what was ignored.
- **Semantic diff** (`diff.py`): `Comparer` walks the JSON body (or masks and diffs text, or compares binary),
  and a fixed set of headers (`content-type`, `location`, …; most headers are volatile and skipped outright). Each
  difference is **regression**, **noise** (a rule explains it) or **intended** (an `Intent` the user gave — "this
  endpoint now returns 403, on purpose"). 0 regressions is the bar for accepting a replay.
- **Replay and linking** (`replay.py`): requests are resent in recorded order, one cookie jar per journey. A `Linker`
  watches what the recorded run and the live run each handed out (an ID in the body, a `Location` segment) and, when
  they differ, treats the live value as standing in for the recorded one from then on — in later paths, query
  strings, headers and bodies. This is what lets `GET /items/{id}` work on a replay against a freshly reset
  database with new primary keys, without the user writing anything.
- **Journeys** (`journeys.py`): a plain-JSON request sequence with `{{var}}` substitution from values an earlier
  step saved (a JSON path into its answer). Two sources: a **smoke** journey (every GET without parameters, built
  from the Language Packs' route nodes) and journeys a **QA sub-agent** writes (`characterize.py`) from the routes
  and their handler code — grouped by resource (login first; a path prefix shared by every route in a project is
  stripped so groups read as `notes`, not `api-v1-notes`), ordered so a group whose code is referenced by another
  comes first, retried once on a 400/401/422 with that rejection fed back as a hint, and the attempt with the most
  accepted steps is kept.
- **Recording sources**: journeys (`record`), a live browse through mitmproxy as a reverse proxy sharing the app's
  network (`record-live`; a sandbox terminal preview the user opens, with a Stop button that ends it and saves
  what was recorded), or an imported HAR file from the browser's own developer tools.
- **Benchmarks** (`bench.py` + k6, Section 5.18/Phase 7 task 4): replay a recording first (so IDs and tokens are
  valid), take its successful GETs (one target per endpoint, IDs folded to `{id}`), and load them with k6 run as a
  sandbox process sharing the app's network (`share_network_of`, so it reaches `127.0.0.1:<port>` like the previewed
  app does) — 5 virtual users for 20 s by default. Compared with the last benchmark of the same recording (p95,
  throughput, per endpoint).
- **Screenshots** (`shoot.py` + Playwright, new `browser` sandbox image): every page route the Language Packs found
  (no parameters), shot at 1280×800 after the network goes idle, pixel-diffed against an accepted baseline (anti-
  aliasing tolerance, then a percentage of changed pixels). `accept: true` makes this run the new baseline.
- **`VerificationService`** (`apps/api/.../verification.py`) owns the reset: every action that touches the app calls
  `fresh_app`, which stops the sandbox session, starts the component fresh (migrations re-applied) and polls until
  it answers HTTP — distinguishing the gateway's own `503 Starting`/`502 No preview` from the app's real answer, so
  readiness isn't declared early. One verification runs per project at a time (it owns the app's state). Reports
  (test/record/replay/bench/screens) are saved as JSON and kept per project; the Tests tab follows an action's SSE
  events live and then renders its finished report.
- **Eval harness skeleton** (task 5): `evals/tasks/registry.json` lists tasks (playbook → case file → eval script);
  `evals/run_tasks.py` runs them and writes one pass/fail summary, so a new eval is a case file plus a registry line,
  not a new runner. Reused the Phase 6 scripts' import/poll helpers (`evals/review.py`) in the new `evals/verify.py`.

## Consequences

- The `browser` sandbox image (Playwright + Pillow, ~2 GB) wasn't built this session — disk was at 95% (11 GB free)
  and the user asked to stop spending time on verification loops and finish the remaining features instead.
  `screens` and the screenshot half of `record-live`'s self-check are code-complete and unit-tested but **not run
  against a real app**. `make sandbox-images` builds it along with the rest.
- For the same reason, GoShop's 0-regression replay and notes-api-python's record/replay are confirmed only from
  earlier in this phase, before the readiness fix and the `journeys.normalize()` fix (found by a unit test: the
  gin-style `:id` substitution ran before Flask's `<int:id>`, corrupting it to `<int{id}>`). Both fixes are small
  and covered by unit tests, but a live re-run is what the acceptance criterion actually asks for — left for next
  time.
- A benchmark is deliberately restricted to GETs that already succeeded in the replay: it must not create or delete
  data, and failed requests have no latency worth measuring.
- `fresh_app` now accepts `None` for "every component that runs", used by `record-live` and `bench`/`screens` when
  a web app's traffic depends on an API that must also be running; `record`/`replay`/`characterize` still start
  only the one component being verified (less to reset, faster, no cross-component surprises).
