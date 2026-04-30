#!/usr/bin/env bash
set -euo pipefail

API="${QUORUM_REVIEW_PROOF_API:-https://quorum-staging.fly.dev}"
API="${API%/}"
PROPOSAL_ID="${QUORUM_REVIEW_PROOF_PROPOSAL_ID:-}"
CREATE_FIXTURE="${QUORUM_REVIEW_PROOF_CREATE_FIXTURE:-0}"
TARGET="${QUORUM_REVIEW_PROOF_TARGET:-jaydenpiao/quorum#122}"
REVIEW_AGENT_KEY="${QUORUM_REVIEW_PROOF_REVIEW_AGENT_KEY:-}"
OPERATOR_KEY="${QUORUM_REVIEW_PROOF_OPERATOR_KEY:-}"
UV_VERSION="${QUORUM_REVIEW_PROOF_UV_VERSION:-${QUORUM_UV_VERSION:-0.11.8}}"
UVX="${QUORUM_REVIEW_PROOF_UVX:-${QUORUM_UVX:-uvx}}"
UV=("$UVX" --from "uv==${UV_VERSION}" uv)

if [[ -n "${QUORUM_REVIEW_PROOF_OUTPUT_DIR:-}" ]]; then
  OUTPUT_DIR="$QUORUM_REVIEW_PROOF_OUTPUT_DIR"
else
  OUTPUT_DIR="/tmp/quorum-review-proof.$(date -u +%Y%m%dT%H%M%SZ)"
fi

STATE_FILE="$OUTPUT_DIR/state.json"
EVENTS_FILE="$OUTPUT_DIR/events.json"
VERIFY_FILE="$OUTPUT_DIR/events-verify.json"
PRECHECK_FILE="$OUTPUT_DIR/precheck.json"
PROOF_JSON="$OUTPUT_DIR/proof.json"
PROOF_MD="$OUTPUT_DIR/proof.md"
CURSOR_DIR="$OUTPUT_DIR/cursor"
CURSOR_FILE="$CURSOR_DIR/review-llm-agent.json"
INTENT_PAYLOAD_FILE="$OUTPUT_DIR/fixture-intent-payload.json"
INTENT_FILE="$OUTPUT_DIR/fixture-intent.json"
FINDING_PAYLOAD_FILE="$OUTPUT_DIR/fixture-finding-payload.json"
FINDING_FILE="$OUTPUT_DIR/fixture-finding.json"
PROPOSAL_PAYLOAD_FILE="$OUTPUT_DIR/fixture-proposal-payload.json"
PROPOSAL_FILE="$OUTPUT_DIR/fixture-proposal.json"

die() {
  printf "error: %s\n" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

require_env_value() {
  local value="$1"
  local name="$2"
  [[ -n "$value" ]] || die "set $name before running this proof"
}

auth_header() {
  printf "Authorization: Bearer %s" "$1"
}

api_get() {
  curl -fsS "$API$1"
}

api_post_file() {
  local path="$1"
  local token="$2"
  local payload_file="$3"
  curl -fsS \
    -X POST "$API$path" \
    -H "$(auth_header "$token")" \
    -H "Content-Type: application/json" \
    --data-binary "@$payload_file"
}

fetch_read_state() {
  api_get "/api/v1/state" >"$STATE_FILE"
  api_get "/api/v1/events" >"$EVENTS_FILE"
  api_get "/api/v1/events/verify" >"$VERIFY_FILE"
}

write_latest_cursor() {
  python3 - "$EVENTS_FILE" "$CURSOR_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

events_path, cursor_path = sys.argv[1:]
events = json.loads(Path(events_path).read_text(encoding="utf-8"))
if not isinstance(events, list):
    raise SystemExit("events payload must be a list")
if not events:
    raise SystemExit(0)
last_event = events[-1]
if not isinstance(last_event, dict) or not isinstance(last_event.get("id"), str):
    raise SystemExit("last event is missing id")
path = Path(cursor_path)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({"cursor": last_event["id"]}, sort_keys=True) + "\n")
PY
}

write_cursor_before_proposal() {
  python3 - "$EVENTS_FILE" "$CURSOR_FILE" "$PROPOSAL_ID" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

events_path, cursor_path, proposal_id = sys.argv[1:]
events = json.loads(Path(events_path).read_text(encoding="utf-8"))
if not isinstance(events, list):
    raise SystemExit("events payload must be a list")

for index, event in enumerate(events):
    if not isinstance(event, dict):
        continue
    if event.get("event_type") != "proposal_created":
        continue
    payload = event.get("payload")
    if not isinstance(payload, dict):
        continue
    if event.get("entity_id") != proposal_id and payload.get("id") != proposal_id:
        continue
    path = Path(cursor_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if index == 0:
        path.unlink(missing_ok=True)
    else:
        previous_id = events[index - 1].get("id")
        if not isinstance(previous_id, str) or not previous_id:
            raise SystemExit("event before proposal is missing id")
        path.write_text(json.dumps({"cursor": previous_id}, sort_keys=True) + "\n")
    raise SystemExit(0)

raise SystemExit(f"proposal_created event for {proposal_id} was not found")
PY
}

json_id() {
  python3 - "$1" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("payload must be an object")
value = payload.get("id")
if not isinstance(value, str) or not value:
    raise SystemExit("payload is missing id")
print(value)
PY
}

proposal_id_from_create_response() {
  python3 - "$1" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("proposal create response must be an object")
proposal = payload.get("proposal")
if not isinstance(proposal, dict):
    raise SystemExit("proposal create response is missing proposal object")
proposal_id = proposal.get("id")
if not isinstance(proposal_id, str) or not proposal_id:
    raise SystemExit("proposal create response is missing proposal.id")
print(proposal_id)
PY
}

write_fixture_intent_payload() {
  python3 - "$TARGET" "$INTENT_PAYLOAD_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

target, output_path = sys.argv[1:]
payload = {
    "title": "Review LLM voter proof fixture",
    "description": (
        "Operator-created fixture for proving review-llm-agent can cast one "
        f"counted low-risk GitHub vote on {target}. This proof script never executes it."
    ),
    "environment": "staging",
}
Path(output_path).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_fixture_finding_payload() {
  local intent_id="$1"
  python3 - "$intent_id" "$TARGET" "$FINDING_PAYLOAD_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

intent_id, target, output_path = sys.argv[1:]
payload = {
    "intent_id": intent_id,
    "summary": (
        "Low-risk review-voter proof fixture. The target is a GitHub issue comment "
        f"on {target}; the script will verify the LLM vote but will not execute the proposal."
    ),
    "evidence_refs": ["review-voter-proof-fixture"],
    "confidence": 0.99,
}
Path(output_path).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_fixture_proposal_payload() {
  local intent_id="$1"
  local finding_id="$2"
  python3 - "$intent_id" "$finding_id" "$TARGET" "$PROPOSAL_PAYLOAD_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

intent_id, finding_id, target, output_path = sys.argv[1:]
if "#" not in target:
    raise SystemExit("QUORUM_REVIEW_PROOF_TARGET must look like owner/repo#issue")
repo_part, raw_issue = target.rsplit("#", 1)
if "/" not in repo_part:
    raise SystemExit("QUORUM_REVIEW_PROOF_TARGET must include owner/repo")
owner, repo = repo_part.split("/", 1)
try:
    issue_number = int(raw_issue)
except ValueError as exc:
    raise SystemExit("QUORUM_REVIEW_PROOF_TARGET issue number must be an integer") from exc
if issue_number < 1:
    raise SystemExit("QUORUM_REVIEW_PROOF_TARGET issue number must be positive")

payload = {
    "intent_id": intent_id,
    "title": f"Review-voter proof comment on {target}",
    "action_type": "github.comment_issue",
    "target": target,
    "environment": "staging",
    "risk": "low",
    "rationale": (
        "Low-risk fixture proposal for review-llm-agent acceptance proof. "
        "It is created only when QUORUM_REVIEW_PROOF_CREATE_FIXTURE=1 and "
        "must remain unexecuted during this proof."
    ),
    "evidence_refs": [finding_id],
    "rollback_steps": [
        "Do not execute this fixture during proof capture.",
        "If a human executes it accidentally, delete the GitHub issue comment.",
    ],
    "payload": {
        "owner": owner,
        "repo": repo,
        "issue_number": issue_number,
        "body": (
            "Quorum review-voter proof fixture. This comment proposal exists "
            "to verify counted LLM vote metadata; the proof script never executes it."
        ),
    },
}
Path(output_path).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
PY
}

create_fixture_proposal() {
  require_env_value "$OPERATOR_KEY" "QUORUM_REVIEW_PROOF_OPERATOR_KEY"

  fetch_read_state
  write_latest_cursor

  write_fixture_intent_payload
  api_post_file "/api/v1/intents" "$OPERATOR_KEY" "$INTENT_PAYLOAD_FILE" >"$INTENT_FILE"
  local intent_id
  intent_id="$(json_id "$INTENT_FILE")"

  write_fixture_finding_payload "$intent_id"
  api_post_file "/api/v1/findings" "$OPERATOR_KEY" "$FINDING_PAYLOAD_FILE" >"$FINDING_FILE"
  local finding_id
  finding_id="$(json_id "$FINDING_FILE")"

  write_fixture_proposal_payload "$intent_id" "$finding_id"
  api_post_file "/api/v1/proposals" "$OPERATOR_KEY" "$PROPOSAL_PAYLOAD_FILE" >"$PROPOSAL_FILE"
  PROPOSAL_ID="$(proposal_id_from_create_response "$PROPOSAL_FILE")"
  printf "fixture proposal: %s\n" "$PROPOSAL_ID"
}

precheck_needs_adapter() {
  python3 - "$STATE_FILE" "$EVENTS_FILE" "$VERIFY_FILE" "$PRECHECK_FILE" "$PROPOSAL_ID" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

state_path, events_path, verify_path, precheck_path, proposal_id = sys.argv[1:]

ELIGIBLE_ACTION_TYPES = {"github.comment_issue", "github.add_labels"}
PROTECTED_ENVIRONMENTS = {"prod", "production"}
REVIEW_AGENT_ID = "review-llm-agent"
PROMPT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_json(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = state.get("proposals", [])
    if not isinstance(values, list):
        fail("state.proposals must be a list")
    return [item for item in values if isinstance(item, dict)]


def select_proposal(state: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    for proposal in proposals(state):
        if proposal.get("id") == proposal_id:
            return proposal
    fail(f"proposal {proposal_id} was not found in /api/v1/state")


def require_event_chain_ok(verify: dict[str, Any]) -> None:
    if verify.get("ok") is not True:
        fail("event-chain verification must report ok=true")


def require_eligible_proposal(proposal: dict[str, Any]) -> None:
    action_type = proposal.get("action_type")
    if action_type not in ELIGIBLE_ACTION_TYPES:
        fail(
            f"proposal {proposal.get('id')} action_type must be one of "
            f"{sorted(ELIGIBLE_ACTION_TYPES)}; got {action_type!r}"
        )
    if action_type == "fly.deploy":
        fail("review-llm-agent must never vote on fly.deploy")

    environment = str(proposal.get("environment", "")).lower()
    if environment in PROTECTED_ENVIRONMENTS:
        fail(f"proposal {proposal.get('id')} targets protected environment {environment!r}")
    # non-prod target guard: this proof is allowed only for low-risk staging/local GitHub work.

    if proposal.get("risk") != "low":
        fail(f"proposal {proposal.get('id')} risk must be low")

    if proposal.get("agent_id") == REVIEW_AGENT_ID:
        fail("self-vote rejected: review-llm-agent cannot vote on its own proposal")

    if action_type == "github.comment_issue":
        payload = proposal.get("payload")
        if not isinstance(payload, dict):
            fail("github.comment_issue proposal payload must be an object")
        for field in ("owner", "repo", "issue_number", "body"):
            if field not in payload:
                fail(f"github.comment_issue payload missing {field}")
    elif action_type == "github.add_labels":
        payload = proposal.get("payload")
        if not isinstance(payload, dict):
            fail("github.add_labels proposal payload must be an object")
        for field in ("owner", "repo", "issue_number", "labels"):
            if field not in payload:
                fail(f"github.add_labels payload missing {field}")


def valid_review_vote(vote: dict[str, Any], proposal_id: str) -> bool:
    return (
        vote.get("proposal_id") == proposal_id
        and vote.get("agent_id") == REVIEW_AGENT_ID
        and vote.get("voter_kind") == "llm"
        and isinstance(vote.get("llm_model"), str)
        and bool(vote.get("llm_model"))
        and isinstance(vote.get("system_prompt_sha256"), str)
        and PROMPT_HASH_RE.match(str(vote.get("system_prompt_sha256"))) is not None
        and isinstance(vote.get("observed_event_cursor"), str)
        and bool(vote.get("observed_event_cursor"))
        and vote.get("counted") is True
        and isinstance(vote.get("counted_reason"), str)
        and bool(vote.get("counted_reason"))
    )


def find_valid_vote(state: dict[str, Any], proposal_id: str) -> dict[str, Any] | None:
    votes_by_proposal = state.get("votes", {})
    if not isinstance(votes_by_proposal, dict):
        fail("state.votes must be an object")
    votes = votes_by_proposal.get(proposal_id, [])
    if not isinstance(votes, list):
        fail(f"state.votes[{proposal_id!r}] must be a list")
    valid = [vote for vote in votes if isinstance(vote, dict) and valid_review_vote(vote, proposal_id)]
    if not valid:
        return None
    return max(valid, key=lambda item: str(item.get("created_at", "")))


state = load_json(state_path)
events = load_json(events_path)
verify = load_json(verify_path)
if not isinstance(state, dict):
    fail("state payload must be an object")
if not isinstance(events, list):
    fail("events payload must be a list")
if not isinstance(verify, dict):
    fail("verify payload must be an object")

require_event_chain_ok(verify)
proposal = select_proposal(state, proposal_id)
require_eligible_proposal(proposal)
vote = find_valid_vote(state, proposal_id)

Path(precheck_path).write_text(
    json.dumps(
        {
            "proposal": proposal,
            "existing_valid_vote": vote,
            "event_chain": verify,
            "event_count": len(events),
            "needs_adapter": vote is None,
            "note": (
                "Current policy-owned counted_reason for eligible LLM votes is "
                "typically llm_vote_counted; the proof preserves the API-owned value."
            ),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print("1" if vote is None else "0")
PY
}

run_review_agent_once() {
  require_env_value "$REVIEW_AGENT_KEY" "QUORUM_REVIEW_PROOF_REVIEW_AGENT_KEY"
  require_env_value "${ANTHROPIC_API_KEY:-}" "ANTHROPIC_API_KEY"
  require_command "$UVX"

  QUORUM_API_KEYS="review-llm-agent:${REVIEW_AGENT_KEY}" \
    ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    "${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed \
    python -m apps.llm_agent.run \
      --agent-id review-llm-agent \
      --quorum-url "$API" \
      --cursor-dir "$CURSOR_DIR" \
      --once
}

write_final_proof() {
  python3 - \
    "$STATE_FILE" \
    "$EVENTS_FILE" \
    "$VERIFY_FILE" \
    "$PRECHECK_FILE" \
    "$PROOF_JSON" \
    "$PROOF_MD" \
    "$PROPOSAL_ID" \
    "$API" <<'PY'
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

(
    state_path,
    events_path,
    verify_path,
    precheck_path,
    proof_json_path,
    proof_md_path,
    proposal_id,
    api_url,
) = sys.argv[1:]

ELIGIBLE_ACTION_TYPES = {"github.comment_issue", "github.add_labels"}
PROTECTED_ENVIRONMENTS = {"prod", "production"}
REVIEW_AGENT_ID = "review-llm-agent"
PROMPT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_json(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def select_proposal(state: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    values = state.get("proposals", [])
    if not isinstance(values, list):
        fail("state.proposals must be a list")
    for proposal in values:
        if isinstance(proposal, dict) and proposal.get("id") == proposal_id:
            return proposal
    fail(f"proposal {proposal_id} was not found in /api/v1/state")


def require_eligible_proposal(proposal: dict[str, Any]) -> None:
    action_type = proposal.get("action_type")
    if action_type not in ELIGIBLE_ACTION_TYPES:
        fail(
            f"proposal {proposal.get('id')} action_type must be eligible for LLM voting; "
            f"got {action_type!r}"
        )
    if action_type == "fly.deploy":
        fail("review-llm-agent must never vote on fly.deploy")
    environment = str(proposal.get("environment", "")).lower()
    if environment in PROTECTED_ENVIRONMENTS:
        fail(f"proposal {proposal.get('id')} targets protected environment {environment!r}")
    if proposal.get("risk") != "low":
        fail(f"proposal {proposal.get('id')} risk must be low")
    if proposal.get("agent_id") == REVIEW_AGENT_ID:
        fail("self-vote rejected: review-llm-agent cannot vote on its own proposal")


def valid_review_vote(vote: dict[str, Any], proposal_id: str) -> bool:
    return (
        vote.get("proposal_id") == proposal_id
        and vote.get("agent_id") == REVIEW_AGENT_ID
        and vote.get("voter_kind") == "llm"
        and isinstance(vote.get("llm_model"), str)
        and bool(vote.get("llm_model"))
        and isinstance(vote.get("system_prompt_sha256"), str)
        and PROMPT_HASH_RE.match(str(vote.get("system_prompt_sha256"))) is not None
        and isinstance(vote.get("observed_event_cursor"), str)
        and bool(vote.get("observed_event_cursor"))
        and vote.get("counted") is True
        and isinstance(vote.get("counted_reason"), str)
        and bool(vote.get("counted_reason"))
    )


def find_valid_vote(state: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    votes_by_proposal = state.get("votes", {})
    if not isinstance(votes_by_proposal, dict):
        fail("state.votes must be an object")
    votes = votes_by_proposal.get(proposal_id, [])
    if not isinstance(votes, list):
        fail(f"state.votes[{proposal_id!r}] must be a list")
    valid = [vote for vote in votes if isinstance(vote, dict) and valid_review_vote(vote, proposal_id)]
    if not valid:
        fail(
            "no counted review-llm-agent LLM vote with model, prompt hash, "
            "observed cursor, counted=true, and counted_reason was found"
        )
    return max(valid, key=lambda item: str(item.get("created_at", "")))


def find_vote_event(events: list[dict[str, Any]], vote_id: str) -> dict[str, Any]:
    for event in reversed(events):
        if (
            event.get("event_type") == "proposal_voted"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("id") == vote_id
        ):
            return event
    fail(f"proposal_voted event for {vote_id} was not found")


state = load_json(state_path)
events = load_json(events_path)
verify = load_json(verify_path)
precheck = load_json(precheck_path)
if not isinstance(state, dict):
    fail("state payload must be an object")
if not isinstance(events, list):
    fail("events payload must be a list")
if not isinstance(verify, dict):
    fail("verify payload must be an object")
if verify.get("ok") is not True:
    fail("event-chain verification must report ok=true")
if not isinstance(precheck, dict):
    fail("precheck payload must be an object")

proposal = select_proposal(state, proposal_id)
require_eligible_proposal(proposal)
vote = find_valid_vote(state, proposal_id)
vote_event = find_vote_event(events, str(vote["id"]))

captured_at = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
proof = {
    "captured_at": captured_at,
    "api": api_url,
    "proposal": proposal,
    "vote": vote,
    "vote_event_id": vote_event["id"],
    "event_chain": verify,
    "precheck": precheck,
}
Path(proof_json_path).write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")

summary = [
    "# Quorum Review LLM Vote Proof",
    "",
    f"- Captured: `{captured_at}`",
    f"- API: `{api_url}`",
    f"- Proposal: `{proposal['id']}`",
    f"- Action type: `{proposal['action_type']}`",
    f"- Environment: `{proposal.get('environment')}`",
    f"- Proposal author: `{proposal.get('agent_id')}`",
    f"- Vote: `{vote['id']}` by `{vote['agent_id']}`",
    f"- Voter kind: `{vote.get('voter_kind')}`",
    f"- Model: `{vote.get('llm_model')}`",
    f"- Prompt SHA-256: `{vote.get('system_prompt_sha256')}`",
    f"- Observed cursor: `{vote.get('observed_event_cursor')}`",
    f"- Counted: `{vote.get('counted')}` reason `{vote.get('counted_reason')}`",
    f"- Vote event: `{vote_event['id']}`",
    f"- Event chain: `ok=true`, count `{verify.get('event_count')}`, last hash `{verify.get('last_hash')}`",
    "",
    "This proof validates review-llm-agent on a low-risk, non-prod GitHub proposal only. "
    "The helper never executes the proposal.",
]
Path(proof_md_path).write_text("\n".join(summary) + "\n")

print(f"proof.json: {proof_json_path}")
print(f"proof.md: {proof_md_path}")
PY
}

require_command curl
require_command python3
mkdir -p "$OUTPUT_DIR"

if [[ -z "$PROPOSAL_ID" ]]; then
  if [[ "$CREATE_FIXTURE" != "1" ]]; then
    die "set QUORUM_REVIEW_PROOF_PROPOSAL_ID or set QUORUM_REVIEW_PROOF_CREATE_FIXTURE=1"
  fi
  create_fixture_proposal
else
  fetch_read_state
  write_cursor_before_proposal
fi

fetch_read_state
NEEDS_ADAPTER="$(precheck_needs_adapter)"
if [[ "$NEEDS_ADAPTER" == "1" ]]; then
  run_review_agent_once
  fetch_read_state
elif [[ "$NEEDS_ADAPTER" != "0" ]]; then
  die "unexpected precheck_needs_adapter result: $NEEDS_ADAPTER"
fi

write_final_proof
