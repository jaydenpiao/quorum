# AGENTS.md — repo-wide instructions for AI coding agents

This file defines how to work safely in the Quorum repository. It is the
**single source of truth** for AI-agent behavior in this repo and follows
the [AGENTS.md](https://agents.md/) convention, so it is picked up
automatically by Codex, Cursor, Windsurf, Claude Code (via `CLAUDE.md`
redirect), and any other agent that honors the standard.

If anything in a tool-specific config (`.claude/`, `.cursor/`, etc.)
contradicts this file, **this file wins**.

---

## 0. Start here (canonical reading order)

Any fresh agent session should read, in order:

1. **`INIT.md`** — shortest startup context + immediate priorities.
2. **This file (`AGENTS.md`)** — the operating rules you are reading now.
3. **`docs/SESSION_HANDOFF.md`** — where the last session left off,
   current phase status, **the live list of known gotchas**, next
   candidates. Always current; treat its state as authoritative over
   any file date.
4. **`docs/ROADMAP.md`** — phase ✅/⏳/⬜ markers and what's next.
5. **`CHANGELOG.md`** — versioned feature list.
6. **`docs/REPO_MAP.md`** — where every file lives; update when you
   move things.
7. **`docs/ARCHITECTURE.md`** — system design, diagrams, extension
   points.

Area-specific deep reads are linked from §"Required reading by area"
below.

---

## 1. Product intent

Quorum is **not** a generic chat agent. It is a control plane for safe,
auditable, policy-gated, quorum-based execution by AI agents operating
on code and infrastructure.

All work should strengthen one or more of:

- auditability
- policy enforcement
- consensus before mutation
- rollback readiness
- post-change verification
- operator visibility
- extensibility across actuator types

## 2. What matters most

1. Keep the core state machine simple.
2. Keep domain objects explicit.
3. Preserve event sourcing and replayability.
4. Treat safety primitives as product primitives, not wrappers.
5. Prefer small files with clear names.
6. Favor markdown docs when making architectural changes.
7. When changing behavior, update docs and examples in the same patch.

## 3. Current development mode

**Phase 5 is shipped; v0.5.0-alpha.1 is tagged.** Quorum now has two
actuator families (`github.*`, `fly.*`), two LLM roles
(`telemetry-llm-agent`, `deploy-llm-agent`), Postgres projection,
human-approval entity, SSE event stream, and an image-push CI pipeline.

Until Phase 6's gate (≥2 weeks of event-schema stability) is met, stay
**single-threaded on the main working branch** — no long-lived parallel
branches, no speculative abstractions for future concurrency. One PR
at a time; wait for CI green before merging; pause for the operator's
confirmation before each merge unless explicitly told otherwise.

When Phase 6 opens, switch to the worktree model in
`docs/PARALLEL_DEVELOPMENT.md`.

## 4. Required reading by area

### Whole repo
- `INIT.md`
- `docs/REPO_MAP.md`
- `docs/ARCHITECTURE.md`
- `docs/SESSION_HANDOFF.md`

### Backend / control plane
- `apps/api/AGENTS.md`
- `config/policies.yaml`, `config/agents.yaml`, `config/system.yaml`
- `examples/demo_incident.json`
- `docs/design/postgres-projection.md` (projection architecture)
- `docs/design/phase-4-github-actuator.md` (GitHub actuator design)
- `docs/design/fly-deployment.md` (Phase 5 Fly.io design)

### LLM adapter
- `apps/llm_agent/AGENTS.md`
- `docs/design/llm-adapter.md`

### Console
- `apps/console/AGENTS.md`

### Contracts
- Prefer JSON examples and schema-like constraints in markdown until
  a dedicated schema package is added.

## 5. Coding rules

- Use Python 3.12+ features conservatively.
- Keep functions short and obvious.
- Add docstrings only where they clarify behavior.
- Avoid metaprogramming.
- Avoid hidden global state except for explicit app bootstrap.
- Keep the event log format stable.
- When adding a **new event type**, update in the same commit:
  - reducer logic (`apps/api/app/services/state_store.py`)
  - projector handler (`apps/api/app/services/postgres_projector.py`)
  - dispatch-completeness test (fails loudly if you miss either)
  - examples under `examples/`
  - docs (`docs/ARCHITECTURE.md` if flow changes)
  - tests covering the event

## 6. Domain model rules

The minimum core entities are:

- `Intent`
- `Finding`
- `Proposal`
- `Vote`
- `PolicyDecision`
- `ExecutionRecord`
- `HealthCheckResult`
- `RollbackRecord`
- `EventEnvelope`
- `HumanApprovalRequest` / `HumanApprovalOutcome` (Phase 4)

Do not bypass them with ad hoc dicts in business logic.

## 7. Logging rules

Every state transition must produce an event. Prefer new event types
over ambiguous overloaded ones.

**Good**: `proposal_created`, `proposal_voted`, `proposal_approved`,
`execution_started`, `health_check_completed`, `rollback_started`,
`rollback_completed`, `rollback_impossible`,
`human_approval_requested`, `human_approval_granted`,
`human_approval_denied`.

**Bad**: `status_changed`, `thing_updated`.

The actuator sub-packages (`apps/api/app/services/actuators/github/`,
`apps/api/app/services/actuators/fly/`) **never** emit events directly
— only the executor does. That keeps the event schema owned by one
service.

## 8. Safety rules

Do not add any path that allows:

- direct execution without a proposal
- silent policy bypass
- mutation without logging
- declaring success before health verification
- multi-writer access to `data/events.jsonl` (it is single-writer by
  design; hash-chain verification runs on startup and refuses to boot
  on a broken chain)

## 9. Docs rules

When changing architecture or workflow, update in the same PR:

- `docs/ARCHITECTURE.md`
- `docs/REPO_MAP.md` if file layout changes
- `docs/PARALLEL_DEVELOPMENT.md` if git workflow changes
- `docs/SESSION_HANDOFF.md` at the end of the session

Never rewrite prior `CHANGELOG.md` entries — append under `[Unreleased]`
or a new `[vX.Y.Z]` section.

## 10. Git workflow rules

- **Branch naming**: `feat/<topic>`, `docs/<topic>`, `chore/<topic>`,
  `ci/<topic>`, `fix/<topic>`. Phase-scoped work may use
  `feat/phase-N-<topic>`.
- **Commits**: small, conventional-commits style
  (`feat(deploy): ...`, `docs(design): ...`). Always sign with DCO:
  `git commit -s`.
- **Never skip hooks** (`--no-verify`). If a hook fails, fix the
  underlying issue — see `docs/SESSION_HANDOFF.md` gotchas.
- **Never force-push `main`**; feature-branch force pushes are
  blocked by the pre-tool hook. For stacked PRs, prefer merging `main`
  into the feature branch as a regular fast-forward push over a
  rebase + force-push cycle.
- **PRs**: one concern per PR. Use the PR template. Squash-merge into
  `main` (linear history is enforced). **Pause for the operator's
  confirmation before each merge** unless a durable instruction says
  otherwise.

## 11. Required CI checks on `main`

Every PR must pass all five before merge:

1. `lint + format + test` — ruff check, ruff format --check, pytest
   with `--cov-fail-under=60`
2. `gitleaks` — secret scanning
3. `pip-audit` — dependency CVE scanning (non-blocking informational)
4. `docker build` — image builds cleanly
5. `mypy` — `mypy --strict` across `apps/` (43+ source files today)

Branch protection enforces these. `gh pr checks <N> --watch` is the
standard way to wait for them.

## 12. Release rules

- Alpha tags: `vX.Y.Z-alpha.M`. Tag with `git tag -s vX.Y.Z-alpha.M -m
  "..."` and push. The `release.yml` workflow auto-creates the GitHub
  release and attaches an SPDX SBOM named
  `quorum-vX.Y.Z-alpha.M.spdx.json`.
- Update `CHANGELOG.md` under `[Unreleased]` → new version section
  before tagging.
- Update `docs/SESSION_HANDOFF.md` to mark the tag in the state block.

## 13. Definition of done for changes

A change is complete only when:

- code works
- `mypy --strict` is clean
- `ruff check` + `ruff format --check` are clean
- tests cover the changed path; full suite passes
- docs match the code (see §9)
- example payloads remain valid
- the change is understandable without external context
- CI shows all 5 required checks green

## 14. Cross-tool AI agent support

This repo supports any AI coding agent that honors `AGENTS.md`:

- **Codex** (OpenAI CLI) — reads `AGENTS.md` natively. No extra
  config needed.
- **Claude Code** — reads `CLAUDE.md`, which is a pointer to this
  file. Claude-specific batteries (`.claude/settings.json`, hooks,
  subagents, skills, slash commands, `.mcp.json`) sit under
  `.claude/`; Codex and other agents can safely ignore them.
- **Cursor / Windsurf / other** — read `AGENTS.md`.

Tool-specific config directories are advisory. If a `.claude/`
permission rule contradicts a rule in this file, this file wins.

## 15. If unsure

Choose the more explicit design.

When in doubt about the current project state (what shipped, what's
pending, what's next), read `docs/SESSION_HANDOFF.md` — it is refreshed
at the end of every substantial session and is more current than any
other file in the repo.
