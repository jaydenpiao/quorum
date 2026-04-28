#!/usr/bin/env bash
set -euo pipefail

API="${QUORUM_DEMO_API:-http://127.0.0.1:8080}"
OPERATOR_KEY="${QUORUM_DEMO_OPERATOR_KEY:-operator-key-dev}"
TELEMETRY_KEY="${QUORUM_DEMO_TELEMETRY_KEY:-telemetry-key-dev}"
CODE_KEY="${QUORUM_DEMO_CODE_KEY:-code-key-dev}"
FIXTURE_REPO="${QUORUM_DEMO_FIXTURE_REPO:-jaydenpiao/quorum-actuator-fixtures}"
FIXTURE_ISSUE="${QUORUM_DEMO_FIXTURE_ISSUE:-1}"

pause() {
  printf "\n%s\n" "$1"
  read -r -p "Press Enter to continue..."
}

post_json() {
  local path="$1"
  local token="$2"
  local payload="$3"
  curl -fsS \
    -X POST "$API$path" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    --data "$payload"
}

json_value() {
  python3 -c 'import json,sys; obj=json.load(sys.stdin); cur=obj
for key in sys.argv[1].split("."):
    cur = cur[key]
print(cur)' "$1"
}

json_payload() {
  python3 - "$@" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime

kind = sys.argv[1]
if kind == "intent":
    print(json.dumps({
        "title": "Prove Quorum can safely touch a real GitHub repo",
        "description": "Create a fixture issue comment only after evidence, policy, quorum votes, execution, and health verification.",
        "environment": "local",
        "requested_by": "operator",
    }))
elif kind == "finding":
    print(json.dumps({
        "intent_id": sys.argv[2],
        "agent_id": "telemetry-agent",
        "summary": "Fixture issue #1 is a safe target for live actuator proof; the operation is reversible and isolated from production code.",
        "evidence_refs": [
            f"github:{os.environ['FIXTURE_REPO']}#{os.environ['FIXTURE_ISSUE']}",
            "scope:fixture-only",
        ],
        "confidence": 0.96,
    }))
elif kind == "proposal":
    intent_id = sys.argv[2]
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps({
        "intent_id": intent_id,
        "agent_id": "code-agent",
        "title": "Post Quorum-gated proof comment to fixture issue",
        "action_type": "github.comment_issue",
        "target": f"{os.environ['FIXTURE_REPO']}#{os.environ['FIXTURE_ISSUE']}",
        "environment": "local",
        "risk": "low",
        "rationale": "Demonstrate the full Quorum control path against a real, safe GitHub fixture target.",
        "evidence_refs": [
            f"intent:{intent_id}",
            f"github:{os.environ['FIXTURE_REPO']}#{os.environ['FIXTURE_ISSUE']}",
        ],
        "rollback_steps": [
            "Delete the created issue comment by comment_id if follow-up cleanup is needed.",
        ],
        "health_checks": [
            {"name": "fixture-comment-smoke", "kind": "always_pass"},
        ],
        "payload": {
            "owner": os.environ["FIXTURE_REPO"].split("/", 1)[0],
            "repo": os.environ["FIXTURE_REPO"].split("/", 1)[1],
            "issue_number": int(os.environ["FIXTURE_ISSUE"]),
            "body": f"Quorum demo proof at {stamp}: this comment was created only after typed proposal, policy evaluation, quorum votes, execution, and health verification.",
        },
    }))
elif kind == "vote":
    print(json.dumps({
        "proposal_id": sys.argv[2],
        "agent_id": sys.argv[3],
        "decision": "approve",
        "reason": sys.argv[4],
    }))
elif kind == "execute":
    print(json.dumps({"actor_id": "operator"}))
else:
    raise SystemExit(f"unknown payload kind: {kind}")
PY
}

export FIXTURE_REPO FIXTURE_ISSUE

printf "Using Quorum API: %s\n" "$API"
printf "Using fixture target: %s#%s\n" "$FIXTURE_REPO" "$FIXTURE_ISSUE"
curl -fsS "$API/readiness" >/dev/null

pause "1/6 Create an operator intent."
intent_json="$(post_json "/api/v1/intents" "$OPERATOR_KEY" "$(json_payload intent)")"
intent_id="$(printf "%s" "$intent_json" | json_value id)"
printf "created intent: %s\n" "$intent_id"

pause "2/6 Record an agent finding with fixture evidence."
finding_json="$(post_json "/api/v1/findings" "$TELEMETRY_KEY" "$(json_payload finding "$intent_id")")"
finding_id="$(printf "%s" "$finding_json" | json_value id)"
printf "created finding: %s\n" "$finding_id"

pause "3/6 Have the code agent create a typed github.comment_issue proposal."
proposal_json="$(post_json "/api/v1/proposals" "$CODE_KEY" "$(json_payload proposal "$intent_id")")"
proposal_id="$(printf "%s" "$proposal_json" | json_value proposal.id)"
printf "created proposal: %s\n" "$proposal_id"

pause "4/6 Cast independent quorum votes from telemetry-agent and code-agent."
post_json "/api/v1/votes" "$TELEMETRY_KEY" "$(json_payload vote "$proposal_id" telemetry-agent "fixture target and evidence are scoped")" >/dev/null
post_json "/api/v1/votes" "$CODE_KEY" "$(json_payload vote "$proposal_id" code-agent "typed payload and rollback steps reviewed")" >/dev/null
printf "proposal approved by quorum: %s\n" "$proposal_id"

pause "5/6 Execute the approved proposal through the GitHub actuator."
execute_json="$(post_json "/api/v1/proposals/$proposal_id/execute" "$OPERATOR_KEY" "$(json_payload execute)")"
printf "%s\n" "$execute_json" | python3 -m json.tool
comment_url="$(printf "%s" "$execute_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"].get("comment_url", ""))')"
printf "created GitHub comment: %s\n" "$comment_url"

pause "6/6 Verify the local event chain and show the fixture issue comments."
curl -fsS "$API/api/v1/events/verify" | python3 -m json.tool
if command -v gh >/dev/null 2>&1; then
  gh issue view "$FIXTURE_ISSUE" --repo "$FIXTURE_REPO" --comments
else
  printf "gh not found; open %s manually.\n" "$comment_url"
fi
