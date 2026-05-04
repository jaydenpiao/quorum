#!/usr/bin/env bash
set -euo pipefail

API="${QUORUM_CONSOLE_PROOF_API:-https://quorum-staging.fly.dev}"
RELEASE_TAG="${QUORUM_RELEASE_TAG:-v0.6.6}"
PROPOSAL_ID="${QUORUM_CONSOLE_PROOF_PROPOSAL_ID:-}"
EXPECT_AGENT="${QUORUM_CONSOLE_PROOF_EXPECT_AGENT:-deploy-llm-agent}"
EXPECT_ACTION="${QUORUM_CONSOLE_PROOF_EXPECT_ACTION:-fly.deploy}"
EXPECT_TARGET="${QUORUM_CONSOLE_PROOF_EXPECT_TARGET:-quorum-prod}"
CURL_RETRIES="${QUORUM_CONSOLE_PROOF_CURL_RETRIES:-4}"
CURL_RETRY_DELAY_SECONDS="${QUORUM_CONSOLE_PROOF_CURL_RETRY_DELAY_SECONDS:-2}"
CURL_CONNECT_TIMEOUT_SECONDS="${QUORUM_CONSOLE_PROOF_CURL_CONNECT_TIMEOUT_SECONDS:-10}"
CURL_MAX_TIME_SECONDS="${QUORUM_CONSOLE_PROOF_CURL_MAX_TIME_SECONDS:-30}"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quorum-console-proof.XXXXXX")"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

die() {
  printf "error: %s\n" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

fetch() {
  local label="$1"
  local url="$2"
  local output="$3"
  local stderr_file="$TMP_DIR/${label//[^A-Za-z0-9_.-]/_}.curl.stderr"

  printf "checking %s: %s\n" "$label" "$url" >&2
  if curl \
    --fail \
    --silent \
    --show-error \
    --retry "$CURL_RETRIES" \
    --retry-delay "$CURL_RETRY_DELAY_SECONDS" \
    --retry-all-errors \
    --connect-timeout "$CURL_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$CURL_MAX_TIME_SECONDS" \
    "$url" >"$output" 2>"$stderr_file"; then
    return 0
  fi

  local status="$?"
  printf "error: %s fetch failed after %s retries: %s\n" \
    "$label" "$CURL_RETRIES" "$url" >&2
  if [[ -s "$stderr_file" ]]; then
    sed 's/^/curl: /' "$stderr_file" >&2
  fi
  return "$status"
}

require_command curl
require_command python3

ROOT_FILE="$TMP_DIR/root.json"
STATE_FILE="$TMP_DIR/state.json"
VERIFY_FILE="$TMP_DIR/events-verify.json"
APP_JS_FILE="$TMP_DIR/console-app.js"
CONSOLE_FILE="$TMP_DIR/console.html"

BASE_URL="${API%/}"

fetch "root metadata" "$BASE_URL/" "$ROOT_FILE"
fetch "state" "$BASE_URL/api/v1/state" "$STATE_FILE"
fetch "event-chain verify" "$BASE_URL/api/v1/events/verify" "$VERIFY_FILE"
fetch "console static app" "$BASE_URL/console-static/app.js" "$APP_JS_FILE"

SELECTED_PROPOSAL_ID="$(
  python3 - \
    "$ROOT_FILE" \
    "$STATE_FILE" \
    "$VERIFY_FILE" \
    "$APP_JS_FILE" \
    "$RELEASE_TAG" \
    "$PROPOSAL_ID" \
    "$EXPECT_AGENT" \
    "$EXPECT_ACTION" \
    "$EXPECT_TARGET" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

(
    root_path,
    state_path,
    verify_path,
    app_js_path,
    release_tag,
    requested_proposal_id,
    expected_agent,
    expected_action,
    expected_target,
) = sys.argv[1:]


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_object(path: str, label: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        fail(f"{label} did not return a JSON object")
    return payload


def proposal_matches(proposal: dict[str, Any]) -> bool:
    return (
        proposal.get("agent_id") == expected_agent
        and proposal.get("action_type") == expected_action
        and proposal.get("target") == expected_target
        and proposal.get("status") == "executed"
    )


root = load_object(root_path, "root metadata")
if root.get("display_version") != release_tag:
    fail(
        "root display_version drift: "
        f"expected {release_tag!r}, got {root.get('display_version')!r}"
    )

verify = load_object(verify_path, "event-chain verify")
if verify.get("ok") is not True:
    fail("event-chain verification must return ok=true")

app_js = Path(app_js_path).read_text(encoding="utf-8")
for needle in (
    "proposalIdFromLocation",
    "updateSelectedProposalUrl",
    "renderInspector",
    "/api/v1/events/verify",
):
    if needle not in app_js:
        fail(f"console static app is missing required proof surface {needle!r}")

state = load_object(state_path, "state")
proposals = state.get("proposals", [])
if not isinstance(proposals, list):
    fail("state.proposals must be a list")

if requested_proposal_id:
    proposal = next(
        (
            item
            for item in proposals
            if isinstance(item, dict) and item.get("id") == requested_proposal_id
        ),
        None,
    )
    if proposal is None:
        fail(f"requested proposal not found: {requested_proposal_id}")
else:
    proposal = next(
        (item for item in reversed(proposals) if isinstance(item, dict) and proposal_matches(item)),
        None,
    )
    if proposal is None:
        fail(
            "no executed proposal matched "
            f"agent={expected_agent!r} action={expected_action!r} target={expected_target!r}"
        )

print(proposal["id"])
PY
)"

CONSOLE_FETCH_URL="$BASE_URL/console?proposal_id=$SELECTED_PROPOSAL_ID"
CONSOLE_URL="$CONSOLE_FETCH_URL#proposals"
fetch "console proof shell" "$CONSOLE_FETCH_URL" "$CONSOLE_FILE"

python3 - \
  "$ROOT_FILE" \
  "$STATE_FILE" \
  "$VERIFY_FILE" \
  "$APP_JS_FILE" \
  "$CONSOLE_FILE" \
  "$RELEASE_TAG" \
  "$SELECTED_PROPOSAL_ID" \
  "$EXPECT_AGENT" \
  "$EXPECT_ACTION" \
  "$EXPECT_TARGET" \
  "$CONSOLE_URL" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

(
    root_path,
    state_path,
    verify_path,
    app_js_path,
    console_path,
    release_tag,
    proposal_id,
    expected_agent,
    expected_action,
    expected_target,
    console_url,
) = sys.argv[1:]


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_object(path: str, label: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        fail(f"{label} did not return a JSON object")
    return payload


def vote_counts(vote: dict[str, Any]) -> bool:
    return vote.get("decision") == "approve" and vote.get("counted") is not False


def latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[-1] if items else None


root = load_object(root_path, "root metadata")
if root.get("display_version") != release_tag:
    fail(
        "root display_version drift: "
        f"expected {release_tag!r}, got {root.get('display_version')!r}"
    )

verify = load_object(verify_path, "event-chain verify")
if verify.get("ok") is not True:
    fail("event-chain verification must return ok=true")

console_html = Path(console_path).read_text(encoding="utf-8")
for needle in (
    "/console-static/styles.css",
    '<script defer src="/console-static/app.js"></script>',
    'id="release-badge"',
    'id="proposal-inspector"',
    'id="metric-chain-status"',
):
    if needle not in console_html:
        fail(f"console shell is missing required proof surface {needle!r}")
if "POC console" in console_html:
    fail("console shell is stale POC console")

app_js = Path(app_js_path).read_text(encoding="utf-8")
for needle in (
    "proposalIdFromLocation",
    "updateSelectedProposalUrl",
    "renderInspector",
    "renderChecks",
    "renderRollback",
    "/api/v1/events/verify",
):
    if needle not in app_js:
        fail(f"console static app is missing required proof surface {needle!r}")

state = load_object(state_path, "state")
proposals = state.get("proposals", [])
if not isinstance(proposals, list):
    fail("state.proposals must be a list")
proposal = next(
    (item for item in proposals if isinstance(item, dict) and item.get("id") == proposal_id),
    None,
)
if proposal is None:
    fail(f"proposal not found: {proposal_id}")

if proposal.get("agent_id") != expected_agent:
    fail(f"proposal agent drift: expected {expected_agent!r}, got {proposal.get('agent_id')!r}")
if proposal.get("action_type") != expected_action:
    fail(
        f"proposal action drift: expected {expected_action!r}, "
        f"got {proposal.get('action_type')!r}"
    )
if proposal.get("target") != expected_target:
    fail(
        f"proposal target drift: expected {expected_target!r}, "
        f"got {proposal.get('target')!r}"
    )
if proposal.get("status") != "executed":
    fail(f"proposal must be terminal executed, got {proposal.get('status')!r}")

payload = proposal.get("payload", {})
if isinstance(payload, dict) and expected_action == "fly.deploy":
    if payload.get("app") != expected_target:
        fail(f"fly.deploy payload app must be {expected_target!r}")

policy = state.get("policy_decisions", {}).get(proposal_id)
if not isinstance(policy, dict):
    fail("selected proposal is missing policy decision")
if policy.get("allowed") is not True:
    fail("selected proposal policy must be allowed")
votes_required = int(policy.get("votes_required") or 0)

votes = state.get("votes", {}).get(proposal_id, [])
if not isinstance(votes, list):
    fail("selected proposal votes must be a list")
counted_approves = [vote for vote in votes if isinstance(vote, dict) and vote_counts(vote)]
if len(counted_approves) < votes_required:
    fail(f"selected proposal is missing quorum votes: {len(counted_approves)}/{votes_required}")

approvals = state.get("human_approvals", {}).get(proposal_id, [])
if not isinstance(approvals, list):
    fail("selected proposal human approvals must be a list")
if policy.get("requires_human") and not any(
    isinstance(approval, dict) and approval.get("decision") == "granted"
    for approval in approvals
):
    fail("selected proposal is missing granted human approval")

executions = state.get("executions", {}).get(proposal_id, [])
if not isinstance(executions, list):
    fail("selected proposal executions must be a list")
execution = latest([item for item in executions if isinstance(item, dict)])
if execution is None:
    fail("selected proposal is missing execution record")
if execution.get("status") != "succeeded":
    fail(f"selected proposal execution must be succeeded, got {execution.get('status')!r}")

checks = execution.get("health_checks", [])
if not isinstance(checks, list) or not checks:
    fail("selected proposal execution is missing health checks")
if not all(isinstance(check, dict) and check.get("passed") is True for check in checks):
    fail("selected proposal execution has failed health checks")
check_names = {check.get("name") for check in checks if isinstance(check, dict)}
if expected_target == "quorum-prod" and {"prod-readiness", "prod-api-health"} - check_names:
    fail("selected prod proposal is missing prod-readiness/prod-api-health checks")

last_hash = verify.get("last_hash", "unknown")
print(f"console-proof-ok: {console_url} proposal={proposal_id} event_chain={last_hash}")
PY
