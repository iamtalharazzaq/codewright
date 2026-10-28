---
name: db-change
command: /db-change
description: 'Change the database: indexes, schema or engine.'
languages: []
scope: global
playbook: database_change
tier: 2
inputs:
- name: description
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
1. Plan the change with migration and rollback scripts.
2. Test it on a throwaway database in the sandbox.
