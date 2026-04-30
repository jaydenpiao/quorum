# Session handoff

This document is the canonical "where we left off" note for AI coding agents
picking up Quorum across sessions. Read it before anything except `AGENTS.md`.

Updated after every substantial session; treat entries below as the
authoritative state of the project.

---

## Current state (as of the handoff)

- **Last tagged release:** [`v0.6.2`](https://github.com/jaydenpiao/quorum/releases/tag/v0.6.2) — trust-monitor and
  voter design-gate release. Package/runtime version is `0.6.2`;
  public display/tag version is `v0.6.2`. It packages the read-only
  live release monitor, the durable `v0.6.1` proof archive, and the
  design-only LLM voter safety gate. Release workflow run
  [`25138132052`](https://github.com/jaydenpiao/quorum/actions/runs/25138132052)
  succeeded on the signed tag and published SBOM asset
  [`quorum-v0.6.2.spdx.json`](https://github.com/jaydenpiao/quorum/releases/download/v0.6.2/quorum-v0.6.2.spdx.json).
  The signed tag object is
  `46d6db147c65eebfe45c17d6f6152f873911bc6f` and points at merge
  commit `36b786ef8e0d8b5f7e87b83e78821eb132c962ac`.
- **Current deployed release proof:** staging and prod both report
  `display_version=v0.6.2`. The live proof captured
  `/tmp/quorum-proof.20260429T230015Z/proof.json`, selected
  `proposal_55eed6fa8e13` / `exec_22293b78a7d9`, verified prod
  `/readiness` and `/api/v1/health` with `ok=true`, and verified the
  staging event chain with `event_count=164` and last hash
  `695f3e103cee7d102a21410e5e179f18d2068377924ba9e7c9e11d758ac33a5a`.
  The durable release/deploy evidence archive is
  `docs/releases/v0.6.2-proof.md`; the previous `v0.6.1` proof
  remains archived at `docs/releases/v0.6.1-proof.md`.
- **v0.6 release content:** PR #105 packaged the post-Phase-5
  alpha-polish and proof work: managed local/CI/release `uv`
  bootstrap, canonical runtime/package versioning, full operator
  console review-to-execute controls, the active GitHub fixture demo,
  the LLM-authored prod deploy proof helper, and the pinned gitleaks
  CLI security check.
- **Test suite:** 463 passing + 13 integration-gated (excluded from CI
  by default; opt-in with `pytest -m integration` against a live
  Postgres, Fly.io, or GitHub, with additional env gates for destructive
  tests).
- **Coverage:** 81.43% (gate floor: 60%).
- **Type check:** `mypy --strict` clean across 50 source files.
- **Required CI checks on `main`:** `lint + format + test`, `gitleaks`, `pip-audit`, `docker build`, `mypy`. All 5 pass on every PR in the series. The `gitleaks` check installs checksum-verified `gitleaks 8.30.1` directly instead of using the deprecated Node 20-backed `gitleaks/gitleaks-action`.
- **pip-audit note:** CI temporarily ignores `CVE-2026-3219` because
  it affects the latest published PyPI `pip` (`26.0.1`) and pip-audit
  reports no fixed version. Keep `pip-audit --strict`; remove the
  single ignore in `.github/workflows/ci.yml` once pip publishes a fix.
  The audit syncs with `--no-install-project`, runs with `--no-sync`,
  and restricts `pip-audit` to the venv `site-packages` path so the
  first-party `quorum` package is not audited as an unpublished PyPI
  dependency.
- **Branch protection:** required PR, linear history, force-push disabled, conversation resolution required.
- **Merged PR count after this LLM vote policy PR merges:** 119. Phase 5 added #50 design doc, #54 fly.toml + /readiness (replaced auto-closed #51), #52 fly.deploy actuator, #53 mid-phase handoff, #55 deploy-llm-agent, #56 image-push CI, #57 CHANGELOG + v0.5.0-alpha.1 handoff, #58 release-workflow fix, #59 `make clean-worktrees`, #61 runtime `flyctl` hardening, #62 image-push staging/prod follow-up, #63 pinned-flyctl release-list compatibility, #64 staging bootstrap handoff/docs, #65 opt-in live Fly deploy/rollback integration coverage, #66 same-app Fly deploy guard, #67 peer-controller deploy evidence, #68 Fly release digest wording, #69 Neon URL normalization, #70 Neon Fly bootstrap evidence, #71 GitHub App bootstrap helper, #72 live GitHub actuator Fly proof, #73 image-push evidence events, #74 image-push evidence proof handoff, #75 LLM proposal dispatch envelope fix, #76 deploy-agent health-check prompt contract, #77 health-checked deploy-agent proof handoff, #78 API/executor health-check gate for `fly.deploy`, #79 LLM prompt hash audit metadata, #80 opt-in live GitHub actuator rollback coverage, #81 LLM adapter Prometheus metrics, #82 deploy-agent same-control-plane proposal guard, #83 handoff refresh for the live guard proof, #84 docs-only image-push skip, #85 final handoff refresh, #93 alpha operator polish, #94 live deploy guard proof hardening, #95 external staging verification proof mode, #96 Fly platform digest proof correction, #97 live prod proof handoff, #98 Fly runtime state refresh, #99 GitHub Actions Node 24-ready pin refresh, #100 dependency lower-bound + lock sync, #101 maintenance state refresh, #102 pinned `uv` toolchain, #103 uv toolchain handoff refresh, #104 pinned gitleaks CLI, #105 v0.6.0-alpha.1 release prep, #107 console execution-actionability hardening, #108 audit proof capture/read models, #109 image-push evidence retry hardening, #110 v0.6.1 hardening handoff refresh, #111 v0.6.1 release prep, #112 v0.6.1 release-proof handoff, #113 live release monitor, #114 v0.6.1 proof archive, #115 LLM voter design gate, #116 v0.6.2 release prep, #117 v0.6.2 proof archive, #118 agent capability gates, and #119 LLM vote policy caps.
- **Current operator alpha-polish state:** local bootstrap and
  validation now run on the same locked `uv`-managed Python path CI
  uses. `make install` recreates `.venv` on managed CPython 3.12 and
  runs `scripts/check_python_runtime.py`, which fails fast on broken
  `readline` imports instead of letting `pytest` segfault during
  startup. The `uv` resolver itself is pinned at `0.11.8` across
  `pyproject.toml`, `Makefile`, GitHub Actions, the release workflow,
  Docker, and operator scripts.
- **Post-#105 verification state:** the release-prep branch passed
  local `make validate`, `make typecheck`, targeted
  `tests/test_version_contract.py` + `tests/test_bootstrap_contract.py`,
  `git diff --check`, and `uv lock --check`. PR #105 then passed all
  required checks (`lint + format + test`, `gitleaks`, `pip-audit`,
  `docker build`, `mypy`) before squash-merge to `main`. Post-merge
  `main` CI/security passed, and the signed v0.6 tag release workflow
  succeeded with the SBOM asset attached.
- **Canonical version contract:** `apps/api/app/version.py` is now the
  single version source. Package metadata, FastAPI/OpenAPI metadata,
  tracing `service.version`, the unauthenticated root metadata
  response, and the console release badge all resolve from that module.
- **Current agent capability state:** `config/agents.yaml`
  `can_propose` and `can_vote` flags are enforced before mutation.
  Explicit `can_propose=false` blocks `POST /api/v1/proposals` before
  `proposal_created`; explicit `can_vote=false` blocks
  `POST /api/v1/votes` before `proposal_voted`. Missing YAML entries
  or missing capability fields remain permissive for env-only dev/test
  agents. `telemetry-llm-agent` and `deploy-llm-agent` remain
  proposer-only with `can_vote: false`.
- **Current LLM voter implementation state:** the API accepts
  structured LLM vote metadata only from agents configured with an
  `llm:` block, rejects missing LLM metadata and non-LLM spoofed
  metadata before event-log mutation, rejects LLM self-votes, and
  enforces `allowed_vote_action_types` before appending
  `proposal_voted`. The server sets `voter_kind`, `counted`, and
  `counted_reason`; `config/policies.yaml` defaults LLM votes to zero
  counted votes and permits at most one counted LLM vote for
  `github.add_labels` and `github.comment_issue`. Protected
  environments and high/critical risk proposals record eligible LLM
  votes as `counted=false`. Adapter-side `cast_vote`, a
  `review-llm-agent` prompt/config, and console LLM vote rendering are
  still follow-up PRs; no `fly.deploy` LLM voting exists.
- **Current console/demo state:** `/console` now renders first-class
  intent and finding panels, rollback state beside execution and health
  state, an operator **Execute proposal** action, and a **Verify event
  chain** control backed by `GET /api/v1/events/verify`. The execute
  action is disabled unless the selected proposal is currently
  executable: status `approved`, policy allowed, quorum met, required
  human approval granted, and not a same-control-plane `fly.deploy`.
  The overview separates actionable proposals from stale historical
  pending proposals so old audit rows do not look like broken work.
  Cold browser verification during v0.6.1 release-prep on
  `http://127.0.0.1:8081/console#proposals` showed
  `releaseBadge=v0.6.1`, `chainStatus=verified`, actionable proposal
  metrics, and no browser console errors. Post-release browser
  acceptance for `v0.6.2` on
  `https://quorum-staging.fly.dev/console#proposals` showed
  `releaseBadge=v0.6.2`, `chainStatus=verified`,
  `eventCount=164 events`, `health=17/17`, and visible latest proposal
  `proposal_55eed6fa8e13` with deploy-LLM prod-deploy metadata,
  terminal execution, votes, and no browser console errors.
- **Active GitHub fixture demo proof:** the paused helper
  `scripts/demo_github_fixture_flow.sh` was live-validated against
  `jaydenpiao/quorum-actuator-fixtures#1` and created fixture comment
  `https://github.com/jaydenpiao/quorum-actuator-fixtures/issues/1#issuecomment-4331852408`
  during the primary validation pass. A later browser-side smoke also
  created
  `https://github.com/jaydenpiao/quorum-actuator-fixtures/issues/1#issuecomment-4331892943`
  before the local event log was restored to the pre-check snapshot.
- **LLM-authored prod deploy proof workflow:** the operator proof path
  is now scripted as `scripts/prove_llm_prod_deploy.sh` and documented
  in `docs/DEMO_VIDEO.md`. It captures a scratch staging cursor, waits
  for fresh `image_push_completed` plus matching staging-success
  evidence, runs `deploy-llm-agent --once`, verifies that the proposal
  targets `quorum-prod` with the exact `prod_digest` and prod health
  checks, then stops before mutation unless `QUORUM_PROOF_EXECUTE=1`
  is set. It also has `QUORUM_PROOF_EXPECT_GUARD=1` for the safe
  negative proof when staging success evidence is missing, and
  `QUORUM_PROOF_STAGING_EVIDENCE=external-staging-finding` for the
  interim live path where the operator verifies the current
  `quorum-staging` release digest + health endpoints and records an
  `external_staging_verification` finding instead of fabricating an
  execution event. The finding records both the image-push
  manifest-list `staging_digest` and Fly's platform digest because
  those can differ for the same deployed image.
- **Post-merge live guard proof:** after PR #93 merged as `73f9f93`,
  image-push run `25035587753` posted `evt_3ffcf5655d77` /
  `imgpush_23bc8714edfa` with prod digest
  `sha256:8651424e5bbb1bf42cf0092d6caed1ab4c39713f9dde1f8d004877428865224c`.
  There was no matching `quorum-staging` `execution_succeeded` event
  for that digest, so a real Anthropic-backed `deploy-llm-agent` tick
  against staging created guard finding `finding_1d560add1716`
  (`evt_2c6b1f43d8a4`) under intent `intent_53b9ca91552b` and did not
  create a prod deploy proposal. The scripted guard mode
  `QUORUM_PROOF_EXPECT_GUARD=1 scripts/prove_llm_prod_deploy.sh` was
  then verified end-to-end and created guard finding
  `finding_82190024cee2` (`evt_eb31bf35b374`) under intent
  `intent_1345488b143b`. Staging `/api/v1/events/verify` returned
  `event_count=92` and
  `last_hash=af732287553e19975cbe226f3e92ed8c79ba0bfb082ec7d3afa30aeea4321b4a`.
- **Previous live LLM-authored prod deploy proof:** after PR #105 merged
  as `2835ce9`, manual image-push run
  [`25079047944`](https://github.com/jaydenpiao/quorum/actions/runs/25079047944)
  posted fresh evidence `evt_a13b62ae2d43` /
  `imgpush_d656e57344f0` for commit
  `2835ce91935a9fed7f11943ff8c70613e391261c` with staging/prod
  manifest digest
  `sha256:459c63cdbc432c2a9e4446e95ff9dcf932127ce2a06f7fec474b3b6a69ebebcf`.
  The proof script captured scratch cursor `evt_893df33ebcdb`, created
  intent `intent_fbd1e29f89fd`, deployed `quorum-staging` from that
  manifest digest via external `flyctl`, recorded Fly platform digest
  `sha256:3368f8888d951073f3278fe0e02e906d74443d11bb3cc27c6e22bb9b5b2dbade`,
  and appended external verification finding `finding_79a85e72a127`
  (`evt_f2e9964e1068`). A real Anthropic-backed
  `deploy-llm-agent` tick then authored prod `fly.deploy` proposal
  `proposal_ee73bc8461df` as agent `deploy-llm-agent`, citing the
  image-push and external staging evidence. The script cast
  code-agent vote `vote_535f29867908`, deploy-agent vote
  `vote_c7d64f5c7a36`, requested/granted human approval
  `approval_req_ff49e76b6edf` / `approval_out_90174fcc41f9`, and
  executed through the staging Quorum API. Execution
  `exec_abdb202f045e` succeeded after `prod-readiness`
  (`hcr_e769ca25660d`) and `prod-api-health`
  (`hcr_03d79037b2fe`) passed. Final staging/prod `/` report
  `display_version=v0.6.0-alpha.1`; prod `/readiness` and
  `/api/v1/health` returned `{"ok": true}`; staging
  `/api/v1/events/verify` returned `event_count=128` and
  `last_hash=300f36e6c60b012e90fa51fa45683e42271a9796e76d04d53b4dad3e02411e81`.
- **Latest live LLM-authored prod deploy proof:** after PR #111 merged
  as `654af76`, `main` `ci`, `security`, and automatic `image-push`
  runs
  [`25089289023`](https://github.com/jaydenpiao/quorum/actions/runs/25089289023),
  [`25089289024`](https://github.com/jaydenpiao/quorum/actions/runs/25089289024),
  and
  [`25089289028`](https://github.com/jaydenpiao/quorum/actions/runs/25089289028)
  succeeded. Signed tag `v0.6.1` (`9cd149917e8a149112409ac60ca8c150135483ef`)
  points at that merge commit; release workflow
  [`25089353063`](https://github.com/jaydenpiao/quorum/actions/runs/25089353063)
  published
  [`quorum-v0.6.1.spdx.json`](https://github.com/jaydenpiao/quorum/releases/download/v0.6.1/quorum-v0.6.1.spdx.json).
  Manual image-push run
  [`25089406553`](https://github.com/jaydenpiao/quorum/actions/runs/25089406553)
  posted fresh evidence `evt_05d8cc15050d` /
  `imgpush_5fe1b504f8e0` with staging/prod manifest digest
  `sha256:07042758006860cf0fdd17be327a687b23e0334942fe50b33f400cc48bcdc299`.
  The proof script captured scratch cursor `evt_9e6941a32df2`, created
  intent `intent_6a9b57f0becc`, deployed `quorum-staging` from that
  manifest digest via external `flyctl`, recorded Fly platform digest
  `sha256:c68b56c9ff7f85f0a27251cff363d6cf30d78fd00ebccd63baee15cebb6a277c`,
  and appended external verification finding `finding_4c98b91b9211`
  (`evt_32e2e1cd8254`). A real Anthropic-backed
  `deploy-llm-agent` tick authored prod `fly.deploy` proposal
  `proposal_28f6c2af1fd1` (`evt_ef49964b67cb`) as agent
  `deploy-llm-agent`, with policy `allowed=true`,
  `requires_human=true`, and `votes_required=2`. The script cast
  code-agent vote `vote_333dd5c99959`, deploy-agent vote
  `vote_ceaa27630cae`, requested/granted human approval
  `approval_req_862411a645b9` / `approval_out_2370eccd55e1`, and
  executed through the staging Quorum API. Execution
  `exec_5911a5fe499c` succeeded after `prod-readiness`
  (`hcr_307401d5767f`) and `prod-api-health`
  (`hcr_f43a57519e22`) passed. Final staging/prod `/` report
  `display_version=v0.6.1`; prod `/readiness` and
  `/api/v1/health` returned `{"ok": true}`; staging
  `/api/v1/events/verify` returned `event_count=146` and
  `last_hash=3bc246b36e4fea73b8746a27f9d2d1865e7f77da5b9e3a5194b693db84ca5e29`.
- **v0.6.2 live LLM-authored prod deploy proof:** after PR #116
  merged as `36b786e`, `main` `ci`, `security`, and `image-push` runs
  [`25138088380`](https://github.com/jaydenpiao/quorum/actions/runs/25138088380),
  [`25138088386`](https://github.com/jaydenpiao/quorum/actions/runs/25138088386),
  and
  [`25138088365`](https://github.com/jaydenpiao/quorum/actions/runs/25138088365)
  succeeded. Signed tag `v0.6.2`
  (`46d6db147c65eebfe45c17d6f6152f873911bc6f`) points at that merge
  commit; release workflow
  [`25138132052`](https://github.com/jaydenpiao/quorum/actions/runs/25138132052)
  published
  [`quorum-v0.6.2.spdx.json`](https://github.com/jaydenpiao/quorum/releases/download/v0.6.2/quorum-v0.6.2.spdx.json).
  Manual image-push run
  [`25138184450`](https://github.com/jaydenpiao/quorum/actions/runs/25138184450)
  posted fresh evidence `evt_c5e2a3a30cb1` /
  `imgpush_d20804ead766` with staging/prod manifest digest
  `sha256:2ffcf11f6929cfde9d6277fb55730c4f9834fff9f57a684cec95d2024ae5bcb3`.
  The proof script captured scratch cursor `evt_a602af55e5bc`,
  created intent `intent_30ac8c75efdc`, deployed `quorum-staging`
  from that manifest digest via external `flyctl`, recorded Fly
  platform digest
  `sha256:936014e57b2d8621115ec18f83959ab7a97c0807f030b2bba429fc3c69f50ecf`,
  and appended external verification finding `finding_fe450cf97e02`
  (`evt_ff43da5a1110`). A real Anthropic-backed
  `deploy-llm-agent` tick authored prod `fly.deploy` proposal
  `proposal_55eed6fa8e13` (`evt_b880dabb82a5`) as agent
  `deploy-llm-agent`, with policy `allowed=true`,
  `requires_human=true`, and `votes_required=2`. The script cast
  code-agent vote `vote_4f169f48aa87`, deploy-agent vote
  `vote_8f87ae958a22`, requested/granted human approval
  `approval_req_7f7b867f32ae` / `approval_out_4e78203986e3`, and
  executed through the staging Quorum API. Execution
  `exec_22293b78a7d9` succeeded after `prod-readiness`
  (`hcr_44c44649cafa`) and `prod-api-health`
  (`hcr_c39b211c47e3`) passed. Final staging/prod `/` report
  `display_version=v0.6.2`; prod `/readiness` and
  `/api/v1/health` returned `{"ok": true}`; staging
  `/api/v1/events/verify` returned `event_count=164` and
  `last_hash=695f3e103cee7d102a21410e5e179f18d2068377924ba9e7c9e11d758ac33a5a`.
  `QUORUM_RELEASE_TAG=v0.6.2 scripts/capture_operator_proof.sh`
  wrote `/tmp/quorum-proof.20260429T230015Z/proof.json` and
  `/tmp/quorum-proof.20260429T230015Z/proof.md`, and
  `QUORUM_RELEASE_TAG=v0.6.2 scripts/check_live_release.sh` passed.
- **v0.6.1 audit-proof hardening:** history read models now
  expose existing projected policy decisions, human approvals,
  health-check results, rollbacks, and image-push evidence under
  `/api/v1/history/*` without adding mutation routes or new projection
  tables. `scripts/capture_operator_proof.sh` is the repeatable
  read-only proof-capture helper: it records staging/prod root
  metadata, event-chain verification, prod readiness/health, and the
  terminal `deploy-llm-agent` `fly.deploy` proposal targeting
  `quorum-prod` into `proof.json` and `proof.md`, failing closed on
  version drift, failed event-chain verification, failed prod health,
  or non-matching proposal/execution state. A read-only smoke on
  2026-04-28 with `QUORUM_RELEASE_TAG=v0.6.0-alpha.1` wrote
  `/tmp/quorum-proof.20260428T221242Z/proof.json` and selected
  `proposal_ee73bc8461df` / `exec_abdb202f045e` with staging
  `event_count=129`, last hash
  `f49d6ee5ac965cd4910460e9912293fb1d4664bf1e1041dd01a955a798d9d419`,
  and prod readiness/health `ok=true`.
- **v0.6.1 image-push evidence reliability:** the optional
  Quorum evidence notifier in `.github/workflows/image-push.yml` now
  retries failed `POST /api/v1/image-pushes` calls with bounded
  exponential backoff, still exits successfully on final failure, and
  writes posted/failed status plus returned Quorum evidence IDs into
  `$GITHUB_STEP_SUMMARY`. Docs-only pushes remain ignored and manual
  `workflow_dispatch` remains supported. Post-merge `main` `ci`,
  `security`, and `image-push` runs for commit `417a181` succeeded;
  image-push run
  [`25080763404`](https://github.com/jaydenpiao/quorum/actions/runs/25080763404)
  executed the hardened notifier and posted
  `evt_35aac062178b` / `imgpush_1b9993098e1f`.
  `QUORUM_RELEASE_TAG=v0.6.0-alpha.1 scripts/capture_operator_proof.sh`
  then wrote `/tmp/quorum-proof.20260428T222519Z/proof.json` with
  staging `event_count=131`, last hash
  `a52518723039520f2dc7608523a048f2dcd144a232f9cc3d89719d4dd9d13c50`,
  selected `proposal_ee73bc8461df` / `exec_abdb202f045e`, and prod
  readiness/health `ok=true`. After the `v0.6.1` live deploy proof,
  `QUORUM_RELEASE_TAG=v0.6.1 scripts/capture_operator_proof.sh` wrote
  `/tmp/quorum-proof.20260429T033023Z/proof.json` and
  `/tmp/quorum-proof.20260429T033023Z/proof.md`, selecting
  `proposal_28f6c2af1fd1` / `exec_5911a5fe499c` with staging
  `event_count=146`, last hash
  `3bc246b36e4fea73b8746a27f9d2d1865e7f77da5b9e3a5194b693db84ca5e29`,
  both staging/prod `display_version=v0.6.1`, and prod
  readiness/health `ok=true`.
- **Docs/onboarding drift:** `README.md`, `docs/DEMO_VIDEO.md`,
  `docs/REPO_MAP.md`, and `.env.example` now match the shipped auth,
  demo-gate, managed-`uv`, and console contracts.
- **Post-proof maintenance state:** PR #99 refreshed GitHub Actions
  pins after CI warned that Node.js 20-based actions would be forced to
  Node.js 24 on June 2, 2026. PR #100 consolidated the five open
  Dependabot lower-bound PRs into one `pyproject.toml` + `uv.lock`
  dependency-graph sync; Dependabot auto-closed the superseded PRs
  #88-#92. Main `ci`, `security`, and `image-push` are green after both
  merges.
- **Fly operational state:** `FLY_API_TOKEN` is configured as a GitHub
  Actions repo secret; `quorum-staging` and `quorum-prod` exist with
  app-scoped 1 GiB `iad` volumes named `quorum_data` (staging:
  `vol_4qly1wq329gwx56r`, prod: `vol_v8emwyn2gj70k11v`). The initial
  app-specific volumes were unattached and destroyed to avoid drift
  from `fly.toml`. Image-push CI now has an optional best-effort
  `POST /api/v1/image-pushes` notifier controlled by repo secrets
  `QUORUM_IMAGE_PUSH_API_URL` and `QUORUM_IMAGE_PUSH_API_KEY`; those
  secrets point at `https://quorum-staging.fly.dev` and the staging
  `deploy-agent` API key. PR #84 adds `paths-ignore` so future
  Markdown/docs-only pushes do not build images or post
  `image_push_completed` evidence; mixed code+docs pushes and manual
  `workflow_dispatch` still build.
- **Neon operational state:** project `square-tree-95302760` in the
  `Jayden` org has prod branch `main` (`br-wild-dream-ajhrmye0`) and
  staging branch `quorum-staging` (`br-still-dust-aj7z7vra`), database
  `neondb`, role `neondb_owner`. Both branches are migrated to Alembic
  `0004 (head)`. Local operator Keychain service names:
  `quorum-neon-prod-database-url` and
  `quorum-neon-staging-database-url`.
- **GitHub actuator bootstrap state:** GitHub App `quorum-actuator`
  exists with non-secret App ID `3496381`; it is installed on fixture
  repo `jaydenpiao/quorum-actuator-fixtures` with installation ID
  `126887427`. The fixture repo has smoke issue #1 and label
  `quorum-smoke`. The generated PEM is stored base64-encoded in local
  Keychain service `quorum-github-app-private-key-b64`.
  `config/github.yaml` points at the fixture installation.
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` is deployed on both
  `quorum-staging` and `quorum-prod`. Both Fly apps have executed
  `github.comment_issue` against fixture issue #1 through Quorum's
  proposal/vote/execute path; keep the App installed only on the
  fixture repo until a separate PR moves the actuator to a production
  target. Opt-in live pytest coverage also proves the direct actuator
  helper creates a fixture comment, rolls it back, and observes the
  deleted comment as 404.
- **Staging deployment state:** `quorum-staging` is running Fly
  release v18, which reports platform image ref
  `registry.fly.io/quorum-staging@sha256:3368f8888d951073f3278fe0e02e906d74443d11bb3cc27c6e22bb9b5b2dbade`.
  That release was deployed during the v0.6 live LLM prod proof from
  image-push manifest-list digest
  `sha256:459c63cdbc432c2a9e4446e95ff9dcf932127ce2a06f7fec474b3b6a69ebebcf`.
  Machine `e2862467be9d78` is the single staging machine in `iad`;
  `autostop=true`, `autostart=true`, and `min_machines_running=0`
  are expected for staging. `/readiness`, `/api/v1/health`,
  `/metrics`, and `/console` returned HTTP 200 after wake.
  `QUORUM_API_KEYS` (operator, code-agent, deploy-agent,
  deploy-llm-agent), `FLY_API_TOKEN`, `DATABASE_URL`, and
  `QUORUM_ALLOW_DEMO=1` are deployed only on staging;
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` is deployed on staging. Local
  operator Keychain service names for the LLM proof are
  `quorum-staging-deploy-llm-agent-api-key` and
  `quorum-anthropic-api-key`.
- **Staging persistence evidence:** an authenticated
  `POST /api/v1/intents` created `intent_f40d2794ee55`; before and
  after `fly machine restart e2862467be9d78 --app quorum-staging`,
  `GET /api/v1/events/verify` returned `event_count=1` and
  `last_hash=3b8f54fef545d63b23069ed1daa5877ad9fbb951a78767d20682155c6dd8c7ff`.
  This verifies the Fly Volume is mounted at `/app/data`.
- **Staging Postgres projection evidence:** after enabling
  `DATABASE_URL`, `quorum-staging` reconciled 13 existing events from
  JSONL into Neon with zero errors, then accepted a live smoke intent
  `intent_ca2cf96dfc15`. Current staging event verification reports
  `event_count=131` and
  `last_hash=a52518723039520f2dc7608523a048f2dcd144a232f9cc3d89719d4dd9d13c50`.
  Reduced state counts are `intents=16`, `findings=5`,
  `proposals=10`, `votes=14`, `policy_decisions=10`,
  `executions=14`, `health_checks=13`, `human_approvals=15`, and
  `image_pushes=27`.
- **Latest image-push evidence after v0.6 release:** the automatic
  post-PR #109 image-push run
  [`25080763404`](https://github.com/jaydenpiao/quorum/actions/runs/25080763404)
  posted `evt_35aac062178b` / `imgpush_1b9993098e1f` for commit
  `417a1813d7d65ec7333070367d4ac7375477da73` with staging/prod digest
  `sha256:6d215f6710803ec8b0ba49ccf6e99e4925cf778c180297eb88065e9a970292d9`.
  The previous post-PR #108 image-push run
  [`25080540658`](https://github.com/jaydenpiao/quorum/actions/runs/25080540658)
  posted `evt_18ecd6c89cb4` / `imgpush_1b9e7213c74e` for commit
  `82dc7c7abed423ec11c9380d5ff6681089ea9741` with staging/prod digest
  `sha256:2fe29eef67cf2d6bcb89550e1dcfa2c8744428e78da9159dddc409c87431661e`.
  The previous post-PR #107 image-push run
  [`25080148345`](https://github.com/jaydenpiao/quorum/actions/runs/25080148345)
  posted `evt_6522032d9b26` / `imgpush_5026efc2bb6c` for commit
  `d84cec6c86f6681f503b6fb65e5f41803a233cb1` with staging/prod digest
  `sha256:37041195db24140d631ea5dbb3a31238287753c42917603fed815f47dd61232b`.
  The earlier post-v0.6 release automatic run `25078777374` went green
  only after rerun and was not the canonical proof input; the v0.6 live
  prod proof used manual `workflow_dispatch` run
  [`25079047944`](https://github.com/jaydenpiao/quorum/actions/runs/25079047944),
  which posted `evt_a13b62ae2d43` / `imgpush_d656e57344f0` for merge
  commit `2835ce91935a9fed7f11943ff8c70613e391261c`.
- **Image-push evidence proof:** workflow run
  `24925601409` posted `image_push_completed` into staging as
  `evt_fd0e051dca4b` / `imgpush_2e6a1c26fdd3`, reported by
  `deploy-agent`, for commit
  `4189cebdf556b116d4fb870e4442f7f6a82da503`. The payload carries
  `registry.fly.io/quorum-staging@sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`
  and
  `registry.fly.io/quorum-prod@sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`.
  Staging `/api/v1/events/verify` advanced from `event_count=47` to
  `event_count=48` with
  `last_hash=8efdf62df7635b0cacd20856c0c171fbfff9c4a64565e1829f41b4fe6988301b`
  immediately after the notifier.
- **Live `deploy-llm-agent` proposal proof:** workflow run
  `24925781387` later posted `image_push_completed` into staging as
  `evt_74ef7a99cb5d` / `imgpush_eadad713af0b` for commit
  `52c3802fbd18e38f0542f5176b468f7bf6950b72`, carrying staging/prod
  digest
  `sha256:3f3a144ec2145b6bc8be2b8cd7a4ca3e3c3742231c48e85832b5e95f60d76971`.
  The operator created intent `intent_8b92f439d2c0`, then ran the real
  Anthropic-backed adapter once as `deploy-llm-agent` against
  `https://quorum-staging.fly.dev`. The call completed against
  `claude-opus-4-7` and submitted `proposal_b07ba69ae657`
  (`fly.deploy` target `quorum-staging`) plus human-approval request
  `approval_req_4fc1b863ca1f`. No execution was claimed or attempted;
  same-app staging deploy remains blocked by invariant. The adapter
  initially logged the tool dispatch as `ok=False` because it expected
  a top-level `id`; PR #75 fixes the dispatcher to recognize the
  current `POST /api/v1/proposals` response envelope. After PR #75
  merged, image-push run `24949609883` posted `evt_761753baf9b7`
  for commit `9bd15cfb1272c8a3cb8581009395010fca1a308f`; a follow-up
  local adapter tick saw intent `intent_5dafd2b01ad5`, logged
  `ok=True` / `tools_ok=1`, and created
  `proposal_524793d66925`. That proposal had strong evidence refs but
  an empty `health_checks` list, so PR #76 hardens the deploy-agent
  prompt to require target-specific `/readiness` and `/api/v1/health`
  checks on every `fly.deploy` proposal.
- **Health-checked `deploy-llm-agent` proposal proof:** after PR #76
  merged, image-push run `24949842912` posted `image_push_completed`
  into staging as `evt_112ad64b8cc1` / `imgpush_a2f29f5cacee` for
  commit `f33c2e5b17bdfb49f440df6867ae57c08c20033b`, carrying
  staging/prod digest
  `sha256:8f1ddd83795d1fcfd9bf4cd629d19e381f26907486c2cf689c20eeed5ac83a0d`.
  The operator created intent `intent_1c7609faa698`, then ran the
  real Anthropic-backed adapter once as `deploy-llm-agent`. The tick
  logged `llm_tool_dispatch_completed ok=True` and `tools_ok=1`, and
  created `proposal_7e096a4d63fe` for `fly.deploy` targeting
  `quorum-staging`. The proposal includes `staging-readiness`
  (`https://quorum-staging.fly.dev/readiness`) and
  `staging-api-health`
  (`https://quorum-staging.fly.dev/api/v1/health`) HTTP checks with
  expected status 200 and 10s timeouts. Policy evaluated it as
  `allowed=true`, `requires_human=true`, `votes_required=2`, and
  opened human approval request `approval_req_e534744bce80`. No
  execution was claimed or attempted; this same-app staging proposal
  should remain pending unless a separate external/peer executor plan
  is intentionally run.
- **Deploy-agent same-control-plane guard:** the LLM adapter now
  includes non-secret `control_plane` metadata in every tick. It infers
  the Quorum API's Fly app from `https://<app>.fly.dev`, or from
  `QUORUM_LLM_CONTROL_PLANE_FLY_APP` for internal URLs, and rejects
  LLM-authored `fly.deploy` proposals whose payload targets that same
  app before POSTing to `/api/v1/proposals`. In practice, an adapter
  pointed at `https://quorum-staging.fly.dev` must create a finding
  instead of another same-app staging deploy proposal until a real
  external executor exists.
- **Live deploy-agent guard proof:** after PR #82 merged, image-push
  workflow run `24952013390` posted `image_push_completed` into
  staging as `evt_477e17095c3c` / `imgpush_ef526b190343` for commit
  `4bbf371a33920fd7c65c6e131239a60cd7b2ec46`, carrying
  staging/prod digest
  `sha256:b46f123bf356b2ae7cd56f12d88860713561df4938fa3b9c78d2b5d7394e3fd5`.
  The operator created intent `intent_0c97ef1f93d8` and ran one real
  Anthropic-backed `deploy-llm-agent` tick against
  `https://quorum-staging.fly.dev` with a cursor exposing only the new
  image-push evidence plus that intent. The tick logged
  `system_prompt_sha256=105f30a9b5419ed471aaddbbb4a97e9f0cfbda9614acff701feab349d19c0a26`,
  dispatched `create_finding` successfully (`finding_bdbec99b4088`),
  and did not create a `fly.deploy` proposal. Staging
  `/api/v1/events/verify` returned `event_count=83` and
  `last_hash=33817f8274654d29c7d67d206d865fb63d83eec1c01409dba833fbfbcb4bab74`.
- **Final image-push evidence before docs-only skip:** PR #83's
  docs-only handoff merge still triggered image-push run
  `24952112311`, then PR #84's workflow change triggered image-push
  run `24952195664`. The latter posted
  `evt_6394c585ff8e` / `imgpush_35d69d877e3c` for commit
  `d2a7384b34daedc55000f38f88897c30d7965cca` with staging/prod
  digest
  `sha256:06c5de817374255b6bc8f876b14381c0ec67c158b3dc65271f5ff236f2c1d3d6`.
  This is expected to be the last docs-adjacent image-push noise,
  because PR #84's `paths-ignore` is active for future docs-only
  merges.
- **Prod deployment state:** `quorum-prod` is running Fly release v9,
  which reports platform image ref
  `registry.fly.io/quorum-prod@sha256:3368f8888d951073f3278fe0e02e906d74443d11bb3cc27c6e22bb9b5b2dbade`.
  That release was requested from image-push manifest-list digest
  `sha256:459c63cdbc432c2a9e4446e95ff9dcf932127ce2a06f7fec474b3b6a69ebebcf`
  through staging proposal `proposal_ee73bc8461df`, not a direct local
  prod `fly deploy`.
  Machine `e829625b579d78` is started in `iad` with 2/2 checks
  passing, mounted volume `vol_v8emwyn2gj70k11v`, and `autostop:
  false` restored again after the live prod proof deploy reset it to
  `true`. `/readiness` and `/api/v1/health` returned HTTP 200.
  `QUORUM_API_KEYS`,
  `FLY_API_TOKEN`, and `DATABASE_URL` are deployed;
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` is deployed in prod;
  `QUORUM_ALLOW_DEMO` is unset in prod.
- **Prod Postgres projection evidence:** prod now has live actuator
  smoke events. Prod `/api/v1/events/verify` returns `event_count=20`
  and
  `last_hash=273e0dbfbbb9f2733370933405a47c6425c2f3b1668feba8435880d3db0197a2`.
  Neon-backed history endpoint counts: `intents=2`, `proposals=2`,
  `votes=4`, `executions=4`.
- **Live Fly deploy/rollback evidence:** an operator-run live actuator
  smoke deployed staging to pushed digest
  `sha256:758395f657f1abcdcbd18bffb0cba1261184cc2d8af7320bcb94602e5223092e`,
  captured previous release digest
  `sha256:6bcea0b7426c60fe21c2000d837f08ef195aa48345d34c7fda603df308da74e0`,
  then `rollback_deploy` returned staging to that previous digest.
  `/readiness`, `/api/v1/health`, and `/api/v1/events/verify` returned
  HTTP 200 after rollback.
- **Peer-controller dog-food evidence:** `quorum-staging` executed a
  real Quorum API-gated `fly.deploy` into `quorum-prod` with intent
  `intent_bead5a2f36fd` and proposal `proposal_a8803f47488e`.
  Policy allowed the action with `requires_human=true` and 2 votes
  required; `code-agent` and `operator` voted; the operator granted
  human approval. The execution deployed requested digest
  `sha256:70af699bb5bcf68f0173181eb80ece15dfe5df767d6166c9b97c212a22d46e67`,
  captured previous prod digest
  `sha256:07167f6706325481c902c5f79e95f9ca18389e9624abfa8e28bcab68961f4999`,
  verified `prod-readiness` and `prod-api-health` as HTTP 200, and
  appended this proposal chain in staging:
  `proposal_created`, `policy_evaluated`, `human_approval_requested`,
  two `proposal_voted`, `proposal_approved`,
  `human_approval_granted`, `execution_started`, two
  `health_check_completed`, `execution_succeeded`. Staging
  `/api/v1/events/verify` returned `event_count=13` and
  `last_hash=014293237212070b61472bb5577cd47317625067633d26331b50bcdfb574dbd4`.
  The latest peer-controller deploy repeated the same gated path with
  intent `intent_91a13c2a90e3` and proposal
  `proposal_7ea9efc0cc32`, deploying requested manifest-list digest
  `sha256:aa267ec52be093acd5b2e8a39c658d073f1927ceeeada5aef55c28fbe7f90f6e`
  into prod and capturing previous prod digest
  `sha256:36809cd455123b89a592a70dcf31cc91a27bb8eddb9b9ccd154830bfa0f9bcce`.
  Prod readiness and API health both passed as HTTP 200.
  The latest peer-controller deploy used the image-push evidence event
  from PR #73: intent `intent_9237553877de`, proposal
  `proposal_f7122b5cbc2a`, policy `allowed=true`,
  `requires_human=true`, `votes_required=2`, code-agent + operator
  approvals, human approval, and execution by `deploy-agent`. It
  deployed requested digest
  `sha256:1d4f28ffaf52e71d7c82a6e154c68267edcb2ea4bd01c82c9a046df72725ae4a`,
  captured previous prod digest
  `sha256:698e0ca0774a1c31c043a3c11dc698693822c22790509d7aca67b352f87952a0`,
  and recorded passing `prod-readiness` and `prod-api-health` checks.
- **Live GitHub actuator evidence:** the config-bearing image from
  PR #71 was deployed to staging, then prod was updated through
  staging's audited `fly.deploy` path. Staging proposal
  `proposal_3b0dfe573bb9` executed `github.comment_issue` against
  fixture issue #1 and created comment
  `https://github.com/jaydenpiao/quorum-actuator-fixtures/issues/1#issuecomment-4317876371`;
  the execution recorded one post-change HTTP health check as passed.
  Prod proposal `proposal_53414b49eb06` executed the same action with
  `environment=prod`; policy required two votes and human approval,
  the operator granted approval, the action created comment
  `https://github.com/jaydenpiao/quorum-actuator-fixtures/issues/1#issuecomment-4317901186`,
  and the post-change health check passed. There is also an earlier
  prod fixture comment from `proposal_1d5c2538f403` with
  `environment=staging`; keep `proposal_53414b49eb06` as the canonical
  protected-prod proof. `tests/test_github_live_integration.py` is now
  the skipped-by-default regression for the fixture comment path; run
  it with `QUORUM_GITHUB_LIVE_TESTS=1` and the Keychain-backed
  `QUORUM_GITHUB_APP_PRIVATE_KEY_B64` env when you need fresh live
  rollback evidence.
- **Same-app deploy invariant:** `fly.deploy` now refuses to run when
  `FLY_APP_NAME` matches the proposal payload's target app. A
  single-machine Quorum app must deploy a peer app or run from an
  external runner; it must not replace the process that is responsible
  for appending terminal execution and health-check events.
- **Event types dispatched:** 18 — `intent_created`, `finding_created`, `proposal_created`, `policy_evaluated`, `proposal_voted`, `proposal_approved`, `proposal_blocked`, `execution_started`, `execution_succeeded`, `execution_failed`, `health_check_completed`, `rollback_started`, `rollback_completed`, `rollback_impossible`, `human_approval_requested`, `human_approval_granted`, `human_approval_denied`, `image_push_completed`. `fly.deploy` reuses the existing `proposal_created` / `execution_*` / `rollback_*` chain; `image_push_completed` is evidence only and never executes a deploy.

## Phase status

- **✅ Phase 0** — Claude Code harness.
- **✅ Phase 1** — OSS hygiene.
- **✅ Phase 2** — core security (typed health checks, hash chain, bearer auth).
- **✅ Phase 2.5** — server-side actor binding, argon2id keys.
- **✅ Phase 3** — production foundation (Dockerfile, pytest-cov gate, structlog, Prometheus, mypy-strict, SBOM, OTel).
- **✅ Phase 3 capstone** — Postgres projection.
- **✅ Phase 4** — GitHub App actuator (4 actions + rollback + `rollback_impossible` event + `github_check_run` health check); LLM adapter (telemetry-llm-agent with `create_finding` + `create_proposal` + `allowed_action_types` gate); **human approval entity + 3 events**; **interactive console with SSE live-tail + forms**. All four Phase 4 roadmap items shipped. Tagged `v0.4.0-alpha.1`.
- **✅ Phase 5** — Fly.io deployment. All merged to `main`:
  - **PR #50** — `docs/design/fly-deployment.md`.
  - **PR #54** (replaces auto-closed #51) — `fly.toml` + `GET /readiness` + 4 tests.
  - **PR #52** — `fly.deploy` actuator + executor prefix-dispatch refactor + policy rule. 27 tests.
  - **PR #53** — SESSION_HANDOFF update.
  - **PR #55** — `deploy-llm-agent` role + system prompt + `allowed_action_types: [fly.deploy]`. 6 tests.
  - **PR #56** — image-push CI workflow, gated on `FLY_API_TOKEN`.
  - **Post-tag hardening** — Dockerfile runtime now carries pinned,
    checksummed `flyctl` as `/usr/local/bin/fly`; Python base image and
    `uv` bootstrap are pinned for reproducible builds.
  - **Post-tag image supply** — image-push CI now publishes the same
    commit image to both `quorum-staging` and `quorum-prod` Fly
    Registry namespaces and records both digests in the job summary.
  - **Post-tag image-push evidence** — image-push CI can optionally
    post a signed `image_push_completed` evidence event into Quorum
    once `QUORUM_IMAGE_PUSH_API_URL` and `QUORUM_IMAGE_PUSH_API_KEY`
    repo secrets are set. The notifier is configured against staging
    and workflow run `24925601409` proved it appends hash-chained
    evidence.
  - **Post-tag LLM proposal proof** — `deploy-llm-agent` has run
    against the live staging event stream with a real Anthropic call
    and created a `fly.deploy` proposal from `image_push_completed`
    evidence. PR #75 fixed the adapter-side result parsing so the
    current proposal response envelope logs as a successful tool
    dispatch. PR #76 fixed the prompt contract so future `fly.deploy`
    proposals include target-specific readiness and API health checks
    instead of leaving `health_checks` empty. PR #77 records the live
    proof: `proposal_7e096a4d63fe` carries the standard staging
    readiness and API-health checks. PR #78 turns that prompt contract
    into a server-side safety gate: new `fly.deploy` proposals with no
    health checks are rejected before `proposal_created`, and older
    empty-check proposals fail before the executor calls Fly.
  - **Post-tag execution safety** — same-app `fly.deploy` is blocked
    when Fly exposes `FLY_APP_NAME`, preserving terminal event writes
    for single-machine apps.
  - **Post-tag dog-food proof** — `quorum-staging` executed a real
    policy-gated, human-approved `fly.deploy` into `quorum-prod`; prod
    health checks passed and staging recorded terminal execution events.
  - **Post-tag Neon projection** — staging and prod Fly apps now have
    Neon-backed `DATABASE_URL` secrets; both DB branches are migrated
    to Alembic head, staging was reconciled from JSONL and smoke-tested
    through the Postgres-backed history API, and prod was verified
    empty but reachable.
  - **Post-tag GitHub App bootstrap** — the fixture repo exists, the
    GitHub App is registered/installed on that fixture, and the helper
    can repeat the manifest flow without printing the generated PEM.
  - **Post-tag GitHub actuator Fly proof** — staging and prod carry
    `QUORUM_GITHUB_APP_PRIVATE_KEY_B64`, run the config-bearing image,
    and executed fixture `github.comment_issue` smokes through Quorum.
    The prod proof used the protected `prod` environment gate with
    human approval.
  - **Post-tag LLM audit metadata** — `llm_call_completed` logs now
    include `system_prompt_sha256`, a SHA-256 hash of the exact system
    prompt bytes used for the tick. Prompt content remains out of
    runtime logs.
  - **Post-tag LLM adapter metrics** — the standalone adapter records
    `quorum_llm_tokens_total`, `quorum_llm_ticks_total`, and
    `quorum_llm_proposals_created_total`; operators expose them with
    `--metrics-port` or `QUORUM_LLM_METRICS_PORT`.
  - **v0.6 alpha-polish release** — tagged `v0.6.0-alpha.1` after
    PR #105. The released image was deployed through the existing
    staging-controls-prod proof path, with `deploy-llm-agent` authoring
    proposal `proposal_ee73bc8461df`, two approvals plus human
    approval, prod health checks, and a verified staging event chain.
- **⬜ Phase 6** — parallel operator-agent worktrees.

All known doc-vs-code drift is closed. No known outstanding tech debt.

## What landed since v0.3.0-alpha.1

Three PRs close the last two Phase 4 roadmap items:

- **PR #46** — README LLM quickstart + ROADMAP/HANDOFF refresh for v0.3.
- **PR #47** — Human approval entity. Three new event types (`human_approval_requested` / `_granted` / `_denied`), new `POST /api/v1/approvals/{proposal_id}` route, execute-time gate, terminal `ProposalStatus.approval_denied`, Alembic 0004 + projector handlers + dispatch-completeness update.
- **PR #48** — SSE event stream + interactive console forms. `EventLog.subscribe()` pub/sub; `GET /api/v1/events/stream`; bearer-token + `create_intent` + cast-vote + grant/deny-approval forms; EventSource live-tail.

## Phase 5 — what it unlocks

Quorum can now dog-food Fly.io deploys through a peer-controller shape.
The path an operator follows:

1. Provision a Fly app + volume per `docs/design/fly-deployment.md` §Operator pre-reqs.
2. `fly secrets set QUORUM_API_KEYS=... QUORUM_GITHUB_APP_PRIVATE_KEY_B64=... DATABASE_URL=... --app <app>`.
3. `fly deploy --app <app>` locally once for the bootstrap.
4. Optional: set `FLY_API_TOKEN` as a repo secret; every merge to
   `main` pushes tagged images to `registry.fly.io/quorum-staging` and
   `registry.fly.io/quorum-prod`.
5. Run the `deploy-llm-agent` process (`python -m apps.llm_agent.run --agent-id deploy-llm-agent`) to watch for new image digests and propose `fly.deploy` actions.
6. Approve each proposal via the operator console. The peer Quorum app
   executes `fly deploy --image registry.fly.io/quorum-prod@sha256:...`
   under the policy + human-approval gate. Same-app deploys are blocked
   until a separate executor lifecycle is designed and proven.

Three design-level invariants that hold across the whole flow:

- **Single-machine-per-app.** Fly Volumes are per-machine; `EventLog` is single-writer. Multi-machine fleets are explicitly deferred.
- **Content-addressed deploys.** `FlyDeploySpec` rejects tags at the pydantic boundary; only `sha256:<64 hex>` passes.
- **Human in the loop for every prod deploy.** `fly.deploy` policy rule is `votes_required: 2, requires_human: true`. Deploys never execute without an explicit approval entity event.
- **Peer controller for live dog-food.** A single-machine Fly app does
  not deploy itself; it deploys the peer app so terminal execution
  events survive machine replacement.

## Reading order for a fresh session

Canonical order — load these before touching code:

1. `AGENTS.md` — repo-wide operating rules and Definition of Done (binding).
2. **This file** (`docs/SESSION_HANDOFF.md`).
3. `docs/ROADMAP.md` — phase status with ✅/⏳/⬜/✂️ markers.
4. `CHANGELOG.md` — every feature since bootstrap; `v0.6.2` is the
   latest tagged trust-monitor and voter design-gate release.
5. `docs/design/phase-4-github-actuator.md` — reference (done, but the patterns are reusable).
6. `docs/design/llm-adapter.md` — reference.
7. `docs/ARCHITECTURE.md` — current system picture including the Actuators section.

Area-specific deep reads are already linked from `AGENTS.md`'s "Required reading by area" section.

## Known gotchas (earned the hard way)

Gotchas marked **[Claude-only]** are specific to the Claude Code
harness under `.claude/`. Codex and other agents can ignore them.

1. **[Repo-wide]** Gitleaks hits on API-key-shaped test fixtures.
   Generate fake values at test setup (RSA via `cryptography`, short
   `test-key-ignored` literals for Anthropic). No PEM / JWT / argon2id
   literals in `tests/`.
2. **[Repo-wide]** Dispatch-completeness test fails if a new event
   type lacks a projector handler. Add the handler in the same commit
   — already hit for `rollback_impossible` and the
   `human_approval_*` family.
3. **[Repo-wide]** `EventLog.append` is sync. Keep `apply(event)` sync.
   Subscribers are sync callbacks fan-out; they marshal to async via
   their own queue (see the SSE route).
4. **[Repo-wide]** Hash chain verification runs on startup. Tampered
   or truncated `data/events.jsonl` refuses to boot — uvicorn raises
   at import. `make reset` wipes it.
5. **[Repo-wide]** `allowed_action_types`, `can_propose` /
   `can_vote`, and other YAML caches leak between tests.
   `@lru_cache(maxsize=1)` loaders are cleared by
   `auth_module.reload_all_registries()`. Test fixtures that write
   throwaway YAMLs must call it — pattern in
   `tests/test_allowed_action_types.py`,
   `tests/test_agent_capability_gates.py`, and
   `tests/test_human_approval.py`.
6. **[Repo-wide]** Anthropic SDK in tests: construct with
   `api_key="test-key-ignored"` + `max_retries=0`; `respx` intercepts
   `https://api.anthropic.com/v1/messages`.
7. **[Repo-wide]** Do not use ambient `uv` for lockfile or validation
   work. The repo pins the resolver at `0.11.8`; use `make validate`
   or invoke it directly as `uvx --from uv==0.11.8 uv ...`. This avoids
   the old local Homebrew `uv 0.5.6` compatibility trap around dynamic
   package metadata in `uv.lock`.
8. **[Repo-wide]** `TestClient.stream()` hangs on infinite SSE
   generators. The stream never naturally terminates and context-exit
   blocks on drain. Don't try to end-to-end test the SSE endpoint
   through TestClient; assert route registration + use
   `EventLog.subscribe` tests for the delivery contract. Real
   integration tests (if needed later) belong under
   `pytest -m integration` with a uvicorn subprocess + curl.
9. **[Repo-wide]** When modifying any route handler, re-check that the
   test for it doesn't import `AUTH['agent_id']` / `AUTH['plaintext']`
   — `tests/_helpers.py` exports `AUTH` as
   `{"Authorization": f"Bearer {TEST_OPERATOR_KEY}"}`, *not* a dict
   of agent/key components.
10. **[Repo-wide]** GitHub auto-closes stacked PRs when their base
   branch is deleted on squash-merge. You cannot reopen once the base
   is gone. Either merge *without* `--delete-branch` and clean up
   afterward, or merge main into the stacked branch (regular
   fast-forward push, no force needed) + `gh pr edit <N> --base main`
   before the parent merges.
11. **[Repo-wide]** The repo's pre-tool-use hook blocks
    `git push --force*` (including `--force-with-lease`). For stacked
    PRs, prefer merging `main` into the feature branch as a regular
    push over rebase + force-push.
12. **[Repo-wide]** The repo's pre-tool-use hook blocks force-removing
    git worktrees outside the project tree. Run `make clean-worktrees`
    (added in PR #59) only when no subagents are active.
13. **[Claude-only]** Ruff `PostToolUse` hook strips unused imports
    between Edits. Workarounds: (a) add import + first usage in a
    single atomic Edit, or (b) for multi-import diffs, use `Write` to
    rewrite the file wholesale — the formatter sees only the final
    state.
14. **[Claude-only]** `backend-engineer` subagent stalls on multi-file
    Python work. Stay main-thread for complex Python changes.
15. **[Claude-only]** Output classifier trips on aggregated
    security-heavy language. Keep PR bodies lean.
16. **[Claude-only]** `docs-writer` subagent has no `Bash` tool.
    Dispatch, then finish git ops yourself.
17. **[Claude-only]** Subagent worktrees stay locked after completion.
    Use `make clean-worktrees` (PR #59) when no agents are active.
18. **[Claude-only]** `.env.example` was blocked by an over-broad deny
    rule in an older `.claude/settings.json`; fixed in PR #29.
19. **[Repo-wide]** Pinned `flyctl` v0.4.39 supports
    `fly releases --app <app> --json`, but not `--limit`. Keep release
    limiting in Quorum code/tests, not in the subprocess argv. Live
    smoke against `quorum-staging` returns `[]` before the first deploy.
20. **[Repo-wide]** `fly.toml` mounts `source = "quorum_data"`.
    Volume names are app-scoped on Fly, so both staging and prod should
    create a volume named exactly `quorum_data`. App-specific names like
    `quorum_staging_data` do not satisfy the shared config.
21. **[Repo-wide]** Same-app `fly.deploy` is blocked when
    `FLY_APP_NAME` equals the proposal payload's `app`. The safe
    near-term dog-food shape is a peer controller app or external
    runner deploying the target app. Do not remove this guard unless a
    separate executor lifecycle has been designed and live-proven.
22. **[Repo-wide]** Prod always-on requires disabling Fly machine
    autostop, not just keeping one machine in the app. The verified
    command shape is `fly machine update <machine-id> --app quorum-prod
    --autostop=off --autostart --yes`. Use `--autostop=off`; pinned
    `flyctl` parses `--autostop off` as an extra positional argument.
    Re-check and reapply this after `fly deploy` or `fly secrets set`;
    the prod `DATABASE_URL` secret update reset autostop to `true`.
23. **[Repo-wide]** Do not confuse image-push manifest-list digests
    with the platform image ref reported by `fly releases`. A docs-only
    merge can push a fresh registry digest without changing or
    deploying the running Fly release. Treat `fly releases --json` and
    `fly machine status --display-config` as the source of truth for
    what is actually deployed.
24. **[Repo-wide]** `pip-audit` currently ignores only
    `CVE-2026-3219` in CI because the advisory affects the latest
    published PyPI `pip` and has no fixed version. Do not add broad
    ignores; remove this one as soon as a fixed pip release exists.
    Keep the audit install on `--no-install-project`, the audit run on
    `--no-sync`, and the `--path "$SITE_PACKAGES"` restriction so
    strict mode does not fail on the local unpublished `quorum` package.
25. **[Repo-wide]** Neon emits default `postgresql://` connection URIs.
    Quorum must normalize those to `postgresql+psycopg://` because the
    repo ships `psycopg`, not `psycopg2`. Keep runtime engine creation
    and Alembic migrations on the same normalization helper.
26. **[Repo-wide]** Shell one-command env assignments do not affect
    expansions in the same command. `VAR=... fly secrets set
    DATABASE_URL="$VAR"` sends an empty value; assign first with
    `VAR=...; fly secrets set DATABASE_URL="$VAR"` or export the var.
27. **[Repo-wide]** `fly ssh console -C` does not inherit app secrets
    into ad-hoc commands, and it execs the given command directly
    rather than through a shell. To run one-off DB tooling inside the
    machine, inject the secret from Keychain explicitly and wrap with
    `sh -lc`, e.g. `fly ssh console -C "sh -lc 'DATABASE_URL=... python
    -m apps.api.app.tools.reconcile --output json'"`.
28. **[Repo-wide]** GitHub App manifest callback codes expire after
    one hour. If `bootstrap_github_app` captures the App but times out
    before repository installation, keep the Keychain PEM, install the
    App from the printed install URL, then use the App JWT path to
    recover `installation_id`; do not rerun and create duplicate Apps
    unless the PEM was lost.
29. **[Repo-wide]** When proving a prod runtime path, set the proposal
    `environment` to `prod` even if the target resource is a fixture.
    Otherwise the action can succeed but will not exercise the
    protected-environment human-approval gate. The canonical prod
    GitHub actuator proof is `proposal_53414b49eb06`, not the earlier
    non-protected smoke `proposal_1d5c2538f403`.
30. **[Repo-wide]** The image-push evidence notifier is intentionally
    best-effort. If the notifier secrets are missing the step is
    skipped; if staging is unavailable the step can warn instead of
    failing the image supply path. Do not treat a successful image-push
    workflow as Quorum-ingested evidence unless staging's event stream
    contains `image_push_completed`.
31. **[Repo-wide]** Older checkouts before PR #75 log a successful
    `deploy-llm-agent` proposal tool call as `ok=False` if
    `POST /api/v1/proposals` returns the current
    `{proposal, policy_decision}` envelope. Inspect the event log for
    `proposal_created` before assuming the proposal failed. The
    staging key and local Anthropic key now exist in Keychain; do not
    print them in logs or docs.
32. **[Repo-wide]** Older deploy-agent prompts before PR #76 can
    create valid `fly.deploy` proposals with strong evidence refs but
    empty `health_checks`. Before approving any LLM-authored deploy
    proposal, verify it includes the target app's `/readiness` and
    `/api/v1/health` checks. Same-app staging proposals should still
    remain pending unless run from a proven external or peer executor;
    new deploy-agent ticks pointed at `https://quorum-staging.fly.dev`
    are guarded from posting those same-app proposals.
33. **[Repo-wide]** New `fly.deploy` proposals without
    `health_checks` are rejected before the event log is mutated, and
    the executor refuses historical empty-check Fly deploys before
    invoking Fly. If you inspect older logs, a pending empty-check
    proposal may still exist as evidence, but it should not be
    considered executable.
34. **[Repo-wide]** The polished local demo is evidence of Quorum's
    control-plane path, not a live Fly mutation. The demo seeder uses a
    `_DemoFlyClient` to produce deterministic `fly.deploy` execution
    records. Use `docs/DEMO_VIDEO.md`'s read-only Fly checks when
    recording; run opt-in live integration tests separately when you
    need fresh actuator proof.
35. **[Console]** If a browser tab still shows the old dark POC console
    with **Seed demo incident**, it is stale client state, not the
    current server output. Hard-refresh or reopen `/console`. The
    console now sends no-cache headers and the recording guide calls
    this out explicitly.
36. **[Repo-wide]** Do not restore `data/events.jsonl` over a running
    uvicorn process and then keep using that same process for new
    writes. `EventLog` keeps the previous tail hash in memory, so the
    next append can create a valid-looking line whose `prev_hash`
    points at the old tail, and `/api/v1/events/verify` will fail with
    a mismatch. Stop uvicorn before copying a backup into place, or
    restart immediately after the restore. The local demo runbook's
    cleanup order already assumes this.

## Next-session candidates (pick one, by priority)

### A — LLM voter adapter support

- Add the separate `review-llm-agent` role with `can_vote: true`,
  `can_propose: false`, and `allowed_vote_action_types` limited to
  `github.add_labels` and `github.comment_issue`.
- Add the LLM adapter `cast_vote` tool without `agent_id` or audit
  metadata in the tool schema; inject `llm_model`,
  `system_prompt_sha256`, and `observed_event_cursor` from runtime
  context before calling `POST /api/v1/votes`.
- Keep telemetry/deploy LLM agents proposer-only and keep
  `fly.deploy` LLM voting out of scope.

### B — LLM voter console/docs polish

- Render LLM vote source, model, prompt hash, counted/capped state, and
  counted reason in `/console`.
- Keep executable-state copy honest: capped or ineligible LLM votes
  must not make protected/high-risk or `fly.deploy` proposals look
  actionable.
- Refresh operator docs after adapter support lands so the series is
  understandable end-to-end.

### C — Phase 6 gate check

- Phase 6 remains blocked until the documented event-schema stability
  window has elapsed. If the gate opens, switch to the worktree model in
  `docs/PARALLEL_DEVELOPMENT.md`; otherwise keep one small PR at a
  time on `main`.

## Cross-tool onboarding

This repo follows the [AGENTS.md](https://agents.md/) convention —
Codex, Claude Code, Cursor, Windsurf, and any other tool that honors
it reads `AGENTS.md` automatically.

- **Codex**: drop into the repo and let it read `AGENTS.md`. No extra
  config. The first Codex session prompt should point at the reading
  order in `INIT.md`.
- **Claude Code**: reads `CLAUDE.md` (pointer to `AGENTS.md`). Extra
  batteries (`.claude/settings.json`, hooks, subagents, skills, slash
  commands) live under `.claude/`. Gotchas #12–#17 above apply.
- **Other agents**: read `AGENTS.md`; ignore tool-specific
  directories.

The repo's pre-tool-use hooks apply to all tools equally:
- `git push --force*` is blocked.
- Force-removing worktrees outside the project tree is blocked.
- The event log path (`data/events.jsonl`) is append-only.

## Parallel development

**Stay single-thread** until Phase 6's gate is met (≥2 weeks of
event-schema stability per ROADMAP). The pattern that works:

- One main thread drives each PR end-to-end (branch → code → tests
  → push → PR → CI → pause for merge).
- Stacked PRs where one depends on another; merge `main` into the
  stacked branch after the parent merges (regular fast-forward push).
- No force-pushes. No rebasing a published branch.

When Phase 6 opens, follow `docs/PARALLEL_DEVELOPMENT.md`.

## Maintenance notes

- **Dependabot:** weekly Python, monthly Actions.
- **CI cadence:** all 5 required checks run in parallel in ~15–40 s each.
- **Release cadence:** tag when a meaningful feature set accumulates under `[Unreleased]`. Alpha tags are `v0.N.0-alpha.M`. v0.2.0 = Phase 4 GitHub actuator; v0.3.0 = Phase 4 LLM adapter; v0.4.0 = Phase 4 complete.

---

*Update this file at the end of every substantial session. Future-you reads it first.*
