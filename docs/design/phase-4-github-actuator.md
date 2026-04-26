# Design: GitHub App actuator (Phase 4 kickoff)

Status: design proposal — no code in this PR. Target: 2–3 implementation PRs
after review.

## Context and goal

Quorum today validates its state machine end-to-end with a simulated
executor. To deliver on the product promise — "AI agents can mutate real
infrastructure safely" — we need at least one real actuator. GitHub is the
lowest-risk, highest-value starting point:

- every mutation lands as a PR reviewable by humans and CI
- rollback is trivial (close PR, delete branch)
- the "blast radius" is bounded to one repo per install
- testing against a fixture repo is cheap
- it exercises every control-plane primitive (policy, quorum, health checks,
  event log) against real side-effects

Out of scope here: direct `git push` to `main`, raw GitHub REST passthrough,
arbitrary workflow dispatch. Those are deliberately omitted — they are
either unreviewable (main push) or too broad (passthrough).

## Non-goals

- Replace human-reviewed PRs. This actuator **opens** PRs; merging stays
  human or a future separate quorum.
- Deploy to production from GitHub. Phase 5 owns `fly deploy`; this
  actuator does not.
- Run arbitrary GitHub Actions workflows. Only `github_check_run` as a
  health-check kind, read-only.
- Multi-org. v1 supports exactly one GitHub App install per Quorum
  deployment.

## Authentication: GitHub App, not PAT

**Decision: GitHub App.** Per-install short-lived installation tokens,
scoped permissions, rotation without redeploying, no single-user dependency
if the PAT holder leaves. A PAT would be faster to prototype but leaves
each Quorum deployment glued to one operator's identity — unacceptable for
a control plane meant to outlive any individual.

App configuration (out-of-band, one-time per deploy):

- App name: "Quorum Actuator"
- Homepage: `https://github.com/jaydenpiao/quorum`
- Webhook: **disabled** (v1 is pull-only; actuator polls health checks)
- Permissions:
  - Repository contents: **Read & write** (for PRs + patches)
  - Pull requests: **Read & write**
  - Issues: **Read & write** (comments)
  - Metadata: Read (implicit)
  - Checks: **Read** (for `github_check_run` health checks)
  - Actions: Read (workflow run status)
- Install on a per-target basis; install IDs recorded in
  `config/github.yaml` (new; see Config below).

Operational bootstrap is now scripted by
`python -m apps.api.app.tools.bootstrap_github_app`; see
`docs/GITHUB_APP_ACTUATOR_FLY.md` for the Fly-specific runbook. The
script uses GitHub's manifest flow to prefill these settings, but the
operator still approves App creation and repository installation in
GitHub's UI.

Secret material:

- **App ID** — non-secret, public in config.
- **App private key (PEM)** — provided via env var
  `QUORUM_GITHUB_APP_PRIVATE_KEY` (PEM string),
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` (base64-encoded PEM, preferred
  on Fly), or mounted path `QUORUM_GITHUB_APP_PRIVATE_KEY_PATH`. Never
  committed, never logged, scrubbed from error messages.
- **Installation access tokens** — minted on demand via JWT; cached in
  memory with ~50-minute TTL (GitHub's tokens last 60 minutes; rotate early).

Token minting uses `PyJWT` + `cryptography`. Two new dependencies; both
Apache-2.0 compatible.

## Action taxonomy

`Proposal.action_type` string → actuator method mapping. v1 scope:

| `action_type`              | What it does                                                    | Destructiveness | Auto-rollback      |
|----------------------------|-----------------------------------------------------------------|-----------------|--------------------|
| `github.open_pr`           | Open a PR on a feature branch with supplied file-list patch     | Low             | Close PR, delete branch |
| `github.comment_issue`     | Add a comment to an existing issue or PR                        | Very low        | Delete comment (best-effort) |
| `github.close_pr`          | Close an existing PR without merging                            | Low             | Reopen PR          |
| `github.add_labels`        | Add labels to an issue or PR                                    | Very low        | Remove added labels |

Explicitly **not** in v1:

- `github.merge_pr` — merging is where blast radius explodes; requires its
  own design PR, probably with a distinct quorum size and mandatory human
  approval.
- `github.push_to_branch` — raw force push; bypasses review, never.
- `github.dispatch_workflow` — arbitrary code execution; revisit with
  allowlist.

Every action's payload is a typed pydantic model (`GitHubOpenPrSpec`,
`GitHubCommentSpec`, etc.) with `extra='forbid'` and bounded string lengths
(same rules as the existing `ProposalCreate` inputs).

Safety rails (hard-coded in the actuator, not policy-configurable):

- The `base` branch in `open_pr` must NOT be `main`, `master`, `release/*`,
  or any branch whose GitHub-API metadata reports `protected: true`.
  Rejected with 400 at proposal-validation time.
- The `head` branch name must be derived from the proposal id:
  `quorum/<proposal_id>`. Non-derivable names are rejected so rollback can
  deterministically find the branch.
- File writes are bounded: max 200 files per PR, max 64 KiB per file.
  Oversize → reject.
- Binary files disallowed in v1; text-only (UTF-8 validated). Revisit when
  a concrete use case appears.

## Actuator module layout

```
apps/api/app/services/actuators/
  __init__.py
  github/
    __init__.py              # public `GitHubActuator` class
    auth.py                  # App JWT → installation token cache
    client.py                # thin httpx wrapper with rate-limit backoff
    actions.py               # one function per action_type
    specs.py                 # typed pydantic payload models
```

Public interface matches the `add-actuator` skill contract:

```python
class GitHubActuator:
    def execute(self, proposal: Proposal) -> ExecutionRecord: ...
    def rollback(self, proposal: Proposal, execution: ExecutionRecord) -> None: ...
```

The actuator does not emit events — the executor does, per
`AGENTS.md` logging rules. The actuator returns typed records; the
executor wraps them in `execution_started` / `execution_succeeded` /
`execution_failed` / `rollback_*` envelopes.

## Health check: `github_check_run`

New `HealthCheckKind.github_check_run`. Spec fields:

```python
class HealthCheckSpec(BaseModel):
    kind: HealthCheckKind  # now includes `github_check_run`
    ...
    # when kind == github_check_run:
    github_owner: str | None           # e.g. "jaydenpiao"
    github_repo: str | None            # e.g. "quorum"
    github_check_run_id: int | None    # known at execute-time
    timeout_seconds: float = 300.0     # default 5 min for CI waits
```

Runner polls `GET /repos/{owner}/{repo}/check-runs/{run_id}` at a short
fixed interval (e.g. 5 s), passes if `status=completed &
conclusion=success`, fails on `conclusion in {failure, timed_out, cancelled}`
or wall-clock timeout. Same validator style as the existing `http` kind
rejects unsafe values.

Alternative considered and rejected: use webhooks. Simpler to poll for v1;
webhooks require a public endpoint and signature verification that's its
own ~2 PRs of work.

## Policy interaction

`config/policies.yaml` gets per-`action_type` overrides. Example:

```yaml
action_type_rules:
  github.open_pr:
    votes_required: 2
    requires_human: false
  github.close_pr:
    votes_required: 2
    requires_human: false
  github.comment_issue:
    votes_required: 1
    requires_human: false
  github.add_labels:
    votes_required: 1
    requires_human: false
```

`policy_engine.evaluate` merges these with the existing risk-level rules,
taking the MAX of the two vote requirements. An unknown `action_type` uses
the risk-level default (current behavior).

No changes to the event schema — action-type-specific metadata goes in
the existing `proposal.payload` blob.

## Config

New file `config/github.yaml` (committed, no secrets):

```yaml
app:
  app_id: 123456          # filled in by operator
  installations:
    - owner: jaydenpiao
      repo: quorum
      installation_id: 78910
limits:
  max_files_per_pr: 200
  max_file_bytes: 65536
  poll_interval_seconds: 5
```

Loaded the same way as `config/policies.yaml` — YAML, cached, reloaded on
process restart only.

## Test strategy

Three layers:

1. **Unit** (fast, always on) — mock the GitHub REST surface with
   `respx`. Cover: token minting, 401 renewal, rate-limit backoff, each
   action type's happy and failure paths, reject-on-protected-base, branch
   name derivation.
2. **Integration against fixture repo** (slow, gated by env var
   `QUORUM_GITHUB_LIVE_TESTS=1`) — fixture repo
   `jaydenpiao/quorum-actuator-fixtures`, marked via
   `pytest.mark.integration` and excluded from default CI. Current
   coverage creates a `github.comment_issue`, rolls it back with
   `rollback_comment_issue`, and verifies GitHub returns 404 for the
   deleted comment.
3. **Contract** — a `schemathesis` run over the new pydantic specs to
   catch shape regressions.

We do NOT test against a mirror of the production Quorum repo — too much
noise for too little safety signal.

## Failure and rollback semantics

Every action declares a rollback strategy up front:

| Action              | Rollback                                   | Failure mode                    |
|---------------------|--------------------------------------------|---------------------------------|
| `github.open_pr`    | Close PR, delete `quorum/<proposal_id>`    | API 404 on close = already closed; log + continue. Branch delete failure = warning event + leave branch. |
| `github.comment_issue` | `DELETE /comments/{id}` (best-effort)   | 404 = already deleted; pass. 403 = log + continue. |
| `github.close_pr`   | Reopen PR via `PATCH state=open`           | If PR was deleted, rollback impossible — emit an explicit `rollback_impossible` event and notify operator. |
| `github.add_labels` | Remove only labels the actuator added      | Track added labels in the `ExecutionRecord` so rollback is deterministic. |

"Rollback impossible" is a recognized terminal state — we do NOT pretend it
succeeded. Event emitted, alert fires, human takes over.

## Rate limiting and retries

- Respect `X-RateLimit-*` headers. When `remaining < 10`, wait until reset
  or yield to a lower-priority actor.
- 5xx retries: exponential backoff with jitter, 3 attempts max.
- 4xx are terminal (except 401, which triggers one token renewal).
- The actuator itself is rate-limited at the Quorum layer too: a
  per-install leaky-bucket (e.g., 60 write-actions/minute) so a runaway
  agent can't exhaust the install's GitHub quota.

## Observability

Traces (OTel, from Phase 3):
- One span per actuator call with attributes `quorum.action_type`,
  `quorum.proposal_id`, `github.owner`, `github.repo`,
  `github.installation_id`.
- GitHub API calls get child spans via the existing
  `opentelemetry-instrumentation-httpx` (new dep, add in implementation
  PR).

Metrics (Prometheus, from Phase 3):
- `quorum_actuator_calls_total{actuator="github", action_type=...}`
- `quorum_actuator_duration_seconds{...}` histogram
- `quorum_github_rate_limit_remaining{installation_id=...}` gauge

Logs (structlog JSON, from Phase 3):
- Every call logs `event=github_action_started/succeeded/failed` with the
  IDs above. Never log the installation token.

## Rollout plan (2–3 PRs)

**PR A — scaffold & auth** (~500 LOC)
- `apps/api/app/services/actuators/github/` skeleton
- `auth.py` with JWT + installation-token cache
- `client.py` httpx wrapper
- `config/github.yaml` + loader
- Unit tests for token minting, cache TTL, 401-renewal
- No `action_type` dispatch yet — just the plumbing

**PR B — first action: `github.open_pr` end-to-end** (~700 LOC)
- `actions.open_pr`, branch-derivation, patch application
- Executor dispatch wiring; emit existing `execution_started`/`succeeded`/
  `failed` events with the new action_type string
- `HealthCheckKind.github_check_run` + runner
- Policy-engine action_type-rules merge
- Unit + contract tests. Integration tests gated by live-test env var.

**PR C — the rest: comment, close, labels + rollback** (~400 LOC)
- Remaining actions + rollback paths
- `rollback_impossible` event type (needs the `create-event-type` skill)
- Docs: `docs/ARCHITECTURE.md` gets an Actuators section

Each PR passes the existing 5 required CI checks, adds its own tests, no
event-log schema change, no auth change.

## Open questions (for review)

1. **Install lookup.** Should `config/github.yaml` carry install IDs, or
   should the actuator auto-discover them via
   `GET /app/installations`? Discovery is simpler operationally but
   widens the App's metadata scope. Lean: explicit config.
2. **Patch format.** Accept raw file contents, or a unified diff? File
   contents is simpler and matches how LLM agents want to write. Diffs are
   more reviewable as proposals. Could support both; start with contents.
3. **Multi-repo per install.** A single installation can cover multiple
   repos in an org; do we model that? v1: allow multiple repos in the
   install list, keyed by `owner/repo`.
4. **Signed commits.** Once the actuator writes commits, do we require
   GPG/Sigstore signing for operator-audit purposes? Defer to a later
   security PR; v1 commits are unsigned but attributed to the Quorum App.
5. **Abuse of `comment_issue`.** Cheap action, low threshold — could be
   spammed. Add a per-install per-issue rate limit? Or a de-dupe ("don't
   comment the same body twice in a row")? Lean: de-dupe; simpler than a
   second rate-limit knob.

---

## Dependencies landing this brings

- `PyJWT>=2.8.0` (Apache-2.0 side of the MIT/Apache dual licensing; we
  pin Apache)
- `cryptography>=42.0.0` (Apache-2.0/BSD dual; Apache-2.0 satisfies)
- `respx>=0.22.0` (dev only — pinned, test-only; BSD-3-Clause, Apache-compat)
- `opentelemetry-instrumentation-httpx>=0.50b0` (Apache-2.0)

## Success criteria (for review approval)

- A reviewer, reading this doc top-to-bottom, can tell me:
  (a) whether we do GitHub App or PAT (answered: App, reasons above);
  (b) which actions land in v1 and which are deferred;
  (c) how rollback works per action;
  (d) how tests avoid hitting production GitHub;
  (e) what the PR breakdown is.
- An implementing agent, handed PR A's spec above, can complete it without
  re-reading the design or re-opening closed decisions.

If you can't answer one of those from this doc alone, it's a bug in the
doc — file an open question above.
