#!/usr/bin/env bash
set -euo pipefail

API="${QUORUM_PROOF_API:-https://quorum-staging.fly.dev}"
PROD_URL="${QUORUM_PROOF_PROD_URL:-https://quorum-prod.fly.dev}"
PROPOSAL_ID="${QUORUM_PROOF_PROPOSAL_ID:-}"
RELEASE_TAG="${QUORUM_RELEASE_TAG:-}"

if [[ -n "${QUORUM_PROOF_OUTPUT_DIR:-}" ]]; then
  OUTPUT_DIR="$QUORUM_PROOF_OUTPUT_DIR"
else
  OUTPUT_DIR="/tmp/quorum-proof.$(date -u +%Y%m%dT%H%M%SZ)"
fi

die() {
  printf "error: %s\n" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

fetch_json() {
  local url="$1"
  local output="$2"
  curl -fsS "$url" >"$output"
}

require_command curl
require_command python3

mkdir -p "$OUTPUT_DIR"

STAGING_ROOT_FILE="$OUTPUT_DIR/staging-root.json"
PROD_ROOT_FILE="$OUTPUT_DIR/prod-root.json"
VERIFY_FILE="$OUTPUT_DIR/staging-events-verify.json"
STATE_FILE="$OUTPUT_DIR/staging-state.json"
EVENTS_FILE="$OUTPUT_DIR/staging-events.json"
PROD_READINESS_FILE="$OUTPUT_DIR/prod-readiness.json"
PROD_HEALTH_FILE="$OUTPUT_DIR/prod-health.json"
PROOF_JSON="$OUTPUT_DIR/proof.json"
PROOF_MD="$OUTPUT_DIR/proof.md"

fetch_json "$API/" "$STAGING_ROOT_FILE"
fetch_json "$PROD_URL/" "$PROD_ROOT_FILE"
fetch_json "$API/api/v1/events/verify" "$VERIFY_FILE"
fetch_json "$API/api/v1/state" "$STATE_FILE"
fetch_json "$API/api/v1/events" "$EVENTS_FILE"
fetch_json "$PROD_URL/readiness" "$PROD_READINESS_FILE"
fetch_json "$PROD_URL/api/v1/health" "$PROD_HEALTH_FILE"

python3 - \
  "$STAGING_ROOT_FILE" \
  "$PROD_ROOT_FILE" \
  "$VERIFY_FILE" \
  "$STATE_FILE" \
  "$EVENTS_FILE" \
  "$PROD_READINESS_FILE" \
  "$PROD_HEALTH_FILE" \
  "$PROOF_JSON" \
  "$PROOF_MD" \
  "$API" \
  "$PROD_URL" \
  "$PROPOSAL_ID" \
  "$RELEASE_TAG" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

(
    staging_root_path,
    prod_root_path,
    verify_path,
    state_path,
    events_path,
    prod_readiness_path,
    prod_health_path,
    proof_json_path,
    proof_md_path,
    api_url,
    prod_url,
    requested_proposal_id,
    release_tag,
) = sys.argv[1:]


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_json(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def require_ok(payload: dict[str, Any], label: str) -> None:
    if payload.get("ok") is not True:
        fail(f"{label} must report ok=true")


def display_version(payload: dict[str, Any], label: str) -> str:
    version = payload.get("display_version")
    if not isinstance(version, str) or not version:
        fail(f"{label} root metadata is missing display_version")
    return version


def find_latest_successful_execution(
    executions_by_proposal: dict[str, list[dict[str, Any]]],
    proposal_id: str,
) -> dict[str, Any]:
    executions = executions_by_proposal.get(proposal_id, [])
    successes = [item for item in executions if item.get("status") == "succeeded"]
    if not successes:
        fail(f"proposal {proposal_id} has no execution_succeeded record")
    return max(successes, key=lambda item: str(item.get("created_at", "")))


def select_proposal(state: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    proposals = list(state.get("proposals", []))
    if proposal_id:
        for proposal in proposals:
            if proposal.get("id") == proposal_id:
                return proposal
        fail(f"proposal {proposal_id} was not found in staging state")

    candidates = [
        proposal
        for proposal in proposals
        if proposal.get("status") == "executed"
        and proposal.get("agent_id") == "deploy-llm-agent"
        and proposal.get("action_type") == "fly.deploy"
        and proposal.get("target") == "quorum-prod"
    ]
    if not candidates:
        fail("no executed deploy-llm-agent fly.deploy proposal targeting quorum-prod found")
    return max(candidates, key=lambda item: str(item.get("created_at", "")))


def require_selected_proposal(proposal: dict[str, Any]) -> None:
    proposal_id = proposal.get("id", "<unknown>")
    required = {
        "status": "executed",
        "agent_id": "deploy-llm-agent",
        "action_type": "fly.deploy",
        "target": "quorum-prod",
    }
    for field, expected in required.items():
        if proposal.get(field) != expected:
            fail(
                f"proposal {proposal_id} must have {field}={expected!r}; "
                f"got {proposal.get(field)!r}"
            )


def require_execution_health(execution: dict[str, Any]) -> list[dict[str, Any]]:
    checks = list(execution.get("health_checks", []))
    if not checks:
        fail(f"execution {execution.get('id')} must include health_checks")
    failed = [check for check in checks if check.get("passed") is not True]
    if failed:
        fail(f"execution {execution.get('id')} has failed health_checks: {failed!r}")
    names = {check.get("name") for check in checks}
    for required_name in ("prod-readiness", "prod-api-health"):
        if required_name not in names:
            fail(f"execution {execution.get('id')} is missing {required_name} health check")
    return checks


def find_execution_event(events: list[dict[str, Any]], execution_id: str) -> dict[str, Any]:
    for event in reversed(events):
        if (
            event.get("event_type") == "execution_succeeded"
            and event.get("payload", {}).get("id") == execution_id
        ):
            return event
    fail(f"execution_succeeded event for {execution_id} was not found")


staging_root = load_json(staging_root_path)
prod_root = load_json(prod_root_path)
verify = load_json(verify_path)
state = load_json(state_path)
events = load_json(events_path)
prod_readiness = load_json(prod_readiness_path)
prod_health = load_json(prod_health_path)

staging_version = display_version(staging_root, "staging")
prod_version = display_version(prod_root, "prod")
if staging_version != prod_version:
    fail(
        "versions drift: "
        f"staging display_version={staging_version!r}, prod display_version={prod_version!r}"
    )
if release_tag and staging_version != release_tag:
    fail(f"QUORUM_RELEASE_TAG={release_tag!r} does not match display_version={staging_version!r}")

require_ok(verify, "staging /api/v1/events/verify")
require_ok(prod_readiness, "prod /readiness")
require_ok(prod_health, "prod /api/v1/health")

proposal = select_proposal(state, requested_proposal_id)
require_selected_proposal(proposal)

execution = find_latest_successful_execution(
    dict(state.get("executions", {})),
    str(proposal["id"]),
)
health_checks = require_execution_health(execution)
execution_event = find_execution_event(list(events), str(execution["id"]))

captured_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
proof = {
    "captured_at": captured_at,
    "api": api_url,
    "prod_url": prod_url,
    "release_tag": release_tag or staging_version,
    "staging_root": staging_root,
    "prod_root": prod_root,
    "staging_event_chain": verify,
    "prod_readiness": prod_readiness,
    "prod_health": prod_health,
    "proposal": proposal,
    "execution": execution,
    "execution_succeeded_event_id": execution_event["id"],
    "health_checks": health_checks,
}

Path(proof_json_path).write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")

summary = [
    "# Quorum Operator Proof",
    "",
    f"- Captured: `{captured_at}`",
    f"- Release: `{proof['release_tag']}`",
    f"- Staging API: `{api_url}`",
    f"- Prod URL: `{prod_url}`",
    f"- Event chain: `ok=true`, count `{verify.get('event_count')}`, last hash `{verify.get('last_hash')}`",
    f"- Proposal: `{proposal['id']}` by `{proposal['agent_id']}` targeting `{proposal['target']}`",
    f"- Execution: `{execution['id']}` status `{execution['status']}`",
    f"- Execution event: `{execution_event['id']}`",
    "- Prod checks: `readiness ok=true`, `api health ok=true`",
    "",
    "## Health Checks",
]
for check in health_checks:
    summary.append(f"- `{check.get('name')}` passed=`{check.get('passed')}` detail=`{check.get('detail', '')}`")
Path(proof_md_path).write_text("\n".join(summary) + "\n")

print(f"proof.json: {proof_json_path}")
print(f"proof.md: {proof_md_path}")
PY
