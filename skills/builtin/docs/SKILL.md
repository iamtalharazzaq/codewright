---
name: docs
command: /docs
description: 'Write documentation: README, API docs, architecture docs and a runbook, checked against the code.'
languages: []
scope: global
playbook: write_docs
tier: 1
inputs:
- name: path
  required: false
allowed_tools:
- read_files
- graph_query
- code_search
- run_tests
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Collect facts from the code: endpoints, commands, configuration, modules.
2. Write the documents.
3. Check them against the code: endpoints exist, commands are the real ones.
4. One approval on the result.
