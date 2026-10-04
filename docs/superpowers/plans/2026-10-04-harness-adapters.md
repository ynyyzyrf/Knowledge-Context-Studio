# Four Harness Adapters Implementation Plan

**Goal:** Deliver KCS-owned official-format adapters for Codex, Claude Code, OpenClaw and Hermes.
**Architecture:** Reuse the stdio bridge and product credentials. Generate native configurations at credential issuance; expose a shared guide through MCP initialize and a read-only tool.
**Tech Stack:** Python/FastAPI, Node ES modules, React/TypeScript.
**Spec:** ../../requirements/2026-10-04-agentcombo-harness-adapters.md

User direction: proceed directly using official harness documentation; AgentCombo inspection and integration are excluded. Execute inline with the executing-plans skill, preserving uncommitted work. No collection hooks, external installs, production changes or global configuration writes.

## Tasks

- [x] Add native configuration generator in src/kcs/harness_configs.py; retain legacy credential response fields. Test TOML/JSON parsing (Hermes uses the JSON subset of YAML), escaping, environment references and absence of embedded secrets.
- [x] Add one shared instructions module and kb_guide tool to the MCP bridge; test initialize, tools/list and guide without credentials over real stdio. Keep existing tools and scope semantics.
- [x] Add four configuration tabs in the issuance UI and update response types; preserve compatibility with older server responses.
- [x] Correct README and add installation/verification instructions covering rule loading, runtime paths, credentials, OpenClaw version/mode limits and no collection.
- [x] Run targeted backend/protocol tests, frontend tests/build and syntax/lint checks; record evidence and remaining live-harness verification limits. Review changes before completion.

## Review focus

Configuration escape handling; secret-free templates; old-client compatibility; server startup without optional credentials for guide; distinction between protocol success and autonomous agent behavior.

## Execution notes

The existing MCP package is 0.3.0 with storage/result work uncommitted. This change layers on it rather than resetting or committing other work. Public templates use environment references; the existing one-time credential display remains available.

Completed as 0.4.0. 13 backend/protocol tests, 8 frontend tests, build, syntax and lint checks passed. Independent review found no blocker; issuance/rotation assertions added in response. No live model runs or UI browser verification; recorded in evidence. No commits or production changes made. Ruling: use YAML-compatible JSON for Hermes to avoid adding a production YAML serializer; explicitly document mapping merge instead of appending to existing YAML.
