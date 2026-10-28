---
name: translate
command: /translate
description: Rewrite code in another supported language.
languages: []
scope: global
playbook: translate_language
tier: 3
inputs:
- name: path
  required: false
- name: language
  required: true
allowed_tools:
- read_files
- run_tests
- write_files
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Only between the five supported languages.
2. Keep behaviour: the same tests pass in the new language.
