# Codewright: example requests

This file lists example requests you can give Codewright, and how Codewright should handle each one. It has two uses:
1. **Demo and try-out list:** things to ask Codewright once it's running.
2. **Test set:** the building agent uses these as acceptance and eval cases (`CODEWRIGHT.md`, Phases 2, 6, 8, 13 and 20).

---

## 1. The golden rules

### 1.1 Always ask before making
Codewright **never starts writing code or building anything until the user says yes**, even for tic-tac-toe or a single function.

```
1. Understand   →  what is being asked (intent + size)
2. Ask          →  the missing info, in ONE message, each question with a default
                   + ALWAYS the language question for anything new (1.2)
3. Confirm      →  a short "Here's what I'll make" card:
                    what · language/stack · main features · what I'll deliver
                    [Start] [Change something]
4. Make         →  only after the user clicks Start or says yes
5. Verify       →  run tests / play-test in the sandbox (live graph grows while it works)
6. Done         →  Done card + guide (how to run, use, test; next ideas)
```

- Steps 2 and 3 can be **one message** when only one or two things are missing.
- If nothing is missing, Codewright still shows the **Confirm** card and waits.
- Pure questions ("what is a linked list?") and reviews need no confirmation, because nothing is made or changed.

### 1.2 Always ask the language: only 5 supported
Codewright works in exactly **5 languages**:

| Language | Typical use |
|---|---|
| **C++** | Performance-critical code, algorithms, console apps/games, libraries (CMake) |
| **TypeScript** | React and Next.js apps, Node APIs, libraries |
| **JavaScript** | React and Next.js apps, Node APIs |
| **Go** | APIs, services, CLI tools |
| **Python** | APIs (FastAPI), scripts, CLI tools, data/automation |

- For anything **new**, Codewright **always asks** which language, listing the options that fit and **recommending one with a reason**.
- For an **existing project**, it uses the project's language and says so.
- For **any other language** (Java, PHP, C#, Rust, Kotlin…), it politely declines and suggests the closest supported one.

---

## 2. Code snippets and algorithms (`write_code`, `/write-code`)

Small, self-contained code: functions, algorithms, data structures, exercises. Shown in the chat (optionally saved as a file), always with tests that Codewright ran in the sandbox.

**What Codewright asks:**
- **language (always):** Python, Go, C++, TypeScript or JavaScript, with a recommendation
- input/output format or function signature (default: a standard signature)
- edge cases to handle (default: the common ones, listed in the confirm card)
- whether to explain the approach (default: yes, short explanation + time/space complexity)

**What it delivers:**
- code in the chat
- tests and their results
- a short explanation + complexity
- an optional "Save to file / add to project" button

| # | Example request | Recommended language (still asked) | Must handle / test |
|---|---|---|---|
| 1 | "Write code to reverse a linked list" | Python | empty list, one node, many nodes; iterative (recursive on request) |
| 2 | "Check if a string is a palindrome" | Python | case, spaces, punctuation, empty string |
| 3 | "FizzBuzz from 1 to 100" | Python | correct output for 3, 5, 15 |
| 4 | "Binary search in a sorted array" | Python | not found, first/last element, duplicates |
| 5 | "Two Sum: indices of two numbers adding to a target" | Python | no solution, negatives, O(n) with a hash map |
| 6 | "Merge two sorted linked lists" | Python | one or both empty |
| 7 | "Detect a cycle in a linked list" | Python | no cycle, cycle at head; Floyd's algorithm |
| 8 | "Check balanced parentheses" | Python | mixed brackets, empty, unmatched |
| 9 | "Implement an LRU cache" | Python | capacity 1, eviction order, get/put O(1) |
| 10 | "Merge sort / quick sort" | C++ | empty, duplicates, already sorted |
| 11 | "Fibonacci with memoization" | Python | n = 0, 1, large n |
| 12 | "Group anagrams" | Python | empty strings, single word |
| 13 | "BFS and DFS on a graph" | Python | disconnected graph, cycles |
| 14 | "Implement a stack and a queue" | C++ | empty pop, peek |
| 15 | "Implement a Trie with insert/search/startsWith" | TypeScript | prefix vs full word |
| 16 | "Dijkstra's shortest path" | C++ | unreachable nodes, ties |
| 17 | "Rotate a matrix 90 degrees" | Go | 1×1, n×n |
| 18 | "Debounce function" | JavaScript | rapid calls, trailing call, cancel |
| 19 | "Reverse a linked list in Go" | Go (named by the user, so no language question) | same as #1 |
| 20 | "Matrix multiplication, as fast as possible" | C++ | non-square, mismatched sizes; benchmark |
| 21 | "Write a SQL query: top 5 customers by total orders" | SQL (inside a Python/Go/TS project, or standalone) | ties, customers with no orders |
| 22 | "Reverse a linked list in Java" | **Declined**: "Java isn't supported. I can do it in Go, C++, TypeScript, JavaScript or Python. Which one?" | – |

**Example conversation:**
> **You:** Write code to reverse a linked list
>
> **Codewright:** Quick check before I write it:
> 1. **Which language?** Python *(recommended: clearest for learning)* · C++ · Go · TypeScript · JavaScript
> 2. Iterative, recursive, or both? *(default: iterative)*
>
> **You:** C++, both
>
> **Codewright:** **Here's what I'll make:** a `Node` struct and `reverseIterative(head)` + `reverseRecursive(head)` in C++17 (O(n) time; O(1) / O(n) space), GoogleTest tests for empty / one node / many nodes, and a short explanation.
> **[Start] [Change something]**
>
> **You:** Start
>
> **Codewright:** *(writes code, builds with CMake, runs tests in the sandbox)*
> ✅ **Done.** Both versions pass all 6 tests.
> *(code + explanation + complexity + test results)*
> Next: **[Explain step by step]** **[Save to a file]** **[Do it in Python]**

---

## 3. Small apps (tier 1)

Single-purpose apps. Codewright asks (always including the language) and confirms before building; one approval at the end.

**What Codewright asks:**
- **language (always)**, with options that fit the app:
  - browser apps: TypeScript + React (recommended) or JavaScript + React
  - terminal/console apps: Python, Go or C++
- main feature choices specific to the app
- style (default: clean modern look, dark/light)

**What it delivers:**
- a working app in Preview (web preview, or **terminal preview** for console apps)
- tests
- `GUIDE.md`
- a Done card
- delivery wherever you choose

| # | Example request | Language options offered (recommended first) | App-specific questions |
|---|---|---|---|
| 1 | "Make a tic-tac-toe game" | TS + React · JS + React · Python/Go/C++ (terminal) | vs computer or 2 players? difficulty? score? |
| 2 | "Make a calculator" | TS + React · JS + React · Python · Go · C++ (terminal) | basic or scientific? keyboard support? history? |
| 3 | "Make a to-do list app" | TS + React · JS + React | save in browser? categories/due dates? |
| 4 | "Make a stopwatch and timer" | TS + React · JS + React | laps? sound when the timer ends? |
| 5 | "Make a unit converter" | TS + React · JS + React · Python (terminal) | which units? |
| 6 | "Make a password generator" | TS + React · Python · Go (CLI) | length, symbols, copy button, strength meter? |
| 7 | "Make a quiz app" | TS + React · JS + React | topic, number of questions, timer, score? |
| 8 | "Make a BMI calculator" | TS + React · JS + React | metric/imperial? categories? |
| 9 | "Make rock-paper-scissors" | TS + React · Python/C++ (terminal) | best of 3/5? score? |
| 10 | "Make a memory card matching game" | TS + React · JS + React | grid size, timer, move counter? |
| 11 | "Make a snake game" | TS + React (canvas) · C++ (terminal) · Python (terminal) | speed levels, high score, walls or wrap-around? |
| 12 | "Make a Pomodoro timer" | TS + React · JS + React | work/break lengths, notifications? |
| 13 | "Make a Markdown previewer" | TS + React · JS + React | side-by-side or tabs? export? |
| 14 | "Make a simple expense tracker" | TS + React · JS + React | categories, monthly total, chart, save in browser? |
| 15 | "Make a personal portfolio website" | Next.js (TS) · Next.js (JS) | sections, your projects/links, color theme? |
| 16 | "Make a landing page for my bakery" | Next.js (TS) · Next.js (JS) | business name, sections, contact form? |
| 17 | "Make a number guessing game in the terminal" | Python · Go · C++ | range, attempts limit? |
| 18 | "Make a script that renames photos by date" | Python · Go | folder, name format, dry-run first? |
| 19 | "Make a console bank account simulator" | C++ · Go · Python | accounts, deposit/withdraw/transfer, save to file? |
| 20 | "Make a QR code generator" | TS + React · Python | download PNG? colors? |
| 21 | "Make a calculator in PHP" | **Declined**, with a suggestion: "PHP isn't supported. I can build it in TypeScript, JavaScript, Python, Go or C++." | – |

**Example conversation: calculator**
> **You:** Make a calculator
>
> **Codewright:** Before I build it:
> 1. **Which language?**
>    - **TypeScript + React** *(recommended: runs in the browser, you can use it right away in Preview)*
>    - JavaScript + React
>    - Python (terminal)
>    - Go (terminal)
>    - C++ (terminal)
> 2. Basic or scientific? *(default: basic + percent and memory buttons)*
> 3. Keyboard support and calculation history? *(default: yes, both)*
>
> **You:** Python, basic is fine
>
> **Codewright:** **Here's what I'll make:** a terminal calculator in Python with +, −, ×, ÷, %, memory, keyboard input and history; safe parsing (no `eval`), clear error messages (e.g. division by zero); pytest tests.
> **[Start] [Change something]**
>
> **You:** Start
>
> **Codewright:** *(Graph tab: the project graph grows live; Preview tab: an interactive terminal)*
> 🧮 Try it in the **Preview** terminal.
> ✋ **Happy with it?** **[Approve] [Edit] [Reject]**
> *(approve → "Where should I deliver it?" → ZIP)*
> ✅ **Done.** Calculator built, 18/18 tests passing.
> **Guide:** run with `python -m calculator`, how to use, run tests with `pytest`.
> Next: **[Add scientific functions]** **[Make a web version in TypeScript]** **[Review the code]**

---

## 4. Medium apps (tier 2)

Multi-screen apps with a backend, a database and usually login. Two approvals: the plan, and the finished app.

**What Codewright asks:**
- **language/stack (always)**, recommended first:
  - Next.js + Python (FastAPI)
  - Next.js + Go
  - Next.js + Node (TypeScript)
  - frontend in TypeScript or JavaScript
- who uses it (roles)
- the core features for the first version
- login needed?
- anything to integrate (payments, email)
- where it will run

**What it delivers:**
- short requirements
- a design (data model, screens)
- a working app in Preview
- tests
- Docker
- `GUIDE.md`
- a Done card
- delivery

| # | Example request | Core features Codewright proposes (to confirm) |
|---|---|---|
| 1 | "Make a blog with an admin panel" | posts, categories, comments, admin login, rich-text editor |
| 2 | "Make an inventory app for my shop" | products, stock in/out, low-stock alerts, suppliers, reports |
| 3 | "Make a simple online store" | product catalog, cart, checkout (test payments), orders, admin |
| 4 | "Make a library management system" | books, members, issue/return, due dates, fines |
| 5 | "Make a student attendance system" | classes, students, daily attendance, reports per student/class |
| 6 | "Make a restaurant menu and order app" | menu with categories, table orders, kitchen view, order status |
| 7 | "Make an appointment booking app for a salon" | services, staff, time slots, booking, reminders |
| 8 | "Make an expense tracker with accounts and charts" | login, accounts, categories, budgets, monthly charts |
| 9 | "Make a URL shortener" | short links, redirects, click stats, custom aliases |
| 10 | "Make a real-time chat app" | login, rooms, live messages (WebSocket), online status |
| 11 | "Make a job board" | job posts, search/filter, apply with CV upload, employer dashboard |
| 12 | "Make a recipe app" | recipes, ingredients, search, favorites, images |
| 13 | "Make a mini Trello / Kanban board" | boards, lists, cards, drag and drop, team members |
| 14 | "Make a notes app with tags and login" | notes, tags, search, Markdown, login |
| 15 | "Make a polling / voting app" | create polls, vote once per user, live results chart |
| 16 | "Make a REST API for a to-do app with auth" | JWT auth, CRUD, validation, API docs (OpenAPI); asks Go / Python / TypeScript |
| 17 | "Make a hotel room booking app" | rooms, availability calendar, bookings, admin |
| 18 | "Make a gym membership manager" | members, plans, payments record, attendance check-in |

**Example conversation (short):**
> **You:** Make an inventory app for my shop
>
> **Codewright:** Before I plan it:
> 1. **Which stack?** Next.js + Python FastAPI *(recommended: quick to build and extend)* · Next.js + Go · Next.js + Node (TypeScript); frontend in TypeScript *(recommended)* or JavaScript
> 2. Who uses it: just you, or staff too? *(default: you as admin + staff accounts)*
> 3. What's most important first? *(default: products, stock in/out, low-stock alerts, simple reports)*
> 4. Do you sell online too, or only track stock? *(default: only track stock)*
>
> *(you answer)*
>
> **Codewright:** **Plan** *(Plan and Diagram tabs)*: 5 screens, data model, features list.
> ✋ **[Approve plan] [Edit] [Reject]** → builds (live graph) → Preview → ✋ **[Approve app]** → delivery → ✅ Done card + guide

---

## 5. Large apps (tier 3): for reference

Full systems with many roles and integrations. Codewright asks the stack, scopes an **MVP** first, and uses all four gates (requirements, design, screens, final app).

| # | Example request |
|---|---|
| 1 | "Make a clinic management system: patients, doctors, appointments, prescriptions, billing" |
| 2 | "Make a food delivery platform: customers, restaurants, riders, orders, payments" |
| 3 | "Make a multi-vendor marketplace" |
| 4 | "Make a learning management system: courses, videos, quizzes, certificates" |
| 5 | "Make a school management system: admissions, fees, exams, results, parents' portal" |

---

## 6. Work on existing code

Same rules: ask what's missing, confirm, then act. The project's language is used (it must be one of the 5).

| Example | Playbook / skill |
|---|---|
| "Review my payment module" / `/review-code internal/payment` | Code review |
| "Review this snippet" *(pasted C++ code)* | Code review |
| "Find bugs in my calculator" | Code review → Bug fix |
| "My calculator gives the wrong result for 0.1 + 0.2" / `/fix-bug …` | Bug fix |
| "Add a score counter to my tic-tac-toe" | Feature |
| "Write tests for my inventory app" / `/write-tests` | Tests |
| "Refactor the order code" / `/refactor src/orders` | Refactor |
| "My API is slow when listing products" / `/optimize` | Performance |
| "Is my store app secure?" / `/security-review` | Security |
| "Upgrade my Next.js app to the latest version" | Upgrade |
| "Make the to-do app look modern" | Frontend |
| "Dockerize my blog" / `/dockerize` | DevOps |
| "Organize my Flask app into clean modules" | Architecture change (modules) |
| "Turn my app into a modular monolith" | Architecture change (modular monolith) |
| "Split my monolith into microservices" | Architecture change (microservices) |
| "I have 8 tiny services, merge them back into one app" | Architecture change (merge) |
| "Rewrite this Python CLI in Go" / `/translate cli.py go` | Translate |
| "Review my Java project" | **Declined**: Java isn't supported (offer to translate it into a supported language only if asked) |

**Example conversation: code review**
> **You:** /review-code src/calculator
>
> **Codewright:** *(Using skill: Review code. Tech Lead, Security Engineer and Code Analyst reviewing; linters run in the sandbox)*
> **Review of `src/calculator`**: 2 major, 3 minor, 4 nits.
> - 🔴 **Major** `parser.py:42`: uses `eval()` on user input (code injection). Fix: a safe expression parser.
> - 🔴 **Major** `ops.py:18`: division by zero crashes the app. Fix: catch and show an error.
> - 🟡 **Minor** …
>
> Top 3 to fix first: …
> **[Fix all major] [Pick findings to fix] [Explain a finding]**

---

## 7. Skills

| Example | What happens |
|---|---|
| Type `/` in the chat | A menu of all built-in and custom skills with short descriptions |
| `/review-code src/` | Runs the code review skill on `src/` |
| `/new-app a quiz game` | Starts the new-app flow (still asks the language and confirms) |
| "Review this for our Go style rules" | **Auto-uses** your custom skill "Go style review" and shows "Using skill: Go style review" |
| "Save this as a skill" *(after a chat where you defined a PR checklist)* | Drafts a `/pr-checklist` skill, shows it, saves only after you approve |
| `/create-skill` | Opens the guided skill creator (name, command, description, languages, steps, output format) |
| Skills screen → Export | Downloads the skill(s) as a ZIP |
| Skills screen → Import a ZIP or Git URL | Validates it, shows its instructions and tools, keeps it disabled until you enable it |

**Example conversation: creating a skill from chat**
> **You:** Whenever I ask for a Go review, check error wrapping, context usage, no global state, and table-driven tests. Save this as a skill.
>
> **Codewright:** Here's the skill I'll save:
> - **Name:** Go team review · **Command:** `/go-team-review` · **Languages:** Go · **Scope:** global
> - **Steps:** check error wrapping · context passed through · no global state · table-driven tests · then a normal review
> - **Output:** findings by severity with fixes
> **[Save skill] [Edit] [Cancel]**
>
> *(after saving)* Next time you say "review my Go code", it's used automatically.

---

## 8. Acceptance checks for every example
For any example in this file, Codewright passes when it:
1. Detects the right intent and size, and uses the right skill if one applies.
2. **Always asks the language** for anything new (only the 5 supported ones, with a recommendation); uses the project's language for existing code; declines unsupported languages with a suggestion.
3. Asks **only** the other missing questions, in one message, each with a default.
4. Shows a **confirm card** and **waits** before making or changing anything.
5. Produces working output: code passes its tests; apps run in Preview (web or terminal).
6. Shows the **live build graph** growing while it works, and includes the final graph in the output.
7. Ends with a **Done card** and a **guide** whose commands were verified in the sandbox.
8. Offers delivery options (for apps and files) and 2–3 sensible next steps.
9. Can continue in the same chat with follow-up changes ("make the computer unbeatable", "add dark mode").
