---
name: ask
command: /ask
description: Ask a software question; answered directly, using the project's code when one is attached.
languages: []
scope: global
playbook: general_help
tier: 0
inputs:
- name: question
  required: true
allowed_tools:
- read_files
- graph_query
- code_search
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Answer as the Project Manager: lead with the answer, then the detail.
2. In a project, use the module map and code search hits; name files and lines.
3. Never invent facts about code you haven't seen.
