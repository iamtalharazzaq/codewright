---
name: add-feature
command: /add-feature
description: Add a feature to an existing app, from stories to tests.
languages: []
scope: global
playbook: add_feature
tier: 2
inputs:
- name: description
  required: true
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
1. Write the stories and acceptance criteria.
2. Plan, build and test the feature.
