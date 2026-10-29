# 0030: New app

Date: 2026-10-29 · Status: accepted · Phase 13 (playbook; the template library is built beside it)

## Context

CODEWRIGHT.md 5.17: an idea becomes a working project, from tic-tac-toe to a clinic system, on a 9B model. The size of
the app decides how many approvals the user sees.

## Decision

- **The stack is chosen by rules, not by the model** (`new_app/stacks.py`): the app type (browser tool, site, web app
  with data, API, CLI, systems, library, script) gives the options with one recommended and a reason; the user's
  language always wins; only the five supported languages are built; a missing template falls back to the closest one
  that exists and the card says so.
- **Size = tier**: small 1 (confirm card in chat, then the app), medium 2 (requirements and design are one plan), large 3
  (four gates: requirements, design, screens, the app). The size comes from the confirmed card, else the words of the
  request.
- **A new app is built in its own project**, created at the scaffold step (`RunServices.create_project`), so Preview,
  Tests and every other playbook work on it during the run and afterwards. A run cancelled or rejected before
  publish leaves a draft project that can be deleted; nothing outside it is touched.
- **The template does the heavy lifting**: scaffold, tests, GUIDE skeleton and Graphify setup come with it; the model
  plans at most 8 files inside the template's extension points and writes them one at a time, each seeing what the
  earlier ones declare (the same build loop as Add a feature). Failing files are fixed within the Reflection budget.
- **Honest results**: a red build is shown red in the result card, with the files that could not be written; nothing
  is hidden so the card looks green. The guide's "how to run" comes from the template manifest, not the model.

## Consequences

Predictable stacks and small, template-sized plans. The M3 acceptance (10 small + 5 medium apps, the inventory and
clinic apps) still needs live runs on the GPU model; none has been done. Images and a dev server are started from the
project's Preview tab, not by this playbook.
