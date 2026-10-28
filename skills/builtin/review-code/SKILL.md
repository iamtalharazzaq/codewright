---
name: review-code
command: /review-code
description: 'Code review like a senior engineer: findings by severity with file, line and a suggested fix.'
languages: []
scope: global
playbook: review_code
tier: 0
inputs:
- name: path
  required: false
allowed_tools:
- read_files
- graph_query
- code_search
- run_linters
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Scope: the given file, folder or module; the whole project when none is given.
2. Run the language's linters in the sandbox.
3. Tech Lead, Security Engineer and Code Analyst review; group findings as critical / major / minor / nit.
4. Each finding: file:line, problem, why it matters, suggested fix. End with a score and the top 3 to fix first.
5. Never apply fixes without confirmation.
