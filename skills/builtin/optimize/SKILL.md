---
name: optimize
command: /optimize
description: 'Make something faster: profile, fix, benchmark.'
languages: []
scope: global
playbook: improve_performance
tier: 2
inputs:
- name: path
  required: false
allowed_tools:
- read_files
- run_tests
- run_app
- write_files
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Measure first.
2. Fix the biggest cost.
3. Benchmark before and after.
