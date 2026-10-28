# 0021: Explain, Audit, Docs, Code review and Skills

Date: 2026-10-28 · Status: accepted · Phase 6 (Milestone M1)

## Context

CODEWRIGHT.md Phase 6: answers about the user's code with diagrams (`explain_code`), the As-Is audit
(`analyze_audit`), docs (`write_docs`), the correction gate (a correction becomes a `USER_FACT`), the `review_code`
playbook and the Skills system (Section 8.6). The model is a 9B model with a 4K context per request, so it can't hold a
file, let alone a project; and it can't be trusted to cite real lines or rate severity on its own. Everything must work
for any project in the five languages: GoShop is only the first test project.

## Decision

- **Explain** (`agent/chat/explain.py`), tier 0, in project chats. The Code Analyst gathers the code the question is
  about before the model writes a word, within one budget (`SOURCE_CHARS`, ~5,200 characters):
  - the names in the question that look like code, or plain words the project defines (`Login`);
  - each one's **definitions** in all five languages (functions, methods, types, classes, constants), the
    implementation before entry points (handlers, routes, ports), with the doc comment above it, cut where it ends,
    blank lines dropped, numbered; mocks, tests and generated files skipped;
  - where each is **used** (file:line), outside the code already shown;
  - for a question about a module, its **outline** and the code lines behind each dependency in the graph;
  - Graphify facts, then search hits only when nothing above was found (they would not fit in the 4K context).

  When nothing matches, the prompt says so and the model is told not to describe code it wasn't shown (no diagram
  either). The diagram is drawn here from steps the model returns as JSON, never as Mermaid it writes itself.
- **Code review** (`agent/playbooks/code_review`, `review_core.py`), tier 0, a run in project chats: scope → linters
  in the sandbox and the secret scan → Tech Lead on every file and Security Engineer on files that touch input,
  queries, files, auth or crypto, one numbered chunk at a time → report. Findings are checked, not trusted:
  - each must quote its **evidence**; a quote not found in the chunk drops the finding, and the line moves to where
    the quote really is;
  - findings that only repeat the role's own instructions are dropped; rambling problems are cut to one sentence;
  - **severity is capped by category** (style is at most a nit, error handling at most major, a bug is critical
    only when it crashes or loses data, a security finding is critical only when it names an exploit class and is
    never below major when it does);
  - findings merge only when they are the same problem on the same line (a linter or the secret scan agreeing with
    the model, or shared words); two problems on one line both stay.
  Results are cached per chunk in the run folder. Fixes are suggested, never applied (Phase 8).
- **Audit** (`agent/playbooks/audit`), tier 0 with one gate: graph → As-Is (C4, dependencies, database map,
  hotspots, computed from the code; the model names each module's job) → **Confirm As-Is** → security → quality →
  recommendations → `audit.md` + `findings.json`. A comment on the gate is parsed into facts and the As-Is is redrawn.
- **Corrections** (`agent/chat/corrections.py`): "that's wrong, X also calls Y" after an explanation or an As-Is
  becomes facts on known modules (unknown names are dropped), shown on a card; saved facts are the strongest evidence
  on the graph and go into project memory.
- **Docs** (`agent/playbooks/docs`), tier 1: facts from the code and the Language Packs → README, API, architecture
  and runbook (tables, commands, variables and diagrams generated from the facts; the model writes the prose) →
  every endpoint and file mentioned is checked → approval → a `codewright/docs-<time>` branch.
- **Skills** (`agent/skills`, `skills/builtin/`, Skills screen): a skill is a folder with `SKILL.md` (frontmatter +
  instructions); built-in (one per playbook, 23, they make the `/` menu), user (global) and project skills. Create by
  form or Markdown, `/create-skill`, or "save this as a skill" in a chat (a draft card; a drafted skill only runs a
  read-only playbook, a snippet or an answer, and keeps a language only if the user named it). Auto-use: the router's
  pick confirmed by keywords, or a strong keyword match; shown as "Using skill". Import/export as ZIP: validated,
  secret-scanned, **disabled until the user enables it**; its own auto-use setting is kept for after that.
- **Evals** (`evals/`): `explain.py` asks a project's question set through the chat API and checks each answer against
  facts taken from the source (`evals/data/explain/<project>.jsonl`); `review.py` imports a project with seeded bugs
  (`evals/repos/seeded-*`, excluded from lint and type checks) and grades `/review-code` against the expected issues
  (`evals/data/review/*.json`, lines found by code snippet). Adding a project or a language is a data file.

## Consequences

- Explain answers what the code says, not what code usually looks like; questions about things the project doesn't
  define get "not found" rather than a plausible story.
- A 9B reviewer still varies from run to run (Go: 7-9 of 9 seeded issues) and still raises about one false alarm per
  small project in code it misreads. A second-opinion check of serious findings belongs to the Verification engine
  (Phase 7).
- Code review on a large project makes many small calls (one per chunk and role); budgets are raised for it in
  `config/budgets.yaml` and it leaves one model slot free for the chat.

## Acceptance (2026-10-28, live on the running stack)

- GoShop question set (`evals/data/explain/goshop.jsonl`): **11/11** correct (was 7/11 before the context rework).
- `/review-code` on seeded issues: Python **9/9** (all with the right severity), Go **7-8/9** across runs; about one
  false alarm per run in each clean file.
- A custom skill created from a chat, exported, deleted, re-imported (disabled), enabled and then auto-used ("Using
  skill: Generate Release Notes").
- Audit on GoShop with a correction on the gate: the correction became a fact (graph and project memory, one entry
  per module pair, so a second audit updates it instead of failing) and the As-Is was redrawn. The first run showed
  169 security findings; after the fixes below, 19.
- `/docs` on GoShop: four documents, 43 endpoints, 0 problems after the check, the build ran in the sandbox, committed
  on a branch.

Fixed on the way, for every project: in code, only quoted values count as hard-coded secrets, and plain-word values
(`"x-access"`, a storage key name) are names, not secrets; secrets in test files are one minor finding per file; a
"security" finding about a type cast is a types issue; generated files (`Code generated ... DO NOT EDIT`) are neither
hotspots nor reviewed; an ORM is not a data store when the database is known; docs show commands without the
sandbox's report flags and paths; example endpoints (`/items/42`) match their route (`/items/{id}`).
