---
name: new-app
command: /new-app
description: Create a new app, game, site or tool. Always asks the language first.
languages: []
scope: global
playbook: new_app
tier: 1
inputs:
- name: description
  required: true
allowed_tools:
- write_files
- run_tests
- run_app
- web_preview
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Ask the language and the missing details (at most 3 questions plus the language).
2. Show the confirm card; nothing starts before Start.
3. Build from the matching template, test it in the sandbox, show it in Preview.
