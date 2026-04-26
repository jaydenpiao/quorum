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

## Script

| Time | Show | Say |
|---|---|---|
| 0:00-0:20 | Redesigned console overview | "Quorum is infrastructure for agentic engineering. Agents can investigate and propose real code or infrastructure changes, but execution is gated by policy, quorum, human approval, health checks, rollback, and an audit log." |
| 0:20-0:45 | Click seed demo, show overview cards | "This seeds a dog-food deploy story: CI has pushed a new Quorum image digest, agents have evidence, and the deploy-agent proposes promoting it to production." |
| 0:45-1:20 | Proposal table + inspector | "The proposal is typed: `fly.deploy`, target `quorum-prod`, high risk, pinned sha256 digest, rollback steps, and explicit prod readiness/API-health checks." |
| 1:20-1:55 | Policy/votes/approval fields | "Because this is prod, policy requires two votes and human approval. The event log records the policy decision, votes from independent roles, and the approval outcome." |
| 1:55-2:25 | Execution result + health checks + timeline | "The executor runs the action path, captures the previous image digest for rollback, records post-change health checks, and only then marks the execution succeeded." |
| 2:25-2:40 | Local event-chain verification | "The audit trail is append-only and hash chained." |
| 2:40-3:00 | Read-only live Fly/GitHub proof | "The same control plane is live on Fly staging and prod, and GitHub shows the current review and CI state." |

Local verification command:

```bash
curl -fsS http://127.0.0.1:8080/api/v1/events/verify | python3 -m json.tool
```

Read-only live proof:

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
