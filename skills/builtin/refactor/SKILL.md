---
name: refactor
command: /refactor
description: Restructure code without changing its behaviour.
languages: []
scope: global
playbook: refactor
tier: 2
inputs:
- name: path
  required: false
allowed_tools:
- read_files
- graph_query
- run_tests
- write_files
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Plan the change and get it approved.
2. Refactor in small steps, tests green after each.
3. Show the diff for approval.
