---
name: dockerize
command: /dockerize
description: Docker setup for the project.
languages: []
scope: global
playbook: devops_deploy
tier: 2
allowed_tools:
- read_files
- write_files
- run_app
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Write the Dockerfile and compose file.
2. Build and run it in the sandbox.
