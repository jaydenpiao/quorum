# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.1.0-alpha.1`](https://github.com/jaydenpiao/quorum/releases/tag/v0.1.0-alpha.1) — pre-release, SBOM attached as `quorum-sbom.spdx.json`.
- **Test suite:** 85 passing + 11 integration-gated (excluded from CI by default; opt-in with `pytest -m integration` against a live Postgres).
- **Coverage:** 79% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 29 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. Plus `gitleaks` via `security.yml` on PRs.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count:** 33.

## Phase status

- **✅ Phase 0** — Claude Code harness (`.claude/`, subagents, skills, slash commands, MCPs).
- **✅ Phase 1** — OSS hygiene (Apache-2.0, SECURITY/CONTRIBUTING/CoC, uv, CI hardening, Dependabot, branch protection).
- **✅ Phase 2** — core security (typed health checks, hash chain, bearer auth, CORS/headers/rate-limit/strict pydantic).
- **✅ Phase 2.5** — server-side actor binding, argon2id keys.
- **✅ Phase 3** — prod foundation (Dockerfile + compose, pytest-cov gate, structlog + X-Request-ID, Prometheus `/metrics`, mypy-strict required, SBOM on tag push, OpenTelemetry traces, log↔trace correlation).
- **✅ Phase 3 capstone** — Postgres projection (PRs #28, #30, #31, #32 + #33 for `health_check_completed`).
- **⬜ Phase 4** — first real actuator (GitHub App). **Design doc merged at `docs/design/phase-4-github-actuator.md`; implementation not started.**
- **⬜ Phase 5** — Fly.io deployment.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## Reading order for a fresh session

Canonical order — load these before touching code:

1. `AGENTS.md` — repo-wide operating rules and Definition of Done (binding).
2. **This file** (`docs/SESSION_HANDOFF.md`).
3. `docs/ROADMAP.md` — phase status with ✅/⏳/⬜/✂️ markers.
4. `CHANGELOG.md` — every feature since bootstrap under `[Unreleased]`.
5. `docs/design/phase-4-github-actuator.md` — the next implementation work.
6. `docs/design/postgres-projection.md` — reference (done, but the patterns used are reusable).
7. `docs/ARCHITECTURE.md` — the current system picture, including all components, auth flow, observability.

Area-specific deep reads are already linked from `AGENTS.md`'s "Required reading by area" section.

## Known gotchas (earned the hard way)

1. **Ruff `PostToolUse` hook strips unused imports.** When you add an import in one Edit and its usage in a separate Edit, the hook fires between them and may strip the import as unused. Fix: re-read the file and re-add the import after mypy / ruff errors report `F821`. Common for every multi-file refactor.
2. **`backend-engineer` subagent stalls on multi-file Python work.** Twice this session the subagent truncated mid-edit. Drive multi-file backend work in the main thread; dispatch `devops-engineer` (reliable) for CI/docs/Dockerfile work.
3. **Gitleaks hits on test-fixture plaintext strings that look like API keys.** Use short, obviously-fake literals (e.g. `"fake-test-plaintext"`) or add a narrow `.gitleaks.toml` allowlist for the specific file. Force-push is denied by `.claude/settings.json`, so rewriting a committed fixture requires a follow-up commit (not a rebase).
4. **Output classifier can trip on aggregated security-heavy language.** Symptom: mid-response error about content filtering. Mitigation: keep commit messages lean, don't re-list all known bugs in every PR body, reference `SECURITY.md` instead of restating.
5. **`.env.example` was blocked by an over-broad deny rule.** Fixed in PR #29. If you see `Read(**/.env.example)` fail, the deny list probably regressed — check `.claude/settings.json`.
6. **`docs-writer` subagent has no `Bash` tool.** It can Read/Edit/Write but can't `git commit`. Pattern: dispatch it, then finish the git ops yourself from the worktree.
7. **Subagent worktrees stay locked** after completion. They accumulate under `.claude/worktrees/` (gitignored). Clean up with `git worktree remove --force ...` when the branch is merged; otherwise harmless.
8. **Dispatch-completeness test in `tests/test_postgres_projector.py`** will fail if you add a new event type without a projector handler. It's a regression guard — do not silence it; add the handler.
9. **`EventLog.append` is sync** (multiple sync callers). If you touch the projector, keep `apply(event)` sync — flipping async is a cross-cutting refactor. See sync-vs-async deviation note in `docs/design/postgres-projection.md`.
10. **Hash chain verification runs on startup.** A tampered or pre-chain `data/events.jsonl` (from before PR #8) will refuse to boot. Reset with `make reset` or `rm -f data/events.jsonl` when needed.

## Next-session candidates (pick one, by priority)

### A — Phase 4 PR A: GitHub App scaffold + auth

**Scope** (per design doc's "Rollout plan"):
- `apps/api/app/services/actuators/github/__init__.py` + `auth.py` + `client.py` + `specs.py` skeleton
- GitHub App JWT → installation-token cache (`PyJWT`, `cryptography` new deps)
- `config/github.yaml` (committed, no secrets) with app_id + installation list
- `QUORUM_GITHUB_APP_PRIVATE_KEY` / `..._PATH` env vars
- Unit tests for token minting, 401 renewal, cache TTL — **no live GitHub calls**
- No action dispatch yet — that's PR B

**Size:** ~500 LOC. Drive in main thread (backend-engineer subagent unreliable). 1 PR.

**Blocker:** none — a fixture repo isn't needed until PR B's live integration tests.

### B — Fixture repo (one-time, operator action, ~2 min)

Create `github.com/jaydenpiao/quorum-actuator-fixtures` (public, empty, throwaway). Needed before Phase 4 PR B's `QUORUM_GITHUB_LIVE_TESTS=1` integration tests can run, not before.

### C — LLM adapter scaffolding

Use the `claude-api` skill (prompt caching, SDK integration). Not yet designed — would need a brief design pass before implementation. Natural after Phase 4 PR A since an LLM agent is the natural second consumer of `require_agent` auth.

### D — Minor follow-ups worth batching into a single PR

- The SBOM release asset is named `quorum-sbom.spdx.json` instead of `quorum-v0.1.0-alpha.1.spdx.json` — `anchore/sbom-action@v0` overrides the `output-file` input for release assets. Fix: adjust workflow to move the artifact to a versioned filename before the upload-release-assets step, or use `gh release upload` in a dedicated step.
- Emit richer context in the existing `_log.warning("projector_status_update_for_missing_proposal", ...)` so operators can triage out-of-order projection.
- Clean up the stale locked worktrees under `.claude/worktrees/` with a `make clean-worktrees` target (currently a manual `git worktree remove --force`).

## Parallel development — my recommendation

One-operator development does not need three simultaneous `claude` processes. The pattern that has worked best this session:

- **One main thread** drives each PR end-to-end (branch, code, tests, push, PR, CI, merge).
- **Parallel `Agent` tool dispatches with `isolation: "worktree"`** for independent lanes that don't share files — especially devops/docs work alongside a backend change.
- `run_in_background: true` on dispatched agents so the main thread keeps moving; a completion notification arrives automatically.
- **Main thread finishes git ops for any subagent without `Bash`** (notably `docs-writer`).

Going further — genuine multi-terminal `claude` sessions per worktree — is Phase 6 territory and worth the operational overhead only once there are multiple concurrent contributors (human + AI) stepping on each other. See `docs/PARALLEL_DEVELOPMENT.md`.

## Maintenance notes

- **Dependabot:** weekly Python, monthly Actions. Expect a handful of PRs per week; most are safe single-file lower-bound bumps. Review diff, merge.
- **CI cadence:** all 5 required checks run in parallel in ~15–35 s each. `mypy` is the slowest.
- **Release cadence:** tag when a meaningful feature set accumulates under `[Unreleased]` in CHANGELOG. Alpha tags are `v0.N.0-alpha.M`.

---

*Update this file at the end of every substantial session. Future-you reads it first.*
