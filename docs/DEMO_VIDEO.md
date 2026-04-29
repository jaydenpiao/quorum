# Quorum 3-minute demo video

This runbook records an active end-to-end Quorum workflow. The primary
demo creates a real, safe GitHub fixture issue comment through Quorum's
proposal, policy, quorum, execution, health-check, and audit path. The
dog-food Fly deploy seed remains available as a deterministic fallback
when you do not want any live mutation during recording.

## Prep

```bash
cd /Users/jaydenpiao/Desktop/Quorum
make install

export QUORUM_DEMO_BACKUP="/tmp/quorum-events-before-demo-$(date +%Y%m%d%H%M%S).jsonl"
mkdir -p data
cp data/events.jsonl "$QUORUM_DEMO_BACKUP" 2>/dev/null || true
rm -f data/events.jsonl data/state_snapshot.json

env -u DATABASE_URL \
  QUORUM_ALLOW_DEMO=1 \
  QUORUM_API_KEYS='operator:operator-key-dev,telemetry-agent:telemetry-key-dev,deploy-agent:deploy-key-dev,code-agent:code-key-dev' \
  .venv/bin/uvicorn apps.api.app.main:app --port 8080
```

For the active GitHub fixture demo, start uvicorn with the GitHub App
private key so the executor can really comment on the fixture issue:

```bash
cd /Users/jaydenpiao/Desktop/Quorum
make install

export QUORUM_DEMO_BACKUP="/tmp/quorum-events-before-demo-$(date +%Y%m%d%H%M%S).jsonl"
mkdir -p data
cp data/events.jsonl "$QUORUM_DEMO_BACKUP" 2>/dev/null || true
rm -f data/events.jsonl data/state_snapshot.json

export QUORUM_GITHUB_APP_PRIVATE_KEY_B64="$(
  security find-generic-password -a "$USER" -s quorum-github-app-private-key-b64 -w
)"

env -u DATABASE_URL \
  QUORUM_ALLOW_DEMO=1 \
  QUORUM_API_KEYS='operator:operator-key-dev,telemetry-agent:telemetry-key-dev,deploy-agent:deploy-key-dev,code-agent:code-key-dev' \
  QUORUM_GITHUB_APP_PRIVATE_KEY_B64="$QUORUM_GITHUB_APP_PRIVATE_KEY_B64" \
  .venv/bin/uvicorn apps.api.app.main:app --port 8080
```

In a second terminal:

```bash
cd /Users/jaydenpiao/Desktop/Quorum
curl -fsS http://127.0.0.1:8080/readiness | python3 -m json.tool
open http://127.0.0.1:8080/console
```

For the primary active demo, keep the console visible and run:

```bash
cd /Users/jaydenpiao/Desktop/Quorum
scripts/demo_github_fixture_flow.sh
```

The script pauses between each stage so the dashboard can visibly
change as the workflow advances.

For the deterministic fallback demo, enter bearer token
`operator-key-dev`, then click **Seed dog-food deploy demo**. If you
click the seed button with the field still empty, the console fills the
demo token automatically.

If the browser still shows the old dark POC console with **Seed demo
incident**, that is a stale tab. The server now sends no-cache headers
for `/console` and `/console-static/*`; close the tab and open
`http://127.0.0.1:8080/console` again, or hard-refresh once with
`Cmd-Shift-R`.

## Recording layout

Before pressing record:

1. Keep Terminal 1 running uvicorn from the prep command. Do not show it
   unless you want to prove the local server is running.
2. Put the browser on `http://127.0.0.1:8080/console` at roughly
   1440x900, zoom 90-100%.
3. Put Terminal 2 beside the browser with
   `scripts/demo_github_fixture_flow.sh` ready. This terminal is part of
   the demo: it represents agents/API clients driving Quorum, while the
   console shows the control-plane state.
4. Start with the console unseeded. Do not click the one-click dog-food
   seed for the primary demo.

## Exact 3-minute active run of show

| Time | What to do on screen | What to say |
|---|---|---|
| 0:00-0:15 | Browser on the empty console. Show the release badge, overview cards, empty proposal queue, and empty timeline. | "Quorum is not a chat app. It is a control plane for agents that want to touch real engineering systems. The rule is simple: agents can observe and propose, but mutations require typed proposals, policy, quorum, execution through controlled actuators, health checks, and an append-only audit log." |
| 0:15-0:35 | In Terminal 2, run `scripts/demo_github_fixture_flow.sh`. Press Enter for step 1. Browser shows a new intent. | "I am starting with an operator intent: prove Quorum can safely touch a real GitHub repository. This is not a fake UI-only object; the intent is written into the event log and reduced into dashboard state." |
| 0:35-0:55 | Press Enter for step 2. Show the event timeline gaining a `finding_created` event. | "Now an agent records evidence. In this case the safe target is fixture issue number one in `jaydenpiao/quorum-actuator-fixtures`. Quorum keeps that evidence separate from the decision to mutate." |
| 0:55-1:20 | Press Enter for step 3. Click the proposal row in the console. | "The code agent creates a typed proposal: `github.comment_issue`. The payload names the repo, issue number, comment body, rollback step, and health check. This is the core product object: not free-form permission, but a bounded action Quorum can inspect and audit." |
| 1:20-1:45 | Press Enter for step 4. Watch the vote count move to `2 approve / 0 reject`, and status become approved. | "Policy says this low-risk GitHub action needs quorum. Two independent agents vote approve. Until quorum is met, execution is blocked; after quorum is met, the proposal becomes executable." |
| 1:45-2:15 | Press Enter for step 5, then click **Execute proposal** in the console. Show `Execution succeeded`, rollback state, and the health check in the inspector. | "Now the operator executes the approved proposal. This is the real actuator call: Quorum's GitHub App posts a comment to the fixture issue, records the external comment URL, runs the health check, and only then marks execution succeeded." |
| 2:15-2:35 | Press Enter for step 6, click **Verify event chain**, then show Terminal 2 printing `/events/verify` and `gh issue view` with the created comment. | "Here is the proof: the local event chain verifies, and GitHub shows the actual comment created by the gated workflow. Quorum did something real, but only after the safety gates passed." |
| 2:35-2:55 | Return to the console timeline and scroll from `intent_created` through `execution_succeeded`. | "Every stage is replayable: intent, finding, proposal, policy decision, votes, execution, health check, and success. That is the audit trail an engineering or security team needs when AI agents touch infrastructure." |
| 2:55-3:00 | Optional: show `gh run list --limit 3`. | "The same control plane is deployed on Fly with CI and image-push evidence, so this local demo maps directly to the running system." |

## Commands to run on camera for the active demo

```bash
scripts/demo_github_fixture_flow.sh
```

The script prints each API step, waits for Enter, and ends by showing:

- local `/api/v1/events/verify`
- the actual comment on `jaydenpiao/quorum-actuator-fixtures#1`

## Fallback dog-food seed commands

Local event-chain verification:

```bash
curl -fsS http://127.0.0.1:8080/api/v1/events/verify | python3 -m json.tool
```

Read-only live Fly proof:

```bash
for app in quorum-staging quorum-prod; do
  printf "\n== %s ==\n" "$app"
  curl -fsS "https://$app.fly.dev/readiness"
  printf "\n"
  curl -fsS "https://$app.fly.dev/api/v1/events/verify" | \
    python3 -c 'import json,sys; j=json.load(sys.stdin); print("event_count", j["event_count"]); print("last_hash", j["last_hash"][:16] + "...")'
done

gh pr list --state open
gh run list --limit 3
```

Expected shape:

- Local verification prints `"ok": true` and `event_count` around `15`.
- Each Fly app prints `{"ok":true}` for readiness.
- Each Fly app's `/api/v1/events/verify` prints `"ok": true` with a
  nonzero `event_count` and a `last_hash` preview.
- `gh pr list --state open` may be empty if no review is open yet; that
  is fine. `gh run list --limit 3` should show recent successful runs on
  `main`.

## LLM-authored prod deploy proof

Use this after the alpha-polish branch has merged and image-push has
posted fresh `image_push_completed` evidence into staging. This is the
live operator proof path: the local active GitHub fixture demo remains
the default recording path, while this proves the real
`deploy-llm-agent` can author a gated `quorum-prod` deploy proposal
from production-grade event evidence.

The proof script creates a scratch cursor before it creates the
prod-promotion intent, waits for fresh image-push evidence plus staging
success evidence, runs `deploy-llm-agent --once`, and verifies that the
resulting proposal:

- was authored by `deploy-llm-agent`
- targets `quorum-prod`
- uses the exact `prod_digest`
- includes `prod-readiness` and `prod-api-health`
- cites both the image-push evidence and staging success evidence

Preferred evidence mode is `quorum-execution`: staging has a real
`execution_succeeded` event for the same digest. When same-app staging
execution is still blocked, use the explicit external evidence mode
instead. That mode does not fabricate execution; it verifies that
`quorum-staging` is already running the fresh `staging_digest`, verifies
staging `/readiness` and `/api/v1/health`, records a
`finding_created` event with `external_staging_verification`, and then
requires the prod proposal to cite that finding.

Pre-flight:

```bash
cd /Users/jaydenpiao/Desktop/Quorum
make install

export ANTHROPIC_API_KEY="$(
  security find-generic-password -a "$USER" -s quorum-anthropic-api-key -w
)"
export QUORUM_PROOF_OPERATOR_KEY="$(
  security find-generic-password -a "$USER" -s quorum-staging-operator-api-key -w
)"
export QUORUM_PROOF_CODE_AGENT_KEY="$(
  security find-generic-password -a "$USER" -s quorum-staging-code-agent-api-key -w
)"
export QUORUM_PROOF_DEPLOY_AGENT_KEY="$(
  security find-generic-password -a "$USER" -s quorum-staging-deploy-agent-api-key -w
)"
export QUORUM_PROOF_DEPLOY_LLM_AGENT_KEY="$(
  security find-generic-password -a "$USER" -s quorum-staging-deploy-llm-agent-api-key -w
)"
export QUORUM_API_KEYS="deploy-llm-agent:$QUORUM_PROOF_DEPLOY_LLM_AGENT_KEY"
```

Dry proposal proof:

```bash
scripts/prove_llm_prod_deploy.sh
```

If the script waits for fresh `image_push_completed` and then times out,
trigger the existing image-push workflow on `main`, wait for staging to
record successful deploy evidence for the same digest, and rerun the
script:

```bash
gh workflow run image-push.yml --repo jaydenpiao/quorum --ref main
gh run list --workflow image-push.yml --limit 3
```

The default script mode stops after it verifies the LLM-authored
proposal. It does not vote, grant human approval, or execute prod.

External staging verification:

```bash
QUORUM_PROOF_STAGING_EVIDENCE=external-staging-finding \
  scripts/prove_llm_prod_deploy.sh
```

Use this when image-push evidence exists but there is no
`quorum-staging` execution event because same-app execution is blocked.
The script requires `FLY_API_TOKEN` and `flyctl` so it can confirm the
current `quorum-staging` release before recording the finding. Fly may
report a platform image digest instead of the image-push manifest-list
digest, so the finding records both `staging_digest` and the
Fly-reported platform digest. If staging is not already on the literal
manifest digest, stop or opt into the direct staging deploy:

```bash
QUORUM_PROOF_STAGING_EVIDENCE=external-staging-finding \
  QUORUM_PROOF_DEPLOY_STAGING=1 \
  scripts/prove_llm_prod_deploy.sh
```

`QUORUM_PROOF_DEPLOY_STAGING=1` mutates `quorum-staging` with
`fly deploy --app quorum-staging --image registry.fly.io/quorum-staging@<staging_digest>`.
It does not mutate prod. Prod remains gated by the
`deploy-llm-agent` proposal, quorum votes, human approval, executor
health checks, rollback handling, and event-chain verification.

Guard-only proof:

```bash
QUORUM_PROOF_EXPECT_GUARD=1 scripts/prove_llm_prod_deploy.sh
```

Use this when fresh image-push evidence exists but staging success evidence is missing.
The script points `deploy-llm-agent` at the latest
image-push window, creates a guard intent, verifies the agent records a
finding, and fails if it creates a `quorum-prod` proposal before staging
has produced `execution_succeeded` plus passing health-check evidence
for the same digest.

Live execution proof:

```bash
QUORUM_PROOF_EXECUTE=1 scripts/prove_llm_prod_deploy.sh
```

Stop if any of these are false:

- the proposal author is not `deploy-llm-agent`
- the proposal target is not `quorum-prod`
- the proposal digest does not exactly match the fresh `prod_digest`
- `prod-readiness` or `prod-api-health` is missing
- the proposal does not cite both image-push and staging success
  evidence
- external staging verification records a finding without the
  Fly-reported platform digest or without staging health passing
- prod `/readiness` or `/api/v1/health` does not return HTTP 200
- staging `/api/v1/events/verify` does not return `"ok": true`

Post-execution audit capture:

```bash
QUORUM_RELEASE_TAG=v0.6.2 scripts/capture_operator_proof.sh
```

Use this after a live execution proof succeeds. The helper is
non-mutating: it reads staging root metadata, prod root metadata,
staging `/api/v1/events/verify`, prod `/readiness`, prod
`/api/v1/health`, and the latest executed `deploy-llm-agent`
`fly.deploy` proposal targeting `quorum-prod`. It writes
`proof.json` and `proof.md` under `/tmp/quorum-proof.<timestamp>/`
unless `QUORUM_PROOF_OUTPUT_DIR` is set.

Optional selectors:

- `QUORUM_PROOF_PROPOSAL_ID=<proposal_id>` captures a specific
  proposal instead of selecting the latest executed prod deploy.
- `QUORUM_PROOF_API=<url>` overrides staging; default is
  `https://quorum-staging.fly.dev`.
- `QUORUM_PROOF_PROD_URL=<url>` overrides prod; default is
  `https://quorum-prod.fly.dev`.

The capture helper fails closed if staging and prod `display_version`
drift, `QUORUM_RELEASE_TAG` does not match, event-chain verification is
not `ok=true`, prod readiness or health is not `ok=true`, the selected
proposal was not authored by `deploy-llm-agent`, the proposal is not an
executed `fly.deploy` targeting `quorum-prod`, or the terminal
execution is missing passing `prod-readiness` and `prod-api-health`
checks.

Browser acceptance checklist:

1. Open `http://127.0.0.1:8080/console` or
   `https://quorum-staging.fly.dev/console`, then clear local storage
   and reload.
2. Confirm the proposal row shows agent identity `deploy-llm-agent`,
   `fly.deploy`, target `quorum-prod`, and the expected digest.
3. Confirm the inspector shows policy allowed, two approve votes, human
   approval granted, execution succeeded, passed health checks, rollback
   state, evidence refs, and verified event chain.
4. Record the proof IDs from the script output: image-push event,
   staging execution or external staging verification finding, prod
   proposal, prod execution, and final event hash.

## Cleanup

Stop uvicorn with `Ctrl-C`, then restore the prior local event log:

```bash
cd /Users/jaydenpiao/Desktop/Quorum
backup="${QUORUM_DEMO_BACKUP:-$(ls -t /tmp/quorum-events-before-demo-*.jsonl | head -1)}"
if [ -f "$backup" ]; then
  cp "$backup" data/events.jsonl
else
  rm -f data/events.jsonl
fi
```
