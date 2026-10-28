---
name: explain
command: /explain
description: Explain how some code works, with a diagram and the graph highlighted.
languages: []
scope: global
playbook: explain_code
tier: 0
inputs:
- name: path_or_question
  required: false
allowed_tools:
- read_files
- graph_query
- code_search
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Query the graph (explain, path, neighbours) and code search.
2. Answer in the chat, naming files and lines.
3. Draw the flow as a sequence or flow diagram in the side panel.
