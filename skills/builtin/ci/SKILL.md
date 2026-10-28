---
name: ci
command: /ci
description: CI pipeline for the project (build, test, lint).
languages: []
scope: global
playbook: devops_deploy
tier: 2
allowed_tools:
- read_files
- write_files
- run_tests
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Write the pipeline for the project's languages.
2. Check every step runs locally in the sandbox.
