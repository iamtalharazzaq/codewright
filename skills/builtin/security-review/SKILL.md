---
name: security-review
command: /security-review
description: Check the project for security problems and suggest fixes.
languages: []
scope: global
playbook: security_review
tier: 1
inputs:
- name: path
  required: false
allowed_tools:
- read_files
- code_search
- run_linters
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Scan for secrets, injection, unsafe input handling and vulnerable dependencies.
2. Report by severity with fixes.
3. Fixes only after confirmation.
