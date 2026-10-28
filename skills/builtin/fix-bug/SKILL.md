---
name: fix-bug
command: /fix-bug
description: Reproduce a bug, fix it and add a regression test.
languages: []
scope: global
playbook: fix_bug
tier: 1
inputs:
- name: description
  required: true
allowed_tools:
- read_files
- run_tests
- write_files
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Reproduce with a failing test.
2. Fix the cause, not the symptom.
3. Prove it with the regression test and the existing tests.
