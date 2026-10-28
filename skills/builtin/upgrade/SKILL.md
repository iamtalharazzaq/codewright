---
name: upgrade
command: /upgrade
description: Upgrade a framework, dependency or language version.
languages: []
scope: global
playbook: upgrade
tier: 2
inputs:
- name: target
  required: false
allowed_tools:
- read_files
- run_tests
- write_files
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Read the migration notes.
2. Upgrade step by step with tests green.
3. Report what changed.
