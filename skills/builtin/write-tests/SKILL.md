---
name: write-tests
command: /write-tests
description: Add tests to existing code, with a coverage report.
languages: []
scope: global
playbook: write_tests
tier: 1
inputs:
- name: path
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
1. Find untested behaviour.
2. Write tests in the project's test framework.
3. Run them in the sandbox and report coverage.
