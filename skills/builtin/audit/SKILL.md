---
name: audit
command: /audit
description: Architecture, quality and security audit of the project, with diagrams and recommendations.
languages: []
scope: global
playbook: analyze_audit
tier: 0
allowed_tools:
- read_files
- graph_query
- code_search
- run_linters
output: markdown
enabled: true
auto_use: false
---

## Instructions
1. Make sure the project graph is fresh.
2. As-Is architecture: context, containers, components, dependencies, database map, hotspots.
3. Ask the user to confirm the As-Is; corrections become facts on the graph.
4. Security (secrets, dependencies) and quality findings.
5. Report with risks, recommendations and effort; which architecture fits only when relevant.
