# Quorum 3-minute demo video

This runbook records the polished local demo without mutating live Fly
or GitHub resources. The local seeder exercises the real Quorum
proposal, policy, vote, approval, executor, health-check, and event-log
paths with a deterministic Fly client stub.

## Prep

```bash
cd /Users/jaydenpiao/Desktop/Quorum

export QUORUM_DEMO_BACKUP="/tmp/quorum-events-before-demo-$(date +%Y%m%d%H%M%S).jsonl"
mkdir -p data
cp data/events.jsonl "$QUORUM_DEMO_BACKUP" 2>/dev/null || true
rm -f data/events.jsonl data/state_snapshot.json

env -u DATABASE_URL \
  QUORUM_ALLOW_DEMO=1 \
  QUORUM_API_KEYS='operator:operator-key-dev,telemetry-agent:telemetry-key-dev,deploy-agent:deploy-key-dev,code-agent:code-key-dev' \
  .venv/bin/uvicorn apps.api.app.main:app --port 8080
```

In a second terminal:

```bash
cd /Users/jaydenpiao/Desktop/Quorum
curl -fsS http://127.0.0.1:8080/readiness | python3 -m json.tool
open http://127.0.0.1:8080/console
```

Enter bearer token `operator-key-dev`, then click **Seed dog-food
deploy demo**.

## Recording layout

Before pressing record:

1. Keep Terminal 1 running uvicorn from the prep command. Do not show it
   unless you want to prove the local server is running.
2. Put the browser on `http://127.0.0.1:8080/console` at roughly
   1440x900, zoom 90-100%.
3. Put Terminal 2 beside or behind the browser with the local
   verification and read-only live proof commands ready to paste.
4. Start with the console unseeded, token field empty or already filled
   with `operator-key-dev`. Filling it on camera is fine.

## Exact 3-minute run of show

| Time | What to do on screen | What to say |
|---|---|---|
| 0:00-0:15 | Browser on the empty console. Slowly move across the left nav, overview cards, proposal table, timeline, and inspector. | "Quorum is a control plane for agentic engineering. The point is not another chat UI. Agents can investigate systems and propose real code or infrastructure changes, but mutation goes through typed proposals, policy, quorum voting, human approval when required, post-change health checks, rollback metadata, and an append-only audit log." |
| 0:15-0:30 | Type `operator-key-dev` in the bearer-token field if it is not already set. Click **Seed dog-food deploy demo**. | "For the demo, I am seeding a deterministic dog-food deployment story. Nothing live is mutated during recording. The seed uses Quorum's real event log, reducer, policy engine, quorum engine, executor, and health-check path with a stubbed Fly client." |
| 0:30-0:48 | Keep the overview cards visible after the seed. Point to `prod`, `2/2` health, and `15 events`. | "The story is realistic: GitHub Actions has published a new content-addressed Quorum image. Agents see image-push evidence and propose promoting that exact digest from staging toward production." |
| 0:48-1:12 | Click or hover the proposal row. Keep the proposal table and inspector visible. | "This is the central product object: a typed `fly.deploy` proposal targeting `quorum-prod`. It is high risk, it names the target app, it carries a pinned `sha256` image digest, and it includes rollback steps plus required prod readiness and API-health checks." |
| 1:12-1:38 | In the inspector, show `Policy allowed`, `Votes 2 approve / 0 reject`, and `Human approval granted`. | "Because the proposal targets production, policy does not let an agent execute alone. Quorum records the policy decision, requires two independent votes, and records a human approval outcome before the executor is allowed to run." |
| 1:38-2:05 | Show `Execution succeeded`, `Released digest`, `Previous digest`, and the health-check list. | "The executor is the only component that records mutation events. It captures the previous production image digest for rollback, deploys the requested digest through the Fly actuator path, runs the post-change checks, and only marks execution succeeded after those checks pass." |
| 2:05-2:25 | Scroll the event timeline from `image_push_completed` through `execution_succeeded`; point to shortened hashes. | "Every state transition is an event: image evidence, intent, findings, proposal, policy, votes, approval, execution, health checks, and success. The hashes show that this is not just a dashboard state dump. It is replayable, append-only operational evidence." |
| 2:25-2:38 | Switch to Terminal 2 and run the local verify command below. | "The local event chain verifies cleanly. That means the demo state can be audited independently from the UI." |
| 2:38-2:55 | Run the read-only live Fly proof command below. Show both apps returning readiness and event-chain verification. | "For live proof, I am only reading from the deployed control planes. Staging and prod are up on Fly and both expose verifiable event chains. This connects the local product demo to the real deployed infrastructure without doing a live mutation on camera." |
| 2:55-3:00 | Run `gh pr list --state open` and `gh run list --limit 3`, or show the output if already run. | "Finally, GitHub shows the current review and CI state. The operational loop is console, policy gate, execution evidence, deployed health, and auditability." |

## Commands to run on camera

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
