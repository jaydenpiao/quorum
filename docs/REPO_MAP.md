# Repo map

This file exists so an AI agent can understand the repository without scanning every file.

## Top level

- `README.md` — product and POC overview
- `INIT.md` — shortest startup context
- `AGENTS.md` — repo-wide working rules
- `CLAUDE.md` — same rules in Claude-friendly filename
- `llms.txt` — shortest file list for LLM navigation
- `pyproject.toml` — Python packaging and dependencies
- `Makefile` — common dev commands

## Config

- `config/system.yaml` — app and runtime settings
- `config/agents.yaml` — agent registry for the POC
- `config/policies.yaml` — quorum and safety rules

## Backend

- `apps/api/app/main.py` — FastAPI bootstrap and static console mounting
- `apps/api/app/api/routes.py` — HTTP routes
- `apps/api/app/domain/models.py` — core typed objects
- `apps/api/app/services/event_log.py` — append-only JSONL writer/reader
- `apps/api/app/services/state_store.py` — replay reducer and state materialization
- `apps/api/app/services/policy_engine.py` — policy evaluation
- `apps/api/app/services/quorum_engine.py` — vote counting and approval rules
- `apps/api/app/services/health_checks.py` — health verification
- `apps/api/app/services/executor.py` — execution + rollback flow
- `apps/api/app/demo_seed.py` — local demo incident bootstrap

## Console

- `apps/console/index.html` — static operator console

## Examples

- `examples/demo_incident.json` — canonical incident scenario
- `examples/sample_proposal.json` — sample proposal payload

## Docs

- `docs/ARCHITECTURE.md` — architecture and readable diagrams
- `docs/CURRENT_MODE.md` — how to work right now
- `docs/PARALLEL_DEVELOPMENT.md` — worktree and branch model for later
- `docs/GITHUB_AUTOMATION.md` — repo creation and push automation
- `docs/PRODUCT.md` — product framing and wedge
- `docs/ROADMAP.md` — staged buildout

## Scripts

- `scripts/bootstrap_local_repo.sh` — init local git and first commit
- `scripts/create_public_github_repo.sh` — create public repo with gh or token
- `scripts/new_worktree.sh` — create a worktree per task
- `scripts/validate_merge.sh` — run merge gate checks
- `scripts/demo_run.sh` — fast local demo

## CI / GitHub

- `.github/workflows/ci.yml` — lint + tests
- `.github/pull_request_template.md` — structured PR template
- `.github/ISSUE_TEMPLATE/bug_report.md` — issue template
