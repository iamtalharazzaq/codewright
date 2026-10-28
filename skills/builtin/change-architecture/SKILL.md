---
name: change-architecture
command: /change-architecture
description: 'Restructure a project: modules, modular monolith, microservices, merge services, serverless or event-driven.'
languages: []
scope: global
playbook: change_architecture
tier: 2
inputs:
- name: target
  required: false
allowed_tools:
- read_files
- graph_query
- code_search
- run_tests
- write_files
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Intake, baseline, As-Is, To-Be, languages, then build, with a gate at every stage.
