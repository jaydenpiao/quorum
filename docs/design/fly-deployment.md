# Design: Fly.io deployment (Phase 5 kickoff)

Status: design proposal — no code in this PR. Target: **3 implementation
PRs** after review (this PR → `fly.toml` + readiness endpoint → deploy-agent
wiring).

## Context and goal

Phase 4 shipped a control plane that can cause real GitHub side-effects
and a Claude-backed telemetry agent that files findings and proposals
through the same API as any other caller. The next unlock is running the
same control plane in production — staging + prod on Fly.io — and
wiring the control plane to deploy **itself** (dog-food).

Fly.io is the chosen host because:

- Fly Machines + Fly Volumes give us a single-writer append-only filesystem
  for `data/events.jsonl` without us running disks. Our `EventLog` is
  sync single-writer with a sha256 hash chain verified on boot
  (`apps/api/app/services/event_log.py`), so shared / multi-writer
  storage would break the invariant.
- Fly secrets are injected as env vars at boot — matches how the app already
  reads `QUORUM_API_KEYS`, `QUORUM_GITHUB_APP_PRIVATE_KEY`, `DATABASE_URL`,
  etc. No code change required to consume them.
- The Fly Registry and `fly deploy --image ...@sha256:...` give us a
  content-addressable deploy primitive the `fly.deploy` actuator can call,
  so dog-food deploys land naturally.
- Neon Postgres is the already-chosen projection host
  (`docs/design/postgres-projection.md` §7 "Prod"). Fly in US-East +
  Neon in US-East is low-ms.

**Goal for Phase 5**: a reviewer should be able to tell from this doc
alone what runs where, what state lives where, which secrets are loaded,
and how a dog-food deploy flows through the existing quorum engine.

Out of scope here: multi-region fleets, active-active HA, any change to
how the event log is persisted, SSO, multi-tenant isolation. Those are
deliberately deferred — none of them are blocking a first production
cut, and each widens the security surface.

## Non-goals

- **Multi-machine fleets per app.** Fly Volumes are per-machine, not
  shared; and `EventLog` is single-writer. Each Fly app (`quorum-staging`,
  `quorum-prod`) runs exactly one machine. Scaling out is a separate
  design once the log is migrated off local disk.
- **Migrating the event log off the local filesystem.** JSONL stays
  canonical per `docs/design/postgres-projection.md`. No S3, no EFS, no
  shared volume.
- **A new authentication surface.** `QUORUM_API_KEYS` with argon2id
  hashes remains the only way to mutate state. No SSO, no IAM.
- **Running the LLM agent in the same Fly app as the API.** The
  telemetry-llm-agent is a separate process today and stays separate;
  co-locating it is a later decision once we see prod token spend.
- **Webhooks / inbound GitHub events.** The GitHub actuator is
  pull-only; no public webhook endpoint in Phase 5.
- **Zero-downtime rolling deploys.** With one machine per app, a deploy
  briefly drops SSE connections. Acceptable for v1; revisit if
  operators complain.

## App topology

Two Fly apps, one per environment. Identical shape.

| app              | region | machines                    | volume                     | postgres            | scale-to-zero |
|------------------|--------|-----------------------------|----------------------------|---------------------|---------------|
| `quorum-staging` | `iad`  | 1 (shared-cpu-1x, 512 MB)   | `quorum_data` (1 GiB)      | Neon branch of prod | yes |
| `quorum-prod`    | `iad`  | 1 (shared-cpu-1x, 512 MB)   | `quorum_data` (1 GiB)      | Neon prod DB        | no (SSE, see §Scale-to-zero) |

Single-machine-per-app is a hard constraint, not a size tradeoff, because
of the Fly Volume + single-writer EventLog coupling described above.

Internal HTTP service on `:8080` (matches `Dockerfile` line 49 `EXPOSE 8080`
and the existing uvicorn entrypoint at `Dockerfile` line 59). No other
listener needed.

## Fly Volume: event-log storage

Mount one volume per app at `/app/data` (matches `Dockerfile` line 52
`VOLUME ["/app/data"]`). The hard-coded path `data/events.jsonl` in
`config/system.yaml:4` resolves to `/app/data/events.jsonl` at container
runtime.

The Fly Volume name is `quorum_data` in each app. Fly scopes volume
names to an app, so `quorum-staging` and `quorum-prod` can both use the
same `fly.toml` mount source without sharing storage or violating
single-writer semantics.

**Size:** 1 GiB per volume to start. At current event rate
(~500 B–1 KiB per event, ~20 event types, low proposal volume per day)
a year of history fits in ~100 MiB. Resize via `fly volumes extend` is
non-disruptive. Revisit size when we hit 50%.

**Region pinning:** Fly Volumes are region-local. When Fly auto-replaces
a machine, the new machine must come up in the **same region** as the
attached volume — we configure this explicitly in `fly.toml`
(`primary_region`) and never run the app in multi-region mode. A lost
volume means the canonical event log is gone; the JSONL is authoritative
per `docs/design/postgres-projection.md` §1, so this is a recovery event,
not routine.

**Snapshots:** Fly's default daily snapshot + 5-day retention is enough.
Restore drill is documented in the PR #51 release notes (not this PR):
stop the machine, attach the snapshot as a new volume, boot. Hash-chain
verification on startup is the integrity gate — a tampered or
truncated `events.jsonl` **refuses to boot**
(SESSION_HANDOFF gotcha #10). `make reset` remains the only sanctioned
wipe path.

**`log_path` is currently not env-var configurable.** It is read from
`config/system.yaml:4`. That's a follow-up, not a Phase 5 blocker —
mounting `/app/data` matches the hard-coded default.

## Managed Postgres: Neon vs Fly Postgres

The projection (`docs/design/postgres-projection.md`) is a derived
read-model. Either host works. Comparison at our expected scale:

| axis          | Neon (managed serverless)              | Fly Postgres (unmanaged HA preset)                     |
|---------------|----------------------------------------|--------------------------------------------------------|
| Ops burden    | Zero — fully managed, auto-scaling     | Operator-managed (backups, version upgrades, failover) |
| Cost at our rate | Free tier covers staging; paid tier for prod is single-digit $/mo | Cheapest option — a `shared-cpu-1x` Fly machine is ~$2/mo but requires our own backups |
| Branching     | First-class DB branching (staging is a branch of prod — locked by `docs/design/postgres-projection.md` §7) | No branching; needs a full second instance |
| Latency from `iad` | Low-ms to Neon `us-east-2`         | Sub-ms (co-located, same region)                       |
| `DATABASE_URL` format | `postgresql://...?sslmode=require` | `postgresql://...`; both rewritten to `postgresql+psycopg://` by `apps/api/app/db/engine.py` lines 29–33 |
| Backup story  | Point-in-time recovery, managed        | We run `pg_dump` on a schedule, or rely on JSONL replay |

**Recommendation: Neon for both staging and prod.** Zero ops burden,
the branching story is already assumed by the projection design, and
the latency gap is not load-bearing for an asynchronous projection.
Fly Postgres is a reasonable fallback if Neon cost or egress becomes an
issue at scale, but nothing in the design assumes we'll ever switch.

Marked **open question #5** for the operator — this is a cost / lock-in
decision worth explicit sign-off.

## Secrets

Fly secrets are injected as env vars at process start. We set each via
`fly secrets set KEY=VALUE --app quorum-{staging,prod}`. The app already
reads all of them from the environment; no code change required.

| env var                              | required? | read at                                              | notes |
|--------------------------------------|-----------|------------------------------------------------------|-------|
| `QUORUM_API_KEYS`                    | yes       | `apps/api/app/services/auth.py:46`                   | `agent_id:plaintext,...` — bootstrap-CLI-generated; operator rotates |
| `QUORUM_GITHUB_APP_PRIVATE_KEY`      | yes (for GitHub actuator path) | `apps/api/app/services/github/auth.py:56` | Inline PEM. Prefer over `QUORUM_GITHUB_APP_PRIVATE_KEY_PATH` to avoid filesystem mounts on Fly |
| `DATABASE_URL`                       | yes       | `apps/api/app/db/engine.py:23`                       | From the Neon attachment; sync `psycopg` dialect is auto-injected by the rewriter |
| `FLY_API_TOKEN`                      | yes (for `fly.deploy`) | `flyctl` subprocess environment | Deploy-scoped token used by `/usr/local/bin/fly`; required anywhere the executor may run `fly.deploy` |
| `ANTHROPIC_API_KEY`                  | no, for now | consumed by the telemetry-llm-agent process only, which is not co-located in Phase 5 | set later if / when we run the LLM agent in-cluster |
| `QUORUM_LOG_LEVEL`                   | optional  | `apps/api/app/logging_config.py:35`                  | default `INFO`; structlog JSON output |
| `OTEL_EXPORTER_OTLP_ENDPOINT`        | optional  | `apps/api/app/tracing.py:59`                         | enables OTel export (no-op when unset) |
| `OTEL_SERVICE_NAME`                  | optional  | `apps/api/app/tracing.py:64`                         | default `quorum` |
| `QUORUM_ALLOW_DEMO`                  | **no in prod** | `apps/api/app/services/auth.py:245`            | only `1` in staging; exposes the seeded-incident route |

Hard rules:

- Secrets are **never** committed to `fly.toml`. `fly.toml` contains
  only non-secret config (region, volume name, service ports, check
  paths). `fly secrets list` is the authority for what's set.
- No secret appears in a health-check endpoint response or a log line
  (existing scrubbing rules in `apps/api/app/services/health_checks.py`
  and the structlog processors stand — no change).
- `QUORUM_ALLOW_DEMO` is **explicitly unset** in prod. Staging may set
  it for operator-facing demos; the config surface on staging is
  otherwise identical to prod so the demo seeder's bearer-token path
  gets real exercise.

## Health check and readiness wiring

The app already exposes two liveness paths today, both trivial:

- `GET /health` → `{"ok": true}` at `apps/api/app/main.py:174-177`
- `GET /api/v1/health` → `{"ok": true}` at `apps/api/app/routes.py:72-74`

The Dockerfile's `HEALTHCHECK` (line 55-56) hits `/api/v1/health`. Fly's
`http_check` will hit the same path, so operator-side and Fly-side agree.

**There is no readiness endpoint today.** For Fly to gate traffic during
boot (the hash-chain verification on a fresh machine against a restored
volume can take meaningful wall-clock time on a large log), we need one.

Decision in this doc, implementation in PR #51:

- Add `GET /readiness` that returns `200 {"ok": true}` **only when**:
  - `EventLog.verify_chain()` has completed (boot-time invariant, already
    enforced — we just expose the result).
  - If `DATABASE_URL` is set, the projector has established a DB
    connection at least once (a cheap `SELECT 1`).
- Return `503` with a `{"detail": ...}` body while either precondition
  is pending. Do not leak subsystem internals in the body.
- Fly `http_check` for readiness hits `/readiness`; liveness stays on
  `/api/v1/health`.

Scope is deliberately narrow — we do **not** include the Anthropic
health check here, because the API process isn't the one calling
Anthropic. Open question #6 revisits this if we co-locate the LLM agent.

## Dog-food deploy flow

The Phase 5 final PR wires production deploys of Quorum **through Quorum
itself**. Flow:

1. CI builds a Docker image on every merge to `main`, tags it with the
   commit SHA, and pushes the same manifest to
   `registry.fly.io/quorum-staging` and `registry.fly.io/quorum-prod`.
   The workflow records both content-addressed digests in the job
   summary so staging and prod deploy proposals can cite separate
   registry evidence. (This is the only new GitHub Actions workflow
   landing in Phase 5 — call it `.github/workflows/image-push.yml`.)
2. A new LLM role — `deploy-agent` — subscribes to the event stream,
   watches for successful image pushes (either via the CI workflow
   emitting an event on completion or by scanning the registry), and
   creates an intent + proposal with `action_type=fly.deploy` and a
   payload carrying the image digest.
3. `code-agent` (and any other voters) vote via the existing quorum
   engine. Policy rule `fly.deploy` requires **2 votes + explicit human
   approval** via the Phase 4 human-approval entity (PR #47). This is a
   high-risk action — rules stricter than `github.open_pr`.
4. The operator reviews in the console (PR #48's SSE UI), inspects the
   image digest + the proposal's rationale, and grants approval.
5. Executor dispatches the `fly.deploy` action. The actuator calls
   `fly deploy --image registry.fly.io/quorum-prod@sha256:<digest>`
   through the pinned `/usr/local/bin/fly` binary installed in the
   runtime image and verified under the non-root `quorum` user (see
   open question #2 on `flyctl`-binary vs Fly Machines API).

Live operator-run actuator deploy/rollback has been proven against
`quorum-staging` with `FlyClient` and the pinned `flyctl`. Fully
self-referential execution from inside the one-machine target app is
blocked at runtime when Fly exposes `FLY_APP_NAME` equal to the target
app. Replacing the same volume-attached machine that is handling the
execution request may terminate the worker before it appends terminal
`execution_succeeded` / `health_check_completed` events. Until an
external executor exists, the supported dog-food shape is a peer
controller deployment: for example, `quorum-staging` may execute an
approved `fly.deploy` targeting `quorum-prod`, but `quorum-staging` may
not deploy `quorum-staging` from inside its own API process.

Live peer-controller evidence: `quorum-staging` executed an API-gated
`fly.deploy` targeting `quorum-prod` after two votes and explicit human
approval. The execution captured the previous prod digest, deployed the
new main image digest, wrote terminal `execution_succeeded` plus two
`health_check_completed` events to staging's event log, and verified
prod `/readiness` + `/api/v1/health` returned HTTP 200.

**Event shape (for review, not implementation):**

```python
# apps/api/app/services/actuators/fly/specs.py (PR #52)
class FlyDeploySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: Literal["quorum-staging", "quorum-prod"]  # no arbitrary apps
    image_digest: str  # full digest, no tags — content-addressed
    strategy: Literal["rolling", "bluegreen", "immediate"] = "rolling"
```

**Rollback for `fly.deploy`:** `fly releases --app ... --json` →
`fly deploy --image <previous-digest>`. The pinned `flyctl` v0.4.39
does not support a `--limit` flag on `fly releases`, so Quorum limits
the parsed JSON list in-process. Deterministic when the previous digest
is captured at forward-deploy time. If the previous digest is
unavailable (first deploy or release introspection failed), the
executor emits `rollback_impossible` so the operator reconciles
manually instead of seeing a false rollback success.

**Safety rails** (hard-coded, not policy-configurable):

- `app` is a literal enum, not a free-form string. Quorum can never
  deploy into an app it doesn't own.
- `image_digest` must be a sha256 digest (64 hex after `sha256:`);
  tags like `latest` are rejected at the pydantic boundary. Content-
  addressing is the whole point.
- The actuator refuses same-app deploys when `FLY_APP_NAME` matches
  `FlyDeploySpec.app`; this is a runtime invariant, not a policy knob.
- Dog-food deploys of `quorum-prod` require `requires_human=true` in
  policy. Non-negotiable.

## Rollout plan (3 PRs)

**PR #50 — this doc.** Single file: `docs/design/fly-deployment.md`.
No runtime change. Only review signals: does the topology make sense,
are the open questions well-framed, is the dog-food flow congruent with
the existing event + policy model.

**PR #51 — `fly.toml` + `/readiness` + Dockerfile tuning** (~200 LOC plus
config).

- `fly.toml` at repo root: app name, region pin, volume mount, http
  service on :8080, `http_check` against `/readiness` and
  `/api/v1/health`. One file; parametrized by `--app` at deploy time.
- New endpoint: `GET /readiness` per §Health check. Unit tests +
  a small integration test that forces it to 503 when the projector
  isn't ready.
- Dockerfile: pin base image digest (`python:3.12-slim@sha256:...`),
  pin the `uv` bootstrap, install a checksummed `flyctl` binary, and
  copy only `/usr/local/bin/fly` into the runtime image.
- No deploy step yet — the PR just has to build green in CI and merge
  cleanly. Manual `fly deploy` by the operator is how we verify it.

**PR #52 — `deploy-agent` + `fly.deploy` actuator** (~800 LOC).

- New actuator: `apps/api/app/services/actuators/fly/` with `specs.py`,
  `client.py` (either `flyctl` subprocess or Fly Machines API client;
  see open question #2), `actions.py`.
- Executor dispatch wiring in `apps/api/app/services/executor.py`:
  add `"fly.deploy"` to `_ACTION_DISPATCH` and `_ROLLBACK_DISPATCH`.
- New event type `deploy_intent_created` via the `create-event-type`
  skill: reducer handler, projector handler, docs touch-ups, test,
  example. (SESSION_HANDOFF gotcha #8 — must land in the same commit
  as the event type.)
- Policy rule in `config/policies.yaml` for `action_type=fly.deploy`:
  `votes_required: 2`, `requires_human: true`.
- New LLM role: `deploy-agent`, scoped `allowed_action_types:
  ["fly.deploy"]` via the Phase 4 gate.
- CI: the image-push workflow (GitHub Actions) builds + pushes
  `quorum-staging:<sha>` and `quorum-prod:<sha>` on every `main` merge.
- Integration tests against `quorum-staging` (operator-provisioned),
  gated behind `QUORUM_FLY_LIVE_TESTS=1`. Default CI skips them.

Each PR passes the 5 required checks (`lint + format + test`,
`gitleaks`, `pip-audit`, `docker build`, `mypy`) and ends with an
explicit operator pause for merge.

## Operator pre-reqs (explicit — before PR #51)

The operator (user) currently has no Fly account. These steps happen
**once**, between PR #50 merging and PR #51 starting. Nothing in this
design-doc PR requires the operator to do anything.

1. `curl -L https://fly.io/install.sh | sh` — install `flyctl`.
2. `fly auth signup` (or `fly auth login` if the account already
   exists).
3. `fly apps create quorum-staging` and `fly apps create quorum-prod`.
4. `fly volumes create quorum_data --size 1 --region iad --app
   quorum-staging`; repeat the same `quorum_data` volume name under
   `quorum-prod` because Fly volume names are app-scoped.
5. Create a Neon project; take a staging branch of the prod DB. Copy
   both connection strings.
6. `fly secrets set QUORUM_API_KEYS=... QUORUM_GITHUB_APP_PRIVATE_KEY=...
   DATABASE_URL=... --app quorum-{staging,prod}`. Use the bootstrap CLI
   (`python -m apps.api.app.tools.bootstrap_keys generate`) to mint
   API keys.
7. (Optional) `fly certs add api.<domain>` per app. `*.fly.dev` is
   fine for v1.
8. After the first prod deploy, opt prod out of scale-to-zero:
   `fly machine update <machine-id> --app quorum-prod --autostop=off --autostart --yes`.
   Use `--autostop=off`; pinned `flyctl` parses `--autostop off` as an
   extra positional argument.

## Open questions (for review)

1. **Region.** `iad` (Ashburn) covers Anthropic + GitHub + Neon-us-east
   at low-ms. `ord` or `sea` are defensible for developer-latency
   reasons. Lean: `iad`.
2. **`flyctl` binary vs Fly Machines API.** ~~Lean: Machines API.~~
   **Decided in PR #52 (actuator implementation): `flyctl` subprocess.**
   Implementing the deploy flow against Fly's API required both
   GraphQL (releases) and REST (machines), doubling surface area over
   the original ~200-line estimate. Shelling out to `fly deploy`
   stayed bounded (~80 LOC client + ~90 LOC actions) and is trivially
   stubbable in tests via `monkeypatch.setattr(subprocess, "run", ...)`
   — same pattern as `respx` for the GitHub client. The runtime image
   now carries a pinned, checksummed `flyctl` binary as
   `/usr/local/bin/fly`, with a writable home for the non-root
   `quorum` user; we can flip to the API later without changing spec
   or event shape.
3. **Scale-to-zero vs always-on.** Staging → scale-to-zero (cold-start
   on first request is fine). Prod → **always-on** because the
   operator console holds long-lived SSE connections
   (`GET /api/v1/events/stream`, PR #48); Fly terminates idle machines
   and drops in-flight connections. Flag: if scale-to-zero is
   attempted in prod, SSE breaks silently from the operator's
   perspective. The verified prod command is
   `fly machine update <machine-id> --app quorum-prod --autostop=off --autostart --yes`.
4. **Custom domain + TLS.** `*.fly.dev` ships with free ACME certs.
   Custom domain adds `fly certs add` + DNS toil; not required for
   v1. Defer.
5. **Managed Postgres host.** Neon (recommended) vs Fly Postgres — see
   §Managed Postgres. Needs operator sign-off, not reviewer sign-off.
6. **Readiness endpoint scope.** Is `EventLog.verify_chain() completed
   + DB reachable` the full definition? Should we also gate on the
   Anthropic-key health check from
   `apps/api/app/services/health_checks.py`? Lean: no — the API
   process doesn't talk to Anthropic; the LLM agent process does.
7. **Log shipping.** Fly ships stdout to its own log store by default;
   our structlog JSON is already compatible. Options: (a) Fly-native
   only, (b) forward via `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTel
   collector, (c) a Vector tail to Axiom / Logflare. Lean: (a) for
   v1; add (b) when a collector is provisioned.
8. **`fly.deploy` actuator image source.** Build in CI and push to
   Fly Registry (recommended), or build in a separate Fly Machine
   on the fly? Lean: CI-built, Fly Registry — keeps build and deploy
   concerns separate.

## Dependencies landing this brings

Nothing in this PR (docs only). Implemented outcome for the later PRs:

- PR #51 introduced no new Python dependencies. `fly.toml` + a new
  FastAPI route + Dockerfile tuning.
- PR #52 adds at most the Fly Machines API client path — depending on
  open question #2, either a single `httpx`-based module (no new
  dependency; `httpx` already pinned) or the `flyctl` binary in the
  runtime layer (no Python dep; adds to image size). The implementation
  chose the `flyctl` binary and pins its release tarball checksum in
  the Dockerfile.

## Success criteria

A reviewer reading this doc top-to-bottom can answer:

- How many Fly apps run, and why one machine per app.
- Where the canonical event log lives and what happens when the volume
  is lost.
- Which managed Postgres we use and whether it's reversible.
- Which env vars Fly injects and which ones are secret vs non-secret.
- What the readiness endpoint guarantees on top of the existing
  liveness endpoint.
- How a production deploy of Quorum flows through the Quorum API
  itself, including the policy rule and rollback strategy.
- Why the runtime image contains a pinned `flyctl` binary.
- What operator actions gate which PR.
- Which decisions are locked (Neon-recommended, `iad` lean,
  single-machine per app, dog-food via `fly.deploy`) vs still open.

If any of those can't be answered from this doc alone, it's a bug in
the doc — file a correction on the PR or open an issue.
