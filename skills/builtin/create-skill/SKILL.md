---
name: create-skill
command: /create-skill
description: Create a new custom skill from a description.
languages: []
scope: global
playbook: custom
tier: 0
inputs:
- name: description
  required: false
allowed_tools: []
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Draft the skill (name, command, description, steps, output format) from the description.
2. Show the draft; save it only after the user approves.
