# 0029: Architecture change I: design for every target, clean modules and modular monolith for real

Date: 2026-10-29 · Status: accepted · Phase 15

## Context

CODEWRIGHT.md 5.18 and Phase 15: recommend an architecture ("what should this be?"), design the To-Be for any target
with a "why this shape" explanation, a decomposition engine with rules, scores, alternatives and editing, a Language
Advisor, and the simpler targets end to end (clean modules / layers, modular monolith) with incremental moves,
import-boundary rules and replay verification. The `architecture_change` playbook was a microservices skeleton with
simulated steps. The model is a 9B one with a 4K context: it cannot restructure a codebase by rewriting files, and a
layout it invents is not checkable.

## Decision

- **The graph decides, the model names.** `agent/decomposition/` is plain, deterministic Python on the module graph
  (`agent/knowledge_graph`). The model is asked for one thing: a short name and a one-sentence purpose per group
  (optional, `use_llm`); a duplicate, invalid or out-of-range name is ignored. Everything else is reproducible.
- **Engine** (`engine.py`). Weighted module graph `w = a·static + b·runtime + c·shared_table_writes + d·co_change`
  (each log-scaled so one huge edge cannot dominate; runtime and table evidence plug in through the edges' `sources`
  as they are added, co-change and the user's facts already do). Louvain communities at four resolutions (own
  implementation: deterministic, no new dependency). Rules applied until none fires, each merge logged with its
  reason: one frontend, one owner per table (from the SQL in the code), no synchronous cycles (a strongly connected
  component is merged), chatty pairs merged (each sends the other at least 75% of its traffic), no nano-services.
  Scores: modularity, balance and size fit, as one 0-100 number (a heuristic for comparing alternatives, not a
  quality claim). Alternatives are the distinct designs from the other resolutions, each with why it was not chosen.
- **Editing re-validates.** `edit_design` applies move / merge / split / rename and recomputes everything; an edit is
  not undone by the rules, what it breaks is listed as a violation (cycle, shared table, chatty pair, nano). At the
  approval the user types the edit in words ("move payment to order", "merge user and product", "rename order to
  checkout", "split db out of product"); `parse_edits` turns it into edits, and a sentence that is not an edit is
  answered ("write it like ..."), not ignored. The cards only carry a comment today, so words are the interface.
- **Recommendation** (`recommend.py`). Each target gets a fit 0-10 with reasons; the simplest target wins ties.
  Microservices need a stated reason (scale, team autonomy) AND a graph that splits cleanly, and fewer than 8
  modules costs points (network and deployment cost); the "why not microservices" reason is always shown when something simpler is recommended.
- **Layers** (`layers.py`) for "clean modules": modules are placed in interface / application / infrastructure /
  domain by name; a dependency pointing outward is a violation. Unplaced modules are listed for the user to correct.
- **Language Advisor** (`languages.py`): workload from module names, fit table per language, **keep the original by
  default**; a switch needs a gap that grows with the size of the code to rewrite. Mode is extract or translate.
- **Platform proposals** (`platform.py`): gateway routes, events for fan-out services, sagas with compensations for
  work spanning services. These are derived from the design's calls and are proposals the user edits at Gate 3.
- **Boundaries as a ratchet** (`boundaries.py`). Rules go into the project (`architecture/boundaries.json`) with a
  stdlib-only checker copied next to them (`architecture/check_boundaries.py`, exit 1 on a new violation, `--update`
  to accept the state). Existing violations are recorded as `known` debt: only new ones fail, so the rules can be
  adopted by a project that does not yet obey them. Imports are resolved for Python, TypeScript/JavaScript (relative
  paths), Go (import path suffix) and C++ (quoted includes); what cannot be resolved to a project file is ignored,
  never guessed. Modular monolith rules: allowed dependencies come from the approved design's calls, other modules
  may import only a module's public entry (`__init__.py`, `index.*`, `api.*`), and writing another module's table is
  a violation. Layer rules: outward dependencies.
- **Moves are mechanical** (`moves.py`). A file only one other module uses is moved into that module; an import that
  reaches into a module's internals is pointed at its public entry. Python and TypeScript/JavaScript moves rewrite
  every import (relative ones become absolute where needed; a `import a.b` without alias is refused rather than
  guessed). Each move is one commit, the tests run after it, and a red move is restored exactly. At most 8 per run.
  Go and C++ get the design and the rules; their moves need the compiler, so they are listed as not applied.
- **Flow.** `intake → baseline → As-Is → To-Be → [languages for service designs] → (audit: report | conversion:
  restructure → verify → approve result → report) → delivery`. The conversion needs green tests to begin with (else
  only the rules are written, a ratchet), records the app's traffic first, and replays it at the end (0 regressions
  or the card says so; no recording means the card says the tests are the only proof). Verify also re-checks the
  boundaries and compares the graph before and after.
- **Microservices stay simulated for conversion** (`simulate`, Phases 16-17); their design (audit) is real. A
  conversion to serverless, event-driven or merge is refused up front: they are designed now, built later.
- Inputs: `target` gains `recommend`; new `request` (goals), `allowed_languages` and `simulate`. A real run needs a
  project (`PlaybookSpec.needs_project_for`); the chat maps the user's words to a target.

## Consequences

- A 9B model cannot break a design: the engine is rules on the graph. The model's only influence is names.
- The design quality depends on the graph: runtime calls and table reads/writes arrive with the baseline recorders of
  Phase 16; until then co-change, static dependencies and the SQL scan carry the weights.
- Moves are conservative. A project whose cross-module imports are all `import a.b.c` without alias, or in Go/C++,
  gets rules and a report but few or no moves. That is the price of never rewriting code with a model here.

## Not demonstrated yet

- The Python benchmark restructured into a modular monolith with 0 replay regressions: the replay path is tested with
  a fake replay; no real benchmark was run (disk, and no running app in the test environment).
- GoShop as a ~5-service design: tested on a GoShop-shaped graph (five domains, a shared db package, a React
  frontend) that gives four backend groups plus the frontend; not run on the real GoShop import.
