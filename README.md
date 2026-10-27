# Codewright

**A self-hosted AI software house in a chat app.**
You chat with Codewright the way you chat with Claude or ChatGPT. Behind the chat, a team of 15 AI roles (project manager, architects, developers, QA, DevOps, security, designers and more) does real software work on your code. It can create new projects, explain, fix, refactor, speed up, secure, upgrade and extend existing ones, and convert monoliths into microservices. It proves its work with tests and asks for your approval before changing anything.

---

## 0. Instructions for the building agent: read this first

You (the coding agent) are implementing Codewright from this document.

### 0.1 Confirm before you build
1. Read this **whole** README before doing anything.
2. Reply with:
   - a short summary of what you will build
   - the confirmed decisions (0.4), restated in your own words
   - your plan for the **verification checklist** (0.3)
   - the **Phase 0 reconciliation** report (0.5)
   - every assumption you are making
   - anything unclear, contradictory or missing
3. **Wait for the user to reply "go".** Do not create, change or delete files, install packages or run commands before that.
4. If anything is unclear at any time, **ask**. Don't guess.

### 0.2 How to work
- Build **one roadmap phase at a time** (Section 15). At the end of each phase:
  - run its acceptance checks
  - show the user what was built, how to run and try it, and the test results
  - update `PROGRESS.md`
  - wait for "next"
- Write tests with the code. A phase is not done until its tests pass.
- Record significant technical decisions as ADRs in `docs/adr/NNNN-title.md`.
- Check the **current official documentation** (LangGraph, LangChain, `deepagents`, Graphify, Ollama, llama.cpp, Next.js, FastAPI) before using an API. Don't rely on memory.
- Never hard-code secrets. Use `.env` with a documented `.env.example`.
- Commit in small, clear steps.
- If something in this README is wrong or impossible, stop, explain, propose options, and wait.

### 0.3 Verification checklist
| # | Verify | If different |
|---|---|---|
| V1 | **Qwen3.5 9B** exists as a **Q4_K_M** GGUF for Ollama/llama.cpp and fits a **10 GB** GPU at the planned context size | Tell the user, propose the closest ~9B coding-capable model, and record it in an ADR |
| V2 | **Graphify** (https://github.com/safishamsi/graphify): PyPI package (`graphifyy`), CLI (`graphify`), license, output files, MCP tools (`query_graph`, `get_node`, `shortest_path`, `get_pr_impact`), Postgres schema extraction | Adapt the integration; tell the user about gaps |
| V3 | Current `deepagents` and LangGraph APIs: sub-agents, file system, `interrupt()`, Postgres checkpointer, streaming | Adapt; record in an ADR |
| V4 | Google Drive access for a single local user (OAuth desktop flow) | Propose the simplest working method |
| V5 | Name: no conflict with an existing product called "Codewright" in a way that matters | Tell the user before branding work starts |

### 0.4 Decisions confirmed by the user
| # | Decision |
|---|---|
| C1 | **Name:** Codewright. It replaces the earlier name "MonoShift"; monolith-to-microservices is now one capability of Codewright. |
| C2 | **Product shape:** a **Claude-type chat app** (Section 2). The user chats; the team works behind the chat. |
| C3 | **Scope:** anything software-related (Section 1.2): general software Q&A, creating new projects, and improving existing ones. Non-software requests are politely declined. |
| C4 | **Team:** 15 agents + 46 sub-agent types, organized like a software house (Section 6). The user is the client. |
| C5 | **Approvals scale with risk:** tiers 0–3 (Section 3.2). |
| C6 | **Users:** single user, running locally. No login. |
| C7 | **Delivery:** Codewright **asks** where to deliver: local folder, GitHub, ZIP download or Google Drive (one or more). |
| C8 | **LLM:** self-hosted **Qwen3.5 9B (Q4_K_M)** with two switchable profiles: (1) remote **RTX 3080 10 GB**, (2) **local CPU**. |
| C9 | **Graphify:** the code-understanding engine; the live graph in the app; before/after graphs for changes; set up inside every generated or converted service/project. |
| C10 | **Framework:** LangGraph + LangChain + `deepagents`. |
| C11 | **Modern UI:** both Codewright's own app and any frontend it builds or modernizes. |
| C12 | **Languages:** the architecture supports any language. Language Packs come in waves: Go + Python → Java + TypeScript/Node → PHP + .NET. |
| C13 | **Benchmark repo:** GoShop: https://github.com/quangdangfit/goshop (Go + React, PostgreSQL, Redis). |
| C14 | **One roadmap** (Section 15), no separate versions. |

### 0.5 Phase 0 is already in progress
The user started Phase 0 using an **earlier version** of this README (named "MonoShift"; focused only on monolith → microservices). Before changing anything:
1. Inspect the existing repository.
2. Report, as a table:
   - what is **done** and still valid
   - what is **missing** for the new Phase 0 (Section 15)
   - what **conflicts** with this README, for example:
     - the name "MonoShift" in code, configs or docs
     - services this README no longer uses (Neo4j, Redis, MinIO)
     - a dashboard-only UI instead of a chat UI
3. Propose the changes (rename, removals, additions), with their effort.
4. **Wait for approval.** Never delete the user's work without explicit confirmation.

---

## 1. Product overview

### 1.1 What Codewright is
- A **chat app** that looks and feels like the Claude app (Section 2).
- Behind the chat: an **AI software house** of 15 roles, each with its own job, tools and instructions.
- Works on **your real code**: connected projects (GitHub, ZIP, Google Drive, local folder) or brand-new projects it creates.
- **Self-hosted and private:** the AI model runs on your own GPU server or your own computer. Code never leaves your machines by default.
- **Proves its work:** tests, traffic replay and benchmarks show that changes do what they should and break nothing.
- **You stay in control:** approval cards in the chat before anything risky happens.

### 1.2 What Codewright can do
| Area | Examples of what you can ask |
|---|---|
| **Ask anything about software** | "What's a saga pattern?", "Python or Go for an API?", "Review this snippet" (no project needed) |
| **Understand code** | "How does checkout work?", "Draw my architecture", "Audit this codebase" |
| **Fix** | "Login returns 500", "Fix this stack trace" (with an uploaded log/screenshot) |
| **Improve** | "Refactor the payment module", "Checkout is slow, speed it up" |
| **Quality** | "Write tests for orders", "Is my code secure? Fix the issues" |
| **Maintain** | "Upgrade to Go 1.26 / Django 5", "Add an index", "Migrate MySQL → PostgreSQL" |
| **Extend** | "Add a wishlist feature", "Add Stripe payments" |
| **Frontend** | "Move to Next.js", "Make the UI modern and accessible" |
| **Create** | "Create a clinic appointment booking app", "Build an inventory system for my shop" |
| **Modernize architecture** | "Convert this monolith to microservices", "Rewrite this service in Python" |
| **Ship** | "Dockerize this", "Set up CI/CD", "Prepare it for deployment" |
| **Document** | "Write API docs", "Explain this project for a new developer" |

Out of scope: non-software requests (politely declined), and touching **production** systems (everything runs in a sandbox until you approve delivery).

### 1.3 Principles
| Principle | Meaning |
|---|---|
| **Chat first** | Everything starts from a conversation; the app shows plans, progress and results inline |
| **Human in control** | Approvals scale with risk; nothing irreversible happens without the user |
| **Prove, don't promise** | Every change is verified (tests, replay, benchmarks) before it's offered |
| **Small-model first** | Designed for a ~9B local model: tools, algorithms and templates first; small scoped LLM tasks |
| **Language-neutral core** | Graphify + Language Packs + a common knowledge graph |
| **Honest advice** | Says plainly when something isn't worth doing (e.g. "don't split this into microservices") |
| **Private** | Self-hosted model; no external APIs by default |

---

## 2. The app: a Claude-type chat app

### 2.1 Layout
```
┌──────────────┬──────────────────────────────────┬─────────────────────┐
│ Sidebar      │ Chat                             │ Side panel          │
│              │                                  │ (artifacts)         │
│ + New chat   │ Project: GoShop · Refactor payment│ [Plan][Diff][Graph] │
│              │                                  │ [Diagram][Tests]    │
│ Projects     │ You: Refactor the payment module │ [Preview][Report]   │
│  GoShop      │                                  │                     │
│  Clinic app  │ Codewright: Got it. Plan:        │ - func Process(o)   │
│              │  ✓ Code analyst mapped payment   │ + func Charge(o)    │
│ Chats        │  ✓ QA wrote 14 tests             │ + func Refund(o)    │
│  Refactor…   │  … Backend dev refactoring       │                     │
│  Explain…    │                                  │ ✓ 14/14 tests pass  │
│  Fix login…  │ ┌ Approval needed ─────────────┐ │ ✓ Replay: 0 diffs   │
│              │ │ Split processor.go into 3    │ │                     │
│              │ │ [Approve] [Edit] [Reject]    │ │ Team: PM · Analyst  │
│ GPU · Qwen9B │ └──────────────────────────────┘ │ QA · Dev · Tech lead│
│ ⚙ Settings   │ [ Ask Codewright to build…  ↑ ]  │                     │
└──────────────┴──────────────────────────────────┴─────────────────────┘
```

### 2.2 Features (Claude app → Codewright)
| Feature | Codewright behavior |
|---|---|
| Streaming chat | Token-by-token replies from the Project Manager agent |
| Conversations | List, search, rename, delete, pin |
| Projects | Connected codebases + project instructions + project memory; each chat belongs to a project, or to none for general Q&A |
| Uploads | Files, screenshots, logs, specs, ZIPs; attached to the chat or the project |
| Side panel (artifacts) | Tabs: **Plan**, **Diff**, **Graph** (live Graphify), **Diagram** (Mermaid/C4), **Tests** (tests/replay/benchmarks), **Preview** (running app from the sandbox), **Report** |
| Edit / regenerate / branch | Edit a past message, regenerate a reply, branch a conversation |
| Stop | Stops the current reply or run (checkpointed, resumable) |
| Team activity | Like Claude's tool-use display: an expandable feed of which agent/sub-agent is doing what |
| Plan checklist | Live to-do list for each request, updated as work progresses |
| Approval cards | Inline **Approve / Edit / Reject** cards, with what, why, alternatives and risk |
| Memory | Project memory (decisions, conventions, lessons) + user preferences; viewable and editable |
| Model picker | LLM profile: remote GPU / local CPU, with a health indicator |
| Rendering | Markdown, syntax-highlighted code with copy, Mermaid diagrams, tables |
| Delivery | "Deliver" card: GitHub PR, local folder, ZIP or Google Drive |
| Settings | LLM profiles, budgets, GitHub token, Google Drive, allowed folders, theme |
| Theme | Dark/light, responsive, keyboard shortcuts, WCAG 2.2 AA |

### 2.3 Screens
| Screen | Purpose |
|---|---|
| **Chat** (main) | Sidebar + chat + side panel, as above |
| **Project home** | Project overview: stack, graph, recent chats, memory, connected source, delivery targets |
| **New project** | Connect existing code (GitHub / ZIP / Drive / local) or start empty ("create from chat") |
| **Graph explorer** (full screen) | Interactive Graphify graph with filters and node details; As-Is/To-Be coloring |
| **Run detail** | Deep view of a long run (e.g. microservices): step timeline, service board, DB split stages, replay results |
| **Team** | The 15 roles as an org chart, with current tasks |
| **Settings** | As above |

Design: clean and modern, the Claude-like feel (calm, generous whitespace, serif or soft type for assistant replies optional), shadcn/ui + tokens, dark/light, accessible.

---

## 3. How a request flows

### 3.1 Flow
```mermaid
flowchart TD
    M["User message<br/>(+ files, project)"] --> R["Intent Router<br/>intent + tier + playbook"]
    R -- unclear --> Q["Clarifier asks questions"]
    Q --> R
    R -- "tier 0" --> A0["Answer directly<br/>(graph + code search)"]
    R -- "tier 1-3" --> P["Planner: plan shown in chat"]
    P -- "tier 2-3" --> G1{{"Approve plan"}}
    P -- "tier 1" --> W
    G1 --> W["Playbook runs<br/>role agents + sub-agents"]
    W --> V["Verification<br/>tests / replay / benchmarks"]
    V -- fail --> F["Reflection: fix + retry"]
    F --> V
    V -- pass --> RV["Tech Lead + Security review"]
    RV --> G2{{"Approve result"}}
    G2 --> D["Delivery<br/>ask where: GitHub / local / ZIP / Drive"]
```

### 3.2 Risk tiers (how many approvals)
| Tier | Meaning | Examples | Approvals |
|---|---|---|---|
| **0** | Answer only, no code changes | explain, Q&A, audit report | None |
| **1** | Small, contained change | bug fix, tests, docs, small security fix | One: the result (diff + verification) |
| **2** | Medium change | refactor, performance, upgrade, DB change, feature, frontend migration, DevOps | Plan + result |
| **3** | Large change | new app, microservices conversion, language translation | Multiple gates (defined per playbook) |

The router proposes a tier; the user can always raise it ("ask me before every step"). Destructive actions always need confirmation, whatever the tier.

### 3.3 Mixed and multi-step requests
"Fix this bug and add tests" → the Project Manager splits it into steps (fix_bug, then write_tests) and shows one combined plan. Long requests run in the background; the chat shows progress, and the user can keep chatting.

---

## 4. Intents (18)
| # | Intent | Example | Tier | Lead agent | Playbook |
|---|---|---|---|---|---|
| 1 | `general_help` | "What's a saga?", "What can you do?" | 0 | Project Manager | Answer |
| 2 | `project_manage` | "Connect my GoShop repo", "status?", "deliver to GitHub" | 0 | Project Manager | Project ops |
| 3 | `explain_code` | "How does checkout work?" | 0 | Code Analyst | Explain |
| 4 | `analyze_audit` | "Audit my architecture" | 0 | Solution Architect | Audit |
| 5 | `write_docs` | "Document this API" | 1 | Technical Writer | Docs |
| 6 | `write_tests` | "Add tests for orders" | 1 | QA Engineer | Tests |
| 7 | `fix_bug` | "Login fails with 500" | 1 | Backend Developer | Bug fix |
| 8 | `security_review` | "Is my code secure? Fix it" | 1–2 | Security Engineer | Security |
| 9 | `refactor` | "Refactor payment" | 2 | Backend Developer | Refactor |
| 10 | `improve_performance` | "Checkout is slow" | 2 | Backend Developer | Performance |
| 11 | `upgrade` | "Upgrade to Django 5" | 2 | Backend Developer | Upgrade |
| 12 | `database_change` | "Add an index", "MySQL → Postgres" | 2 | Database Engineer | DB change |
| 13 | `add_feature` | "Add a wishlist" | 2 | Product Manager | Feature |
| 14 | `frontend_modernize` | "Move to Next.js", "modern UI" | 2 | Frontend Developer | Frontend |
| 15 | `devops_deploy` | "Dockerize + CI/CD" | 2 | DevOps Engineer | DevOps |
| 16 | `translate_language` | "Rewrite notifications in Python" | 3 | Backend Developer | Translate |
| 17 | `convert_microservices` | "Convert to microservices" | 3 | Solution Architect | Microservices |
| 18 | `new_app` | "Create a clinic booking app" | 3 | Product Manager | New app |

The Intent Router returns structured JSON:
```json
{"intent": "refactor", "tier": 2, "project_id": "goshop", "targets": ["internal/payment"], "clarifying_questions": [], "confidence": 0.86}
```
- If `confidence` is low, it asks.
- If the request isn't about software, it politely declines.
- Fuzzy requests ("make my app better") get one or two clarifying questions, then a proposed plan.

---

## 5. Playbooks

Every playbook defines: **steps**, **roles**, **verification**, **approvals**, and **outputs**. Playbooks live in `agent/playbooks/<name>/` as a LangGraph subgraph + config, so new ones can be added without touching the core.

### 5.1 Answer (`general_help`), tier 0
Project Manager answers directly. Uses code search / graph if a project is attached. No tools that change anything.

### 5.2 Project ops (`project_manage`), tier 0
Connect or import a project, show status, list chats/runs, change settings, run delivery. Uses the connectors.

### 5.3 Explain (`explain_code`), tier 0
1. Code Analyst queries Graphify (path, explain, neighbors) + code search.
2. Answer in chat + a diagram (flow or sequence) in the side panel + the graph highlighted.

### 5.4 Audit (`analyze_audit`), tier 0
1. Ensure the project graph is fresh (Graphify + enrichment).
2. As-Is architecture (Section 7 of the microservices playbook: C4, dependencies, DB map, hotspots).
3. Security Engineer: secret and dependency scan. Tech Lead: code-quality findings.
4. Report: findings, risks, recommendations (incl. whether microservices are worth it, and how many services), effort estimate.
5. Output: audit report + diagrams + graph, deliverable anywhere.

### 5.5 Docs (`write_docs`), tier 1
Technical Writer + Code Analyst generate README, API docs, architecture docs and a runbook, verified against the code (endpoints exist, examples run where possible). One approval on the result.

### 5.6 Tests (`write_tests`), tier 1
1. QA picks targets (module/endpoints), with Test Writer sub-agents ×K.
2. Generate characterization/unit/integration tests.
3. Run them in the sandbox. Coverage before → after.
4. Approve the result (tests + coverage report).

### 5.7 Bug fix (`fix_bug`), tier 1
1. Understand: the error, logs, screenshots, steps (Clarifier asks if needed).
2. **Reproduce** with a failing test (QA). If it can't be reproduced, report that and ask.
3. Locate the cause (graph + code search + Diff Analyzer).
4. Fix (Backend Developer / Code Writer), smallest change possible.
5. Verify: the new test passes, and all existing tests + replay still pass.
6. Tech Lead review → approve the result → deliver.

### 5.8 Security (`security_review`), tier 1–2
1. Secret Scanner, Dependency Auditor, Auth Reviewer, plus static checks.
2. Findings report with severity.
3. Fixes for chosen findings: low-risk ones are tier 1, risky ones tier 2 (plan first).
4. Verify: tests + replay unchanged; scanners clean for the fixed items.

### 5.9 Refactor (`refactor`), tier 2
1. Map the target (graph) + characterization tests (QA) + record traffic if the app runs.
2. Refactor plan (Solution Architect / Tech Lead) → **approve plan**.
3. Refactor in small steps, tests after each step (sandbox).
4. Verify: tests + replay = **identical behavior**; before/after graph for the module.
5. Review → **approve result** → deliver.

### 5.10 Performance (`improve_performance`), tier 2
1. Baseline benchmark (k6 / profiler / DB query analysis).
2. Find bottlenecks (QA Load Tester + DB Engineer + Code Analyst).
3. Plan → approve.
4. Fix (code, queries, indexes, caching).
5. Verify: behavior unchanged (tests + replay) and performance improved (before/after numbers).
6. Approve the result.

### 5.11 Upgrade (`upgrade`), tier 2
1. Read the release notes / migration guides of the target version (docs search).
2. Plan the breaking changes → approve.
3. Upgrade step by step (dependencies, code changes); build/test after each step.
4. Verify: tests + replay unchanged. Approve the result.

### 5.12 DB change (`database_change`), tier 2
Database Engineer: plan (migration + rollback scripts + data checks) → approve → apply in the sandbox → verify (tests, counts/checksums, query plans) → approve. Engine migrations (e.g. MySQL → PostgreSQL) add data migration and verification stages.

### 5.13 Feature (`add_feature`), tier 2
1. Product Manager: user stories + acceptance criteria (asks questions).
2. Solution Architect: design (where it fits, API, data, UI) → **approve plan**.
3. UI/UX Designer: screen designs if there's UI → previews.
4. Backend + Frontend Developers build; QA writes tests from the acceptance criteria.
5. Verify: new tests pass, old tests + replay unchanged; Preview in the side panel.
6. Review → approve the result → deliver.

### 5.14 Frontend (`frontend_modernize`), tier 2
Rewire to APIs/gateway → framework migration page by page (parity first: Playwright + screenshot similarity) → modernization by the UI/UX Designer (design system, responsive, WCAG 2.2 AA) as a separate step with before/after previews → approve.

### 5.15 DevOps (`devops_deploy`), tier 2
DevOps Engineer: Dockerfiles, Compose, CI/CD, optional Kubernetes/cloud manifests, observability. Security Engineer reviews. Verify: images build, the app starts, CI passes in the sandbox. Approve.

### 5.16 Translate (`translate_language`), tier 3
Spec-first:
1. Contract + black-box tests + recorded traffic.
2. Language Advisor confirms that the change is worth it → **approve**.
3. Generate in the new language one function at a time, with compile/test feedback.
4. Verify with the **same** tests + replay → approve the result.

### 5.17 New app (`new_app`), tier 3
Turns a business problem into a working project.

```mermaid
flowchart TD
    A["User: 'Create a clinic booking app'"] --> B["Product Manager: questions<br/>users, core features, platform, constraints"]
    B --> C["PRD + user stories + MVP scope"]
    C --> G1{{"Gate: approve requirements"}}
    G1 --> D["Solution Architect: architecture<br/>simple app or 1 frontend + N services,<br/>stack, data model, APIs"]
    D --> G2{{"Gate: approve design"}}
    G2 --> E["UI/UX Designer: screens + design system"]
    E --> G3{{"Gate: approve screens"}}
    G3 --> F["Pick template from library + scaffold<br/>(DevOps + Backend + Frontend)"]
    F --> H["Build feature by feature<br/>tests from acceptance criteria (QA)"]
    H --> I["Run in sandbox: Preview tab"]
    I --> J["Security + Tech Lead review"]
    J --> G4{{"Gate: approve app"}}
    G4 --> K["Docs + Graphify graph"]
    K --> L["Delivery: ask where"]
```

- **Architecture honesty:** a small app gets a **simple, well-structured app**, not microservices. Microservices are proposed only when the requirements justify them.
- **Template library** (`templates/apps/`): ready, tested starters (e.g. FastAPI + Next.js, Go + Next.js; auth, CRUD, admin, Docker, tests, CI, Graphify setup). Codewright fills in the domain-specific parts in small steps. Essential for a 9B model.
- **MVP first:** big requests are scoped to an MVP, then grown feature by feature through `add_feature`.
- After delivery the project appears in **Projects**, and every other playbook works on it.

### 5.18 Microservices (`convert_microservices`), tier 3
The most detailed playbook. **Output shape:** **one frontend** + **N backend microservices** behind an API gateway, with a message broker; one Backend Developer per service.

```mermaid
flowchart TD
    A["1. Intake: goals, constraints"] --> G1{{"Gate 1: confirm goals"}}
    G1 --> B["2. Baseline: run app, record traffic, tests"]
    B --> C["3. As-Is architecture: graph, DB map, diagrams"]
    C --> G2{{"Gate 2: confirm As-Is"}}
    G2 -- corrections --> C
    G2 --> D["4. To-Be: 1 frontend + N services, why"]
    D --> G3{{"Gate 3: approve design"}}
    G3 -- edits --> D
    G3 --> E["5. Language per service"]
    E --> G4{{"Gate 4: pick languages"}}
    G4 -- "audit only" --> AR["Audit report"]
    G4 -- conversion --> F["6. Foundation: gateway, broker, auth, CI"]
    F --> H["7. Build each service (1 dev per service)"]
    H --> G5{{"Gate 5: approve service PR"}}
    G5 -- next --> H
    G5 -- done --> I["8. Database split: schemas, outbox, sagas"]
    I --> G6{{"Gate 6: approve split"}}
    G6 --> J["9. One frontend + modern UI"]
    J --> G7{{"Gate 7: approve UI"}}
    G7 --> K["10. Report + before/after graphs"]
    K --> G8{{"Gate 8: delivery location"}}
```

**Step details:**
1. **Intake:**
   - stack detection
   - goals (scale, team autonomy, cost, modernization)
   - allowed languages
   - deployment target
   - constraints
   - frontend choice
   - delivery
2. **Baseline:**
   - run the monolith in the sandbox
   - characterization tests per endpoint
   - mitmproxy recording of user journeys
   - runtime profiling (OpenTelemetry + DB query logs)
   - k6 performance baseline
3. **As-Is:**
   - Graphify graph (code + SQL + live Postgres schema) + enrichment (runtime calls, table reads/writes, git co-change, endpoints/events)
   - C4 L1–L3, dependency diagram, DB ownership map, key flows, coupling hotspots
   - user corrections become `USER_FACT` edges
4. **To-Be:**
   - weighted module graph: `w = a·static_calls + b·runtime_calls + c·shared_table_writes + d·co_change`
   - community detection (Leiden/Louvain) at several resolutions
   - LLM names and justifies the groups
   - **rules:**
     - one owner per table
     - no sync cycles
     - chatty pairs merged
     - strong consistency kept inside one service
     - no nano-services
     - **one frontend**
   - scores per service
   - per-service design: API, events, data
   - platform: gateway, NATS/RabbitMQ, JWT auth, sagas, observability
   - "Why N services" + alternatives
   - the user edits on the graph
5. **Languages:**
   - service profile → rule-based scoring → explanation
   - **default: keep the original language**
   - mode per service: Extract (same language) or Translate (new language)
6. **Foundation:**
   - output layout (`frontend/`, `services/<name>/`, `gateway/`, `platform/`, `libs/`, `deploy/`, `docs/`)
   - gateway routing everything to the monolith first (Strangler Fig)
   - broker + event envelope
   - JWT middleware
   - OpenTelemetry + Jaeger
   - CI templates
   - replay must still pass 100%
7. **Per-service loop** (least-coupled first; GoShop: Notification → Payment → User → Catalog → Order):
   - spec (contract + black-box tests + traffic subset)
   - scaffold (incl. Graphify setup)
   - extract / translate
   - boundaries: clients/events in the service; an **anti-corruption layer** in the monolith
   - own schema
   - unit + contract tests (Schemathesis, buf/Pact)
   - sandbox deploy
   - **shadow traffic**
   - **replay diff = 0 regressions**
   - reflect/fix (max 5 loops, then escalate)
   - Tech Lead (fresh context) + Security review
   - Graphify the service → PR → **Gate 5**
   - Release Manager canary cut-over (10 → 50 → 100%), then the code is removed from the monolith

   Parallel when independent, limited by `max_parallel_llm_jobs`.
8. **DB split:**
   - schema per service + DB user
   - break cross-service FKs (add snapshots)
   - API composition / read models
   - outbox + idempotent consumers
   - **sagas with compensation**, e.g. order → reserve stock → payment → paid/cancelled
   - optional separate DB instances with count/checksum verification
   - Gate 6 before risky stages, with migration + rollback scripts
9. **Frontend:** the frontend playbook (5.14) against the gateway.
10. **Report:**
    - C4 before/after
    - service, event and saga catalogs
    - ADRs, API docs, runbook
    - **before/after Graphify graphs + `COMPARISON.md`**
    - migration report (replay %, tests, performance, risks)
    - Gate 8: delivery location

**Behavior verification (used by refactor, upgrade, security, microservices, translate):**
- replay recorded traffic per journey with a state reset
- compare status, selected headers, and the body as semantic JSON
- noise rules (IDs, timestamps, tokens, unordered arrays, float tolerance), visible to the user
- each diff is classified as **regression / noise / intended**
- accept only with 0 regressions

---

## 6. The team: 15 agents, 46 sub-agent types

You are the **client**. All agents use the same model; they differ in instructions, tools and context. Sub-agents are short-lived helpers for one small job with a clean context (marked ×N when created per item).

```mermaid
flowchart TD
    CL["Client (you)"] --> PM["1 Project Manager"]
    PM --> M["Management"]
    PM --> AR["Architecture"]
    PM --> EN["Engineering"]
    PM --> QO["Quality and ops"]
    PM --> DE["Delivery"]
    M --> BA["2 Business Analyst"]
    M --> PDM["3 Product Manager"]
    AR --> SA["4 Solution Architect"]
    AR --> TL["5 Tech Lead"]
    EN --> CA["6 Code Analyst"]
    EN --> DB["7 Database Engineer"]
    EN --> BE["8 Backend Developer ×N"]
    EN --> FE["9 Frontend Developer"]
    EN --> UX["10 UI/UX Designer"]
    QO --> QA["11 QA Engineer"]
    QO --> DO["12 DevOps / Cloud Engineer"]
    QO --> SE["13 Security Engineer"]
    DE --> RM["14 Release Manager"]
    DE --> TW["15 Technical Writer"]
```

### 6.1 Agents and sub-agents
| # | Agent | Responsibilities | Sub-agents |
|---|---|---|---|
| 1 | **Project Manager** (main agent) | Talks to the user; routes intents; plans; assigns; tracks; budgets; runs approvals; reports | Intent Classifier · Clarifier · Status Reporter |
| 2 | **Business Analyst** | Understands the project and constraints: stack, goals, environment, delivery | Stack Detector · Requirements Interviewer |
| 3 | **Product Manager** | Business problems and feature ideas → requirements, stories, MVP scope | PRD Writer · User Story Writer · Scope Prioritizer |
| 4 | **Solution Architect** | Architecture (As-Is, To-Be, new apps), service boundaries, stack and language advice | As-Is Modeler · To-Be Designer · Language Advisor · Diagram Generator |
| 5 | **Tech Lead** | Quality gatekeeper; reviews every change in a fresh context; standards | Fresh Reviewer ×N · Standards Checker |
| 6 | **Code Analyst** | Runs Graphify; builds/enriches the knowledge graph; explains code; finds hotspots | Module Summarizer ×M · Dependency Mapper · Hotspot Finder |
| 7 | **Database Engineer** | Data model, ownership, migrations, indexes, DB split, outbox, sagas | Schema Mapper · Migration Writer · Saga Designer |
| 8 | **Backend Developer ×N** | Writes and changes backend code: fixes, refactors, features, services, upgrades, translations | Code Writer · Boundary Builder · Fixer |
| 9 | **Frontend Developer** | The frontend: features, API wiring, framework migration | Page Migrator ×P · API Client Generator |
| 10 | **UI/UX Designer** | Screen designs, design system, modern UI, accessibility, previews | Design System Builder · Screen Redesigner ×S · Accessibility Checker |
| 11 | **QA Engineer** | Proves behavior: unit, characterization, contract, replay, E2E, load | Test Writer ×K · Traffic Recorder · Diff Analyzer · E2E Tester · Load Tester |
| 12 | **DevOps / Cloud Engineer** | Sandbox, Docker, CI/CD, gateway, broker, K8s, observability, previews | Sandbox Operator · Containerizer · CI Builder · Infra Generator |
| 13 | **Security Engineer** | Secrets, dependencies, auth, input validation, service security | Secret Scanner · Dependency Auditor · Auth Reviewer |
| 14 | **Release Manager** | PRs, cut-over (canary, rollback), delivery to the chosen locations | PR Creator · Cut-over Controller · Delivery Agent |
| 15 | **Technical Writer** | Docs, diagrams, reports, before/after graph comparisons | Doc Writer · Graph Comparator · Report Builder |

**Totals:** 15 agents · 46 sub-agent types · instances as needed.

### 6.2 Who works on which playbook
| Playbook | Lead | Main helpers |
|---|---|---|
| Answer / Project ops | Project Manager | Business Analyst, Release Manager |
| Explain | Code Analyst | Solution Architect |
| Audit | Solution Architect | Code Analyst, DB Engineer, Security, Tech Lead, Technical Writer |
| Docs | Technical Writer | Code Analyst |
| Tests | QA Engineer | Code Analyst, Backend Developer |
| Bug fix | Backend Developer | QA, Code Analyst, Tech Lead |
| Security | Security Engineer | Backend Developer, Tech Lead |
| Refactor / Performance / Upgrade | Backend Developer | Code Analyst, QA, DB Engineer, Solution Architect, Tech Lead |
| DB change | Database Engineer | Backend Developer, QA |
| Feature | Product Manager | Solution Architect, Backend, Frontend, UI/UX, QA, Tech Lead |
| Frontend | Frontend Developer | UI/UX Designer, QA |
| DevOps | DevOps Engineer | Security, Release Manager |
| Translate | Backend Developer | Solution Architect, QA, Tech Lead |
| Microservices | Solution Architect | All |
| New app | Product Manager | All |

### 6.3 Team rules
- The Tech Lead **never** reviews in the context that produced the work.
- Agents communicate through **state + workspace files**, not long shared chats (this keeps context small).
- Each agent/sub-agent has a prompt (`agent/agents/<role>/prompt.md`), a tool allowlist and an output JSON schema.
- Only one LLM job runs at a time by default (`max_parallel_llm_jobs = 1`); the Project Manager schedules the queue.

---

## 7. Agentic components (24)
| # | Component | Responsibility | Used by |
|---|---|---|---|
| **Thinking** | | | |
| 1 | Intent Router | Message → intent + tier + playbook; asks when unclear; declines non-software requests | Project Manager |
| 2 | Planner | Task → to-do list, shown and updated live in chat | All agents |
| 3 | Playbook Registry | Workflows per intent (Section 5); pluggable | Project Manager |
| 4 | Orchestrator (LangGraph) | Runs playbook steps; branches, loops, retries, background runs | Whole system |
| 5 | Sub-agent Manager (deepagents) | Creates agents/sub-agents with their own prompt, tools and context | All agents |
| **Doing** | | | |
| 6 | Tool Registry | Typed, validated tools; allowlist per agent | All agents |
| 7 | MCP Client | Graphify MCP server (graph queries); future MCP tools | All agents |
| 8 | Language Packs | Detect, parse, build, test, run, scaffold per language | Developers, QA, Analyst |
| 9 | Sandbox | All code runs in Docker with limits; previews of running apps | Developers, QA, DevOps |
| 10 | Virtual File System | Project workspace, read/write | All agents |
| 11 | Connectors | GitHub, ZIP, Google Drive, local folder: in and out | Business Analyst, Release Manager |
| **Knowing** | | | |
| 12 | Knowledge Graph | Graphify graph + runtime calls, DB ownership, git co-change, user corrections | All agents |
| 13 | Code Search (RAG) | Semantic search over code/docs (pgvector) | All agents |
| 14 | Context Manager | Small, relevant context per task; cached summaries by file hash | All agents |
| 15 | Short-term Memory | Chat + run state | All agents |
| 16 | Long-term Memory | Project memory + cross-project lessons + user preferences; user-editable | All agents |
| **Checking** | | | |
| 17 | Verification Engine | Tests, replay + diff, contract tests, benchmarks, E2E, screenshots | QA, Tech Lead |
| 18 | Reflection Loop | Failure → hypothesis → fix → retry (max 5) → escalate | Developers |
| 19 | Structured Output Validator | JSON-schema outputs, validation, retries | All agents |
| **Control** | | | |
| 20 | Approval Gates (HITL) | Approval cards in chat; LangGraph `interrupt()` + resume | Project Manager |
| 21 | Checkpointing | Resume after a crash, stop, or GPU disconnect | Orchestrator |
| 22 | Guardrails + Budgets | Safety rules, limits, no production, masked secrets, git safety | Whole system |
| 23 | Observability | Every LLM/tool call traced; visible in the app | Whole system |
| 24 | Evals | Benchmarks per playbook; regression detection in CI | Development |

```
You (chat) → [1 Router] → Project Manager → [3 Playbooks] + [2 Planner]
   → [4 Orchestrator] → role agents → sub-agents   (via [5])
        do:    [6 Tools] [7 MCP] [8 Language Packs] [9 Sandbox] [10 Files] [11 Connectors]
        know:  [12 Graph] [13 Search] [14 Context] [15/16 Memory]
        check: [17 Verify] ⇄ [18 Reflect], [19 Validator]
   → [20 Approval card] → you → delivery
Always on: [21 Checkpoints] [22 Guardrails] [23 Observability]
```

---

## 8. Core concepts

### 8.1 Projects and workspaces
- A **project** = a source (connected or created), instructions, memory, graph, chats and runs.
- Workspace per project: `workspaces/<project_id>/` with `source/` (original, read-only), `work/` (the git working copy for changes), `graph/` (Graphify outputs + enriched graph versions), `baseline/` (tests, traffic, perf), `runs/<run_id>/` (plans, artifacts, reports), `logs/`.
- Every change happens on a **branch** in `work/`. Delivery publishes that branch or its files.

### 8.2 Graphify (code understanding)
- **Base graph:** Graphify on the project: code via tree-sitter (local, no LLM needed), SQL schemas, live Postgres schema when available.
- **Enrichment:** Language Packs (routes, ORM models, queries, events), runtime calls, table reads/writes, git co-change, user corrections. Each node/edge stores `source` and `confidence`.
- **Agents query the graph** (MCP tools / Graphify CLI: query, path, explain) instead of reading whole files. This is essential for a 9B model.
- **In the app:** the live Graph tab and the full-screen Graph explorer.
- **Before/after:** any structural change (refactor, microservices, translate, new app) produces before/after graphs + a comparison summary.
- **Inside outputs:** every generated or converted project/service ships with its `graphify-out/`, a `GRAPHIFY.md` (how to rebuild and query, how to connect an AI assistant), an MCP config example, and a CI step that rebuilds the graph.
- **Hygiene:** re-run after every significant change; check for stale/duplicate nodes; never decide on an old graph.

### 8.3 Language Packs
```python
class LanguagePack(Protocol):
    name: str
    def detect(self, repo: Path) -> DetectionResult: ...
    def parse(self, repo: Path) -> GraphFragment: ...        # framework-level: routes, ORM, queries, events
    def build(self, path: Path) -> CommandResult: ...
    def test(self, path: Path) -> TestReport: ...
    def run(self, path: Path, env: dict) -> RunningProcess: ...
    def scaffold_service(self, spec: ServiceSpec, out: Path) -> None: ...   # incl. Graphify setup
    def client_stub(self, contract: Contract, out: Path) -> None: ...
    def docker_base(self) -> DockerSpec: ...
    def instrumentation(self) -> InstrumentationSpec: ...
```
Graphify covers general structure for many languages; packs add framework meaning and build/test/run/scaffold. Waves: Go + Python → Java + TypeScript/Node → PHP + .NET. Fallback: Graphify-only (lower confidence).

### 8.4 Template library (for new apps and scaffolds)
`templates/apps/` and `templates/services/`: tested starters with auth, CRUD, admin, Docker, tests, CI and Graphify setup. Each template has a manifest (stack, features, extension points). New apps start from a template; the LLM fills in domain code in small steps.

### 8.5 Extract vs Translate
| | Extract | Translate |
|---|---|---|
| When | Same language | New language |
| Source of truth | Original code | Spec: contract + black-box tests + recorded traffic (original code as reference) |
| Method | Move code, change boundaries | One function at a time, with compile/test feedback |
| Risk | Low | Higher, shown in the UI |

---

## 9. Harness (LangGraph + deepagents)

### 9.1 State (sketch)
```python
class ChatTurnState(TypedDict):
    conversation_id: str
    project_id: str | None
    message: UserMessage                 # text + attachments
    intent: IntentResult | None
    plan: Plan | None
    run_id: str | None                   # long runs execute as background runs

class RunState(TypedDict):
    run_id: str
    project_id: str | None
    playbook: str
    tier: int
    inputs: dict
    plan: Plan
    steps: dict[str, StepResult]
    artifacts: list[ArtifactRef]         # shown in the side panel
    approvals: list[ApprovalRecord]
    verification: VerificationReport | None
    delivery: list[DeliveryTarget]
    budget: BudgetState
    llm_profile: Literal["remote_gpu", "local_cpu"]
    errors: list[ErrorRecord]
```

### 9.2 Components → implementation
| Need | Implementation |
|---|---|
| Chat turn | LangGraph graph: route → (answer or plan) → start/continue a run; streams tokens and events to the UI |
| Runs | One LangGraph subgraph per playbook; background execution; events (plan updates, team activity, artifacts, approvals) streamed over SSE/WebSocket |
| Sub-agents | `deepagents` with per-role prompts, tool allowlists, file system backed by the workspace |
| Approvals | `interrupt()` → approval card in chat → resume with approve/edit/reject + comments |
| Checkpoints | Postgres checkpointer; stop/resume; GPU-loss recovery |
| Budgets | Time/tokens/retries per run and step; pause and ask when exceeded |
| Traces | Every LLM/tool call stored; viewable from "Team activity" |

---

## 10. LLM: self-hosted Qwen3.5 9B
| Profile | Where | Notes |
|---|---|---|
| **remote_gpu** (default) | User's RTX 3080 10 GB machine, via Ollama or a llama.cpp server | Reached over a **secure tunnel** (Tailscale/WireGuard/SSH); never expose the port publicly |
| **local_cpu** | The machine running Codewright | Slow; fine for Q&A, explain, audits, small fixes |

- **Model:** Qwen3.5 9B **Q4_K_M** (verify V1); one model for all roles.
- **Switching:** model picker in the chat and Settings; health check before runs; on GPU loss: checkpoint → pause → ask (retry / switch to CPU / wait).
- **VRAM:** start with `num_ctx` ≈ 16K on the GPU (8K on CPU), measure, tune, record in an ADR. `max_parallel_llm_jobs = 1`.
- **Embeddings:** a small local embedding model (e.g. `nomic-embed-text`) on CPU.
- **External providers:** off by default; opt-in only, with a clear warning.

```yaml
# config/models.yaml (example)
profiles:
  remote_gpu: { base_url: http://gpu-box.tailnet:11434/v1, model: qwen3.5:9b-q4_K_M, num_ctx: 16384, max_parallel_llm_jobs: 1 }
  local_cpu:  { base_url: http://localhost:11434/v1,       model: qwen3.5:9b-q4_K_M, num_ctx: 8192,  max_parallel_llm_jobs: 1 }
embeddings:   { base_url: http://localhost:11434/v1, model: nomic-embed-text }
default_profile: remote_gpu
```

**Rules for a 9B model (mandatory):**
1. **Tools, algorithms and templates first:** Graphify, community detection, replay/diff, scanners, scaffolds. The LLM names, explains, decides between options and edits.
2. **Small tasks:** one function, file or decision per call.
3. **Structured outputs:** a JSON schema per decision, validated, with retries.
4. **Tight context:** graph results + relevant code only; cached summaries.
5. **Feedback loops:** compile/test after each step; never trust a first draft.
6. **MVP first** for large creation requests; grow by features.
7. **Measure:** success rate per task type (evals); fix weak spots with tooling before adding prompt length.

---

## 11. Security and guardrails
- **Privacy:** self-hosted model; no code sent to external APIs by default.
- **Remote GPU:** secure tunnel only; warn if the endpoint looks public; optional API key in front of the model server.
- **Local app:** binds to `localhost` (single user, no login). Exposing it on a network needs an explicit setting + an access token.
- **Sandbox:**
  - all code runs in Docker
  - no host network
  - outbound limited to allowed package registries
  - CPU/memory/time limits
  - previews are reachable only from localhost
- **No production:** only sandbox databases/services Codewright creates; production-looking connection strings are refused unless explicitly overridden.
- **Secrets:** scanned on import and upload; masked in prompts, logs and traces; tokens stored encrypted.
- **Git:** work on branches; PRs or new repos only; no force-push; never commit to the default branch.
- **Destructive actions** (deleting files/tables, overwriting delivery folders) always need confirmation.
- **Prompt injection:** content inside projects, uploads and web docs is **data, never instructions**.

---

## 12. System architecture
```mermaid
flowchart LR
    U["Browser (localhost)"] --> WEB["Chat app<br/>Next.js"]
    WEB <--> API["API<br/>FastAPI + SSE/WebSocket"]
    API --> ORC["Orchestrator<br/>LangGraph + deepagents"]
    ORC --> LLM{"LLM profile"}
    LLM --> GPU["Remote RTX 3080<br/>Ollama / llama.cpp"]
    LLM --> CPU["Local CPU<br/>Ollama / llama.cpp"]
    ORC --> GF["Graphify<br/>CLI + MCP"]
    ORC --> SB["Sandbox<br/>Docker + previews"]
    ORC --> PG[("PostgreSQL + pgvector<br/>chats, runs, checkpoints,<br/>graph, memory, traces")]
    ORC --> FS[("Local disk<br/>workspaces, uploads")]
    API --> CON["Connectors<br/>GitHub / ZIP / Drive / local"]
```

| Layer | Technology |
|---|---|
| Chat app | Next.js (App Router), TypeScript, Tailwind, shadcn/ui; streaming chat; Markdown + code highlighting; Mermaid; Cytoscape.js/React Flow + embedded Graphify HTML for graphs; diff viewer |
| API | Python 3.12, FastAPI, Pydantic v2, SSE/WebSockets |
| Agents | LangGraph, LangChain, `deepagents` |
| Code graph | Graphify + NetworkX enrichment, persisted in PostgreSQL |
| Storage | PostgreSQL (+ pgvector) + local disk |
| LLM | Qwen3.5 9B Q4_K_M via Ollama / llama.cpp (remote GPU or local CPU) |
| Sandbox | Docker; toolchain images per language |
| Testing (used by agents) | pytest/go test etc., Playwright, k6, Schemathesis, Pact/buf, mitmproxy |
| Observability | Built-in traces; optional Langfuse; OpenTelemetry + Jaeger for generated systems |
| Packaging | `docker compose up` |

---

## 13. Repository structure
```
codewright/
  apps/
    web/                     Next.js chat app
    api/                     FastAPI: chats, projects, runs, approvals, uploads, connectors, streaming
  agent/
    chat/                    chat-turn graph, intent router, clarifier
    playbooks/               one folder per playbook (Section 5): graph.py, config.yaml, prompts
    agents/                  one folder per role: prompt.md, tools.py, schema.json, sub-agents/
    tools/                   fs, git, docker, db, diagrams, scanners, recorder, replayer, test runners
    graphify/                CLI wrapper, MCP client, importer, before/after comparison
    knowledge_graph/         enrichment, persistence, queries
    language_packs/          base.py, go/, python/, java/, typescript/, php/, dotnet/
    decomposition/           weighting, community detection, rules, scoring
    verification/            replay, diff, noise rules, benchmarks, screenshots
    memory/                  project memory, lessons, preferences
    llm/                     profiles, health, structured outputs, queue, budgets
  connectors/
    inputs/  outputs/        github, zip, gdrive, local
  sandbox/
    images/  runner/         toolchain images; lifecycle, limits, network, previews
  templates/
    apps/  services/  ci/  deploy/  frontend/
  evals/                     repos/, references/, tasks/, run_evals.py
  config/                    models.yaml, budgets.yaml, noise_rules.default.yaml, tiers.yaml
  deploy/                    docker-compose.yml
  docs/                      adr/, architecture/, setup/remote-gpu.md
  PROGRESS.md
  README.md
```

---

## 14. Outputs (what the user receives)
| Request type | Output |
|---|---|
| Answer / explain | Chat answer + diagram/graph in the side panel |
| Audit | Report + diagrams + graph (deliverable) |
| Fix / tests / refactor / performance / security / upgrade / DB / feature / frontend / DevOps | A branch with the changes + a verification report (tests, replay, benchmarks) + before/after graph where structural + a PR or other delivery |
| New app | A complete project: code, tests, Docker, CI, docs, `GRAPHIFY.md`, running preview, delivered where chosen, and added to Projects |
| Microservices | `frontend/` (one app) + `services/<N>/` + gateway + platform + deploy + docs (C4, catalogs, ADRs, runbook, before/after graphs, `COMPARISON.md`) + reports |

---

## 15. Roadmap (one sequence)

Build in order and **stop after each phase** for review. Durations are rough, for one developer with a coding agent.

| Milestone | After phase | Demo |
|---|---|---|
| **M1: Chat with your code** | 6 | Chat app; connect GoShop; ask questions, explain, audit, docs; live graph |
| **M2: Improve existing code** | 10 | Fix bugs, write tests, refactor, speed up, secure, upgrade GoShop, all verified |
| **M3: Build** | 13 | Add features; modernize the frontend; create a new app from a chat request with a live preview |
| **M4: Modernize architecture** | 17 | GoShop → 1 frontend + 5 microservices, DB split, sagas, before/after graphs |
| **M5: v1.0** | 22 | Translate, more languages, evals, polish, hardened, one-command install |

### Phase 0: Setup and reconciliation (≈1 week, in progress)
1. **Reconcile the existing work** (Section 0.5): report, then apply the approved changes (rename MonoShift → Codewright, remove unused services, etc.).
2. Repo structure (Section 13), `PROGRESS.md`, ADR template.
3. `deploy/docker-compose.yml`: web, api, postgres (+pgvector), optional ollama-cpu, optional langfuse profile.
4. FastAPI skeleton (health, settings, Alembic). Next.js skeleton: **chat layout shell** (sidebar, chat area, side panel), theme tokens, dark/light.
5. Lint/format/type-check, pre-commit, CI.
6. `.env.example`.
7. Verification checklist V1–V5 → report.
- **Acceptance:** `docker compose up` works; the chat shell renders; CI green; V1–V5 reported.

### Phase 1: LLM layer and harness core (≈2 weeks)
1. `agent/llm/`:
   - `remote_gpu` + `local_cpu` profiles
   - health check
   - queue (`max_parallel_llm_jobs`)
   - structured outputs (schema + validation + retry)
   - token/time tracking
   - budgets
2. Remote GPU setup guide (`docs/setup/remote-gpu.md`): Ollama/llama.cpp, the Q4_K_M model, secure tunnel, VRAM vs `num_ctx` measurements.
3. LangGraph basics: a run subgraph pattern, Postgres checkpointer, `interrupt()` approvals, event streaming.
4. `deepagents`: the Project Manager + one sample role with workspace-backed files.
5. Trace store. GPU-loss handling.
- **Acceptance:** a sample run streams events, pauses for approval, resumes; crash → resume; profile switch works; 9B structured-output success rate measured.

### Phase 2: The chat app (≈3 weeks)
1. Conversations: create, list, search, rename, delete, pin; message storage; streaming replies.
2. **Intent Router** (18 intents, tiers, confidence, clarifying questions, non-software decline) with an eval set of ~100 labeled messages.
3. **Answer** playbook (`general_help`).
4. In-chat components: plan checklist, team activity feed, **approval cards**, artifact links.
5. Side panel framework with tabs (Plan, Diff, Graph, Diagram, Tests, Preview, Report).
6. Edit / regenerate / branch / stop. Markdown, code highlighting, Mermaid rendering.
7. Settings: LLM profile + health, budgets, theme. Model picker in the chat.
- **Acceptance:** a Claude-like chat experience works end to end for general software Q&A; router accuracy reported; UI reviewed by the user.

### Phase 3: Projects, uploads, connectors, delivery (≈2 weeks)
1. Projects: create/connect (GitHub, ZIP, Google Drive, local folder); project home; instructions; project memory.
2. Uploads in chat (files, screenshots, logs) with secret scanning.
3. Workspace manager (Section 8.1), git branches for changes.
4. Output connectors + the **Deliver** card (local / GitHub / ZIP / Drive; asks where).
5. `project_manage` playbook.
- **Acceptance:** GoShop connected by each method; a sample result delivered to each target; a malicious ZIP is rejected; secrets are masked.

### Phase 4: Graphify + knowledge graph + code search (≈2 weeks)
1. Graphify wrapper (CLI + MCP), importer, graph versions per project, hygiene checks.
2. Enrichment framework (sources + confidence).
3. Code search (chunk + embed + pgvector).
4. Graph tab + full-screen Graph explorer (filters, node details, highlight from chat).
- **Acceptance:** the GoShop graph shows `user`, `product`, `order`, `payment`, `notification` and their links; graph queries are correct on fixtures.

### Phase 5: Language Packs (Go, Python) + sandbox (≈3 weeks)
1. `LanguagePack` interface + Graphify-only fallback.
2. Go and Python packs: detect, framework parsing, build/test/run, scaffold, client stubs.
3. Sandbox runner: toolchain images, limits, network allowlist, **previews** (run an app and show it in the Preview tab).
4. First templates: one Go and one Python service template, including Graphify setup.
- **Acceptance:** golden tests on fixtures; GoShop builds, tests and runs in the sandbox, visible in Preview.

### Phase 6: Understand: Explain, Audit, Docs (≈2 weeks), Milestone M1
1. `explain_code`: graph + search answers with diagrams.
2. `analyze_audit`: As-Is architecture (C4, dependencies, DB map, hotspots), security and quality findings, recommendations, report.
3. `write_docs`.
4. Gate pattern for corrections ("that's wrong, Payment also calls Notification" → `USER_FACT`).
- **Acceptance:** GoShop questions answered correctly (eval set); the audit is reviewed by the user; **M1 demo**.

### Phase 7: Verification engine (≈2 weeks)
1. Test runner integration per Language Pack; coverage.
2. Characterization test generation (QA sub-agents).
3. Traffic recorder (mitmproxy) + replay + semantic diff + noise rules; self-replay = 0 diffs.
4. Benchmarks (k6, profiler hooks). Playwright + screenshot comparison.
5. Eval harness skeleton (tasks per playbook, run in CI on fixtures).
- **Acceptance:** GoShop recorded and replayed with 0 diffs; reports render in the Tests tab.

### Phase 8: Fix and test (≈2 weeks)
`fix_bug` (reproduce → fix → verify) and `write_tests` playbooks, with the Reflection loop, Tech Lead fresh review, and tier-1 approval + delivery.
- **Acceptance:** seeded bugs in GoShop fixed with regression tests; coverage increased; evals recorded.

### Phase 9: Refactor and performance (≈3 weeks)
`refactor` and `improve_performance` playbooks with plan + result approvals, replay-proven behavior, before/after graphs and benchmarks.
- **Acceptance:** a GoShop module refactored with 0 replay regressions; a seeded slow endpoint measurably faster.

### Phase 10: Security, upgrade, DB change (≈3 weeks), Milestone M2
`security_review`, `upgrade` and `database_change` playbooks (scanners, migration guides, migration + rollback scripts, data checks).
- **Acceptance:** seeded vulnerabilities found and fixed; a dependency/framework upgrade done with all tests green; an index/migration verified; **M2 demo**.

### Phase 11: Features (≈3 weeks)
`add_feature` playbook: Product Manager (stories), Solution Architect (design), UI/UX (screens), Backend + Frontend builds, tests from acceptance criteria, Preview.
- **Acceptance:** "Add a wishlist" to GoShop works end to end with tests and a preview.

### Phase 12: Frontend and modern UI (≈3 weeks)
`frontend_modernize` playbook: rewire, migrate (React → Next.js first) with parity checks, then the modern redesign with before/after previews and accessibility checks.
- **Acceptance:** the GoShop frontend migrated with E2E parity, then modernized; accessibility checks pass.

### Phase 13: New app (≈4 weeks), Milestone M3
1. Template library (`templates/apps/`): at least 2 full-stack starters (e.g. FastAPI + Next.js, Go + Next.js) with auth, CRUD, admin, Docker, tests, CI, Graphify setup.
2. `new_app` playbook (Section 5.17): requirements → design → screens → scaffold → feature-by-feature build → preview → review → delivery → added to Projects.
- **Acceptance:** "Create a clinic appointment booking app" and "Create an inventory app for a small shop" each produce a running, tested app with a preview, delivered and then extendable through chat; **M3 demo**.

### Phase 14: DevOps (≈2 weeks)
`devops_deploy` playbook: Dockerfiles, Compose, CI/CD, optional K8s/cloud manifests, observability, security review.
- **Acceptance:** GoShop and a generated app containerized, with CI passing in the sandbox.

### Phase 15: Microservices I: design and audit (≈3 weeks)
To-Be design (decomposition engine, rules, scores, alternatives, "Why N services", editing on the graph), Language Advisor, and the microservices audit report with the projected graph.
- **Acceptance:** GoShop → ~5 services with reasons, events and sagas; edits re-validate.

### Phase 16: Microservices II: build the services (≈4 weeks)
Foundation generation, per-service loop (spec → scaffold → extract → ACL → tests → shadow → replay → reflect → review → PR → canary cut-over), parallel scheduling, Graphify per service, Run detail screen (service board, replay results).
- **Acceptance:** all GoShop services extracted with 0 replay regressions; the monolith serves nothing.

### Phase 17: Microservices III: data and finish (≈3 weeks), Milestone M4
DB split stages, outbox, sagas with compensation, rollback scripts, frontend against the gateway, before/after graphs + `COMPARISON.md`, final report, Gate 8 delivery.
- **Acceptance:** all saga paths tested; replay = 0 regressions; full report delivered; **M4 demo**.

### Phase 18: Translate (≈3 weeks)
`translate_language` playbook (spec-first, function by function).
- **Acceptance:** a GoShop service rebuilt in Python passes the same contract and replay tests.

### Phase 19: More Language Packs and templates (≈4+ weeks)
Java (Spring) + TypeScript/Node, then PHP (Laravel) + .NET; matching templates.
- **Acceptance:** each pack passes golden tests; one benchmark repo per language goes through audit + one improvement playbook.

### Phase 20: Evals (≈2 weeks, ongoing from Phase 7)
- **Benchmarks:**
  - GoShop
  - a Python monolith
  - synthetic repos with known answers
  - seeded bugs/vulnerabilities/slow endpoints
  - new-app prompts with acceptance tests
- **Metrics:**
  - router accuracy
  - task success per playbook
  - replay equivalence
  - tests passing
  - human interventions
  - retries
  - time per task (GPU and CPU)
  - 9B structured-output success rate
- CI on fixtures; nightly on full repos.

### Phase 21: Polish (≈2 weeks, can run in parallel from Phase 2)
Every screen and component (Section 2): Claude-like feel, responsive, dark/light, keyboard shortcuts, accessibility, onboarding ("connect a project or ask anything"), good empty/error states.

### Phase 22: Hardening and v1.0 (≈2 weeks), Milestone M5
- sandbox escape and prompt-injection tests
- token storage, tunnel checks
- crash/resume and GPU-loss tests for every playbook
- caching and incremental Graphify
- one-command install
- user guide + contributor guide (adding a playbook, a Language Pack or a template)
- **Acceptance:** fresh-machine install; GoShop end-to-end conversion on the remote GPU; audit + Q&A on CPU; a new app created from chat; **v1.0 tag**

| Phase | Weeks | Cumulative |
|---|---|---|
| 0 | 1 | 1 |
| 1 | 2 | 3 |
| 2 | 3 | 6 |
| 3 | 2 | 8 |
| 4 | 2 | 10 |
| 5 | 3 | 13 |
| 6 (M1) | 2 | 15 |
| 7 | 2 | 17 |
| 8 | 2 | 19 |
| 9 | 3 | 22 |
| 10 (M2) | 3 | 25 |
| 11 | 3 | 28 |
| 12 | 3 | 31 |
| 13 (M3) | 4 | 35 |
| 14 | 2 | 37 |
| 15 | 3 | 40 |
| 16 | 4 | 44 |
| 17 (M4) | 3 | 47 |
| 18 | 3 | 50 |
| 19 | 4+ | 54+ |
| 20 | 2 | 56 |
| 21 | (parallel) | – |
| 22 (M5) | 2 | ~58 |

---

## 16. Risks and mitigations
| Risk | Mitigation |
|---|---|
| A 9B model is weak at long, multi-step coding | Tools/algorithms/templates first; one-function tasks; structured outputs; compile/test loops; MVP-first; evals per task type; a bigger model can be plugged in later |
| 10 GB VRAM limits the context | Graph queries instead of whole files; tuned `num_ctx`; cached summaries |
| Remote GPU drops | Checkpoints; pause and ask; switch to CPU |
| CPU mode is slow | Show time estimates; recommend the GPU for tier 2–3 work |
| Router misunderstands a request | Confidence threshold; clarifying questions; a plan shown before work; user can correct |
| New-app requests too big | MVP scoping by the Product Manager; grow by features |
| Changes break behavior | Tests + replay + benchmarks before every result; 0-regression rule |
| Graphify stale/duplicate nodes | Re-run after changes; hygiene checks |
| Data loss | Sandbox only; migration + rollback scripts; count/checksum checks; confirmations |
| Prompt injection from code/uploads/docs | Treated as data; tool allowlists; sandbox |
| Over-engineering (e.g. needless microservices) | Honest-advice rules; "simple app" default for new apps; "Why N services" justification |

---

## 17. Definition of done (v1.0)
- [ ] `docker compose up` on a fresh machine; works with the remote RTX 3080 and with local CPU, switchable from the chat
- [ ] Claude-like chat: streaming, conversations, projects, uploads, side panel, edit/regenerate/branch/stop, team activity, plan checklist, approval cards, memory, settings, dark/light
- [ ] All 18 intents routed correctly on the eval set (target agreed with the user)
- [ ] Playbooks working on GoShop: explain, audit, docs, tests, bug fix, security, refactor, performance, upgrade, DB change, feature, frontend, DevOps, microservices, translate
- [ ] New app from chat: at least 2 example apps created, running in Preview, tested, delivered, and extendable through chat
- [ ] Verification on every change: tests + replay + benchmarks where relevant; 0 regressions
- [ ] Graphify: live graph in the app, before/after graphs for structural changes, set up in every generated/converted project
- [ ] Delivery to local folder, GitHub, ZIP and Google Drive, chosen by the user
- [ ] Runs resume after a crash, a stop, or GPU loss
- [ ] Language Packs: Go, Python, Java, TypeScript
- [ ] Evals in CI; user and contributor docs written

---

## 18. Glossary
| Term | Meaning |
|---|---|
| **Intent** | What the user wants, detected from a chat message (e.g. `fix_bug`) |
| **Playbook** | The step-by-step workflow Codewright runs for an intent |
| **Tier** | Risk level of a request; decides how many approvals are needed |
| **Approval card** | An in-chat card to approve, edit or reject a plan or result |
| **Sub-agent** | A short-lived helper agent for one small job |
| **Graphify** | Open-source tool that turns code into a queryable knowledge graph |
| **Language Pack** | Plugin that teaches Codewright one language's frameworks and build/test/run |
| **Template** | A tested starter project used to build new apps and services |
| **Characterization test** | A test that records how code behaves today |
| **Traffic replay** | Re-sending recorded requests and comparing the responses |
| **Monolith / microservice** | One big app vs. small independent services that each own their data |
| **Strangler Fig** | Replacing parts of a system gradually behind a gateway |
| **Anti-corruption layer** | An adapter that lets old code call new services |
| **Outbox / saga** | Reliable events / multi-service workflows with compensation |
| **Q4_K_M** | A 4-bit quantized model format: smaller and faster, with a small quality loss |
