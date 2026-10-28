---
name: write-code
command: /write-code
description: Write a function, algorithm, data structure or query, with tests, in one of the five languages.
languages: []
scope: global
playbook: write_code
tier: 1
inputs:
- name: problem
  required: true
allowed_tools:
- read_files
- run_tests
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Always ask the language (one of the five) and recommend one with a reason.
2. Write the code and tests for the agreed edge cases.
3. Show code, explanation, time/space complexity and test results.
