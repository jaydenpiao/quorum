# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.1.0-alpha.1`](https://github.com/jaydenpiao/quorum/releases/tag/v0.1.0-alpha.1) — pre-release, SBOM attached as `quorum-sbom.spdx.json`.
- **Test suite:** 172 passing + 11 integration-gated (excluded from CI by default; opt-in with `pytest -m integration` against a live Postgres).
- **Coverage:** 83.43% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 35 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. Plus `gitleaks` via `security.yml` on PRs.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 38 (Phase 4 merged four PRs in a single session: #35 / #36 / #37 / #38).

## Phase status

- **✅ Phase 0** — Claude Code harness (`.claude/`, subagents, skills, slash commands, MCPs).
- **✅ Phase 1** — OSS hygiene (Apache-2.0, SECURITY/CONTRIBUTING/CoC, uv, CI hardening, Dependabot, branch protection).
- **✅ Phase 2** — core security (typed health checks, hash chain, bearer auth, CORS/headers/rate-limit/strict pydantic).
- **✅ Phase 2.5** — server-side actor binding, argon2id keys.
- **✅ Phase 3** — prod foundation (Dockerfile + compose, pytest-cov gate, structlog + X-Request-ID, Prometheus `/metrics`, mypy-strict required, SBOM on tag push, OpenTelemetry traces, log↔trace correlation).
- **✅ Phase 3 capstone** — Postgres projection (PRs #28, #30, #31, #32 + #33 for `health_check_completed`).
- **✅ Phase 4** — GitHub App actuator (PRs #35 / #36 / #37 / #38). First real actuator wired through the full control plane: policy → quorum → dispatch → health checks → actuator-aware rollback. `github.open_pr` is the only action shipped in this phase; `comment_issue` / `close_pr` / `add_labels` and `HealthCheckKind.github_check_run` remain as small, pattern-following follow-ups.
- **⬜ Phase 5** — Fly.io deployment.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## Phase 4 — what actually landed

Four DCO-signed, squash-merged PRs, all against `main`:

- **PR #35 (PR A) — auth scaffold.** `AppJWTSigner` (RS256), `InstallationTokenCache` (60 s refresh margin, thread-safe, single-retry-on-401 wrapper), `GitHubAppClient`, typed config loader for a new `config/github.yaml`. Private key from `QUORUM_GITHUB_APP_PRIVATE_KEY` or `..._PATH` env — never logged, scrubbed from exception chains.
- **PR #36 (PR B1) — `github.open_pr` action.** `GitHubOpenPrSpec` / `GitHubFileSpec` / `OpenPrResult` + `derive_head_branch()`. Safety rails at the pydantic boundary: repo-path validator, UTF-8 byte-size cap, reserved-base guard, duplicate-path rejection, file-count cap. Client grows `get_branch`, `create_blob`, `create_tree`, `create_commit`, `create_ref`, `create_pull_request`. `actions.open_pr` orchestrates `base → blobs → tree → commit → ref → PR`.
- **PR #37 (PR B2) — executor dispatch + policy rules + main wiring.** `Executor` dispatches on `proposal.action_type`; `github.*` routes to the actuator. `Proposal.payload` (typed, 256 KiB JSON cap) and `ExecutionRecord.result` added. `PolicyEngine` merges a new `action_type_rules` section (MAX votes_required, OR requires_human). `main.py` optionally constructs a `GitHubAppClient` — a misconfigured actuator never blocks deploy.
- **PR #38 (PR C) — actuator-aware rollback + `rollback_impossible` event.** New terminal event type with all five create-event-type touch points (`RollbackImpossibleRecord`, reducer, projector handler, dispatch-completeness regression guard, example JSON). `rollback_open_pr` closes the PR + deletes the branch (idempotent on 404/422); merged PRs raise `RollbackImpossibleError` with enough state for a human to revert manually. `docs/ARCHITECTURE.md` gets an Actuators section.

**What is NOT yet done in Phase 4** (all pattern-following, small):

- `github.comment_issue` / `github.close_pr` / `github.add_labels` actions + their rollback functions.
- `HealthCheckKind.github_check_run` + runner (poll a commit's check-runs until terminal status). The existing `http` kind can loosely cover CI-readiness probes in the meantime.
- A live fixture repo `github.com/jaydenpiao/quorum-actuator-fixtures` (one-time operator action, ~2 min) to unlock the `QUORUM_GITHUB_LIVE_TESTS=1` integration-test gate. Still not needed to demo.

## Reading order for a fresh session

Canonical order — load these before touching code:

1. `AGENTS.md` — repo-wide operating rules and Definition of Done (binding).
2. **This file** (`docs/SESSION_HANDOFF.md`).
3. `docs/ROADMAP.md` — phase status with ✅/⏳/⬜/✂️ markers.
4. `CHANGELOG.md` — every feature since bootstrap under `[Unreleased]`.
5. `docs/design/phase-4-github-actuator.md` — implemented; still worth reading to understand actuator-contract invariants.
6. `docs/design/postgres-projection.md` — reference (done, but the patterns used are reusable).
7. `docs/ARCHITECTURE.md` — current system picture including the new Actuators section.

Area-specific deep reads are already linked from `AGENTS.md`'s "Required reading by area" section.

## Known gotchas (earned the hard way)

1. **Ruff `PostToolUse` hook strips unused imports — hit often during Phase 4.** When you add an import in one Edit and its usage in a separate Edit, the hook fires between them and strips the import. Two workarounds that both work: (a) add the import **and** its first usage in a single atomic Edit, or (b) for larger diffs, use `Write` to rewrite the file wholesale — the formatter sees only the final state and keeps every import that is used there. (a) is lower-blast-radius; (b) is safer for multi-import refactors.
2. **`backend-engineer` subagent stalls on multi-file Python work.** Held across this session too — all Phase 4 PRs were driven on the main thread.
3. **Gitleaks hits on test-fixture plaintext strings that look like API keys.** Use short, obviously-fake literals or a narrow `.gitleaks.toml` allowlist. Phase 4 avoided this entirely by generating RSA keypairs at pytest fixture time instead of committing PEM literals.
4. **Output classifier can trip on aggregated security-heavy language.** Keep PR bodies lean, reference `SECURITY.md` instead of re-listing bugs.
5. **`.env.example` was blocked by an over-broad deny rule.** Fixed in PR #29; if it regresses, check `.claude/settings.json`.
6. **`docs-writer` subagent has no `Bash` tool.** Dispatch it, then finish the git ops yourself.
7. **Subagent worktrees stay locked** after completion. Clean up with `git worktree remove --force ...`.
8. **Dispatch-completeness test in `tests/test_postgres_projector.py`** fails if you add a new event type without a projector handler. Phase 4 PR C added `rollback_impossible` with its handler + updated expected set in the same commit — treat this as the mandatory template for new event types.
9. **`EventLog.append` is sync.** Keep `apply(event)` sync; flipping async is a cross-cutting refactor.
10. **Hash chain verification runs on startup.** A tampered or pre-chain `data/events.jsonl` (from before PR #8) will refuse to boot. Reset with `make reset` or `rm -f data/events.jsonl` when needed.

## Next-session candidates (pick one, by priority)

### A — Phase 4 follow-ups: remaining GitHub actions + `github_check_run`

Each follow-up is a small PR that reuses the PR B1 / PR C pattern. Natural grouping:

- **PR D** — `github.comment_issue` + `github.close_pr` + `github.add_labels` actions. Each needs: typed spec in `specs.py`, client REST method(s), `actions.<name>` function, rollback function (comment delete, PR reopen, remove-added-labels), executor dispatch branch, policy rule row. ~600 LOC total.
- **PR E** — `HealthCheckKind.github_check_run`. Spec fields (owner/repo/head_sha/check_name), runner that polls `/commits/{sha}/check-runs` with a timeout, integration with the actuator result so `head_sha` is threaded from `OpenPrResult`. ~300 LOC.

Both are fully specified in `docs/design/phase-4-github-actuator.md`.

### B — Fixture repo (one-time, operator action, ~2 min)

Create `github.com/jaydenpiao/quorum-actuator-fixtures` (public, empty, throwaway). Needed before `QUORUM_GITHUB_LIVE_TESTS=1` integration tests can run. Still not needed to demo.

### C — Phase 5: Fly.io deployment

- `fly.toml`, Fly Volume for canonical JSONL, Neon Postgres for projection.
- Staging + prod apps.
- Dog-food deploys: production deploys flow through the Quorum API itself (deploy-agent → code-agent votes → operator approves → executor calls `fly deploy ...@sha256:...`).

Unlocks the end-to-end "Quorum deploys Quorum" story. Depends on nothing new — Phase 4 shipped with the deploy primitives Phase 5 needs.

### D — LLM adapter scaffolding

Use the `claude-api` skill (prompt caching, SDK integration). Not yet designed — brief design pass first. Natural second consumer of `require_agent` auth.

### E — Minor follow-ups worth batching into a single PR

- SBOM release asset is named `quorum-sbom.spdx.json` instead of versioned (e.g. `quorum-v0.1.0-alpha.1.spdx.json`). `anchore/sbom-action@v0` overrides the `output-file` for release assets; fix with a rename step before `upload-release-assets`.
- Richer context in `_log.warning("projector_status_update_for_missing_proposal", ...)` for out-of-order projection triage.
- `make clean-worktrees` target for stale locked `.claude/worktrees/` (today a manual `git worktree remove --force`).
- Consider tagging `v0.2.0-alpha.1` to cut an SBOM against the Phase 4 work — `[Unreleased]` now covers four PRs of actuator + rollback features.

## Parallel development — my recommendation

Unchanged from the prior session:

- **One main thread** drives each PR end-to-end. Phase 4 was four PRs in one session, all main-thread.
- **Parallel `Agent` tool dispatches with `isolation: "worktree"`** for independent lanes that don't share files — especially devops/docs work alongside a backend change.
- `run_in_background: true` on dispatched agents.
- **Main thread finishes git ops for any subagent without `Bash`** (notably `docs-writer`).
- **Genuine multi-terminal `claude` sessions per worktree** is Phase 6 territory.

See `docs/PARALLEL_DEVELOPMENT.md`.

## Maintenance notes

- **Dependabot:** weekly Python, monthly Actions. Expect a handful of PRs per week; most are safe single-file lower-bound bumps. Review diff, merge.
- **CI cadence:** all 5 required checks run in parallel in ~15–35 s each. `mypy` is the slowest. Phase 4's PRs all landed inside this envelope.
- **Release cadence:** tag when a meaningful feature set accumulates under `[Unreleased]` in CHANGELOG. Alpha tags are `v0.N.0-alpha.M`. Phase 4 is a good tagging cut-point.

---

*Update this file at the end of every substantial session. Future-you reads it first.*
