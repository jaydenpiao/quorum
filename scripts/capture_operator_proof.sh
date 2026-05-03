#!/usr/bin/env bash
set -euo pipefail

API="${QUORUM_PROOF_API:-https://quorum-staging.fly.dev}"
PROD_URL="${QUORUM_PROOF_PROD_URL:-https://quorum-prod.fly.dev}"
PROPOSAL_ID="${QUORUM_PROOF_PROPOSAL_ID:-}"
RELEASE_TAG="${QUORUM_RELEASE_TAG:-}"
GITHUB_REPO="${QUORUM_PROOF_GITHUB_REPO:-jaydenpiao/quorum}"

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
  "$RELEASE_TAG" \
  "$GITHUB_REPO" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

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
    github_repo,
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


def find_required_event(
    events: list[dict[str, Any]],
    event_type: str,
    label: str,
    predicate: object,
) -> dict[str, Any]:
    if not callable(predicate):
        fail(f"internal error: predicate for {label} is not callable")
    for event in reversed(events):
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload", {})
        if isinstance(payload, dict) and predicate(payload):
            return event
    fail(f"{label} event was not found")


def find_matching_events(
    events: list[dict[str, Any]],
    event_type: str,
    predicate: object,
) -> list[dict[str, Any]]:
    if not callable(predicate):
        fail(f"internal error: predicate for {event_type} is not callable")
    matches: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload", {})
        if isinstance(payload, dict) and predicate(payload):
            matches.append(event)
    return matches


def event_payload_id(event: dict[str, Any]) -> str:
    payload = event.get("payload", {})
    if isinstance(payload, dict) and isinstance(payload.get("id"), str):
        return payload["id"]
    fail(f"event {event.get('id')} is missing payload.id")


def release_metadata(github_repo: str, tag: str, expected_asset_name: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{github_repo}/releases/tags/{quote(tag, safe='')}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "quorum-operator-proof-capture",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            release = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        fail(f"GitHub release metadata fetch failed for {tag}: HTTP {exc.code}")
    except URLError as exc:
        fail(f"GitHub release metadata fetch failed for {tag}: {exc.reason}")

    if not isinstance(release, dict):
        fail(f"GitHub release metadata for {tag} did not return an object")
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        fail(f"GitHub release metadata for {tag} has invalid assets")
    asset = next(
        (item for item in assets if isinstance(item, dict) and item.get("name") == expected_asset_name),
        None,
    )
    if asset is None:
        fail(f"GitHub release metadata is missing SBOM asset {expected_asset_name!r}")
    digest = asset.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        fail(f"SBOM asset {expected_asset_name!r} is missing a sha256 digest")
    return {
        "tag_name": release.get("tag_name"),
        "html_url": release.get("html_url"),
        "published_at": release.get("published_at"),
        "sbom_asset_name": expected_asset_name,
        "sbom_asset_url": asset.get("browser_download_url"),
        "sbom_asset_digest": digest,
    }


def join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


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

captured_at = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
resolved_release_tag = release_tag or staging_version
release_url = f"https://github.com/{github_repo}/releases/tag/{resolved_release_tag}"
sbom_asset_name = f"quorum-{resolved_release_tag}.spdx.json"
sbom_asset_url = (
    f"https://github.com/{github_repo}/releases/download/"
    f"{resolved_release_tag}/{sbom_asset_name}"
)
release = release_metadata(github_repo, resolved_release_tag, sbom_asset_name)
sbom_asset_digest = release["sbom_asset_digest"]
console_url = join_url(api_url, f"/console?proposal_id={proposal['id']}#proposals")
proposal_event = find_required_event(
    list(events),
    "proposal_created",
    f"proposal_created for {proposal['id']}",
    lambda payload: payload.get("id") == proposal["id"],
)
intent_id = proposal.get("intent_id")
if not isinstance(intent_id, str) or not intent_id:
    fail(f"proposal {proposal['id']} is missing intent_id")
intent_event = find_required_event(
    list(events),
    "intent_created",
    f"intent_created for {intent_id}",
    lambda payload: payload.get("id") == intent_id,
)
evidence_refs = {str(ref) for ref in proposal.get("evidence_refs", [])}
finding_events = find_matching_events(
    list(events),
    "finding_created",
    lambda payload: payload.get("id") in evidence_refs
    or payload.get("intent_id") == intent_id,
)
if not finding_events:
    fail(f"proposal {proposal['id']} has no finding evidence")

released_digest = execution.get("result", {}).get("released_image_digest")
image_push_events = find_matching_events(
    list(events),
    "image_push_completed",
    lambda payload: payload.get("id") in evidence_refs
    or payload.get("prod_digest") == released_digest,
)
if not image_push_events:
    fail(f"proposal {proposal['id']} has no image_push_completed evidence")

policy_event = find_required_event(
    list(events),
    "policy_evaluated",
    f"policy_evaluated for {proposal['id']}",
    lambda payload: payload.get("proposal_id") == proposal["id"],
)
vote_events = find_matching_events(
    list(events),
    "proposal_voted",
    lambda payload: payload.get("proposal_id") == proposal["id"],
)
if not vote_events:
    fail(f"proposal {proposal['id']} has no vote events")

human_approval_events = [
    event
    for event in list(events)
    if event.get("event_type")
    in {"human_approval_requested", "human_approval_granted", "human_approval_denied"}
    and isinstance(event.get("payload"), dict)
    and event["payload"].get("proposal_id") == proposal["id"]
]
if not human_approval_events:
    fail(f"proposal {proposal['id']} has no human approval events")

execution_started_event = find_required_event(
    list(events),
    "execution_started",
    f"execution_started for {proposal['id']}",
    lambda payload: payload.get("proposal_id") == proposal["id"],
)
health_check_ids = [str(check.get("id")) for check in health_checks if check.get("id")]
health_check_events = find_matching_events(
    list(events),
    "health_check_completed",
    lambda payload: payload.get("proposal_id") == proposal["id"]
    and payload.get("id") in health_check_ids,
)
if len(health_check_events) != len(set(health_check_ids)):
    fail(f"proposal {proposal['id']} is missing health_check_completed events")

provenance = {
    "release": release,
    "proposal_event_id": proposal_event["id"],
    "intent_id": intent_id,
    "intent_event_id": intent_event["id"],
    "finding_ids": [event_payload_id(event) for event in finding_events],
    "finding_event_ids": [str(event["id"]) for event in finding_events],
    "image_push_ids": [event_payload_id(event) for event in image_push_events],
    "image_push_event_ids": [str(event["id"]) for event in image_push_events],
    "policy_decision_event_id": policy_event["id"],
    "policy_decision": policy_event["payload"],
    "vote_ids": [event_payload_id(event) for event in vote_events],
    "vote_event_ids": [str(event["id"]) for event in vote_events],
    "human_approval_ids": [event_payload_id(event) for event in human_approval_events],
    "human_approval_event_ids": [str(event["id"]) for event in human_approval_events],
    "execution_started_id": event_payload_id(execution_started_event),
    "execution_started_event_id": execution_started_event["id"],
    "execution_succeeded_id": execution["id"],
    "execution_succeeded_event_id": execution_event["id"],
    "health_check_ids": list(health_check_ids),
    "health_check_event_ids": [str(event["id"]) for event in health_check_events],
}
proof = {
    "captured_at": captured_at,
    "api": api_url,
    "prod_url": prod_url,
    "release_tag": resolved_release_tag,
    "github_repo": github_repo,
    "release_url": release_url,
    "sbom_asset_name": sbom_asset_name,
    "sbom_asset_url": sbom_asset_url,
    "sbom_asset_digest": sbom_asset_digest,
    "console_url": console_url,
    "proposal_id": proposal["id"],
    "proposal_event_id": provenance["proposal_event_id"],
    "intent_id": intent_id,
    "intent_event_id": provenance["intent_event_id"],
    "execution_id": execution["id"],
    "execution_started_event_id": provenance["execution_started_event_id"],
    "execution_succeeded_event_id": execution_event["id"],
    "staging_root": staging_root,
    "prod_root": prod_root,
    "staging_event_chain": verify,
    "event_chain_event_count": verify.get("event_count"),
    "event_chain_last_hash": verify.get("last_hash"),
    "prod_readiness": prod_readiness,
    "prod_health": prod_health,
    "proposal": proposal,
    "execution": execution,
    "health_checks": health_checks,
    "provenance": provenance,
}

Path(proof_json_path).write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")

summary = [
    "# Quorum Operator Proof",
    "",
    f"- Captured: `{captured_at}`",
    f"- Release: `{proof['release_tag']}`",
    f"- Release URL: {release_url}",
    f"- Expected SBOM asset: `{sbom_asset_name}`",
    f"- Expected SBOM URL: {sbom_asset_url}",
    f"- SBOM asset digest: `{sbom_asset_digest}`",
    f"- Staging API: `{api_url}`",
    f"- Prod URL: `{prod_url}`",
    f"- Console deep link: {console_url}",
    f"- Event chain: `ok=true`, count `{verify.get('event_count')}`, last hash `{verify.get('last_hash')}`",
    f"- Proposal: `{proposal['id']}` event `{provenance['proposal_event_id']}` by `{proposal['agent_id']}` targeting `{proposal['target']}`",
    f"- Intent: `{intent_id}` event `{provenance['intent_event_id']}`",
    f"- Findings: `{', '.join(provenance['finding_ids'])}` events `{', '.join(provenance['finding_event_ids'])}`",
    f"- Image pushes: `{', '.join(provenance['image_push_ids'])}` events `{', '.join(provenance['image_push_event_ids'])}`",
    f"- Policy decision event: `{provenance['policy_decision_event_id']}`",
    f"- Votes: `{', '.join(provenance['vote_ids'])}` events `{', '.join(provenance['vote_event_ids'])}`",
    f"- Human approvals: `{', '.join(provenance['human_approval_ids'])}` events `{', '.join(provenance['human_approval_event_ids'])}`",
    f"- Execution: `{execution['id']}` status `{execution['status']}`",
    f"- Execution start event: `{provenance['execution_started_event_id']}`",
    f"- Execution success event: `{execution_event['id']}`",
    "- Prod checks: `readiness ok=true`, `api health ok=true`",
    "",
    "## Health Checks",
]
event_by_health_id = {
    event_payload_id(event): str(event["id"])
    for event in health_check_events
}
for check in health_checks:
    check_id = str(check.get("id"))
    summary.append(
        f"- `{check.get('name')}` id=`{check_id}` event=`{event_by_health_id.get(check_id, '')}` "
        f"passed=`{check.get('passed')}` detail=`{check.get('detail', '')}`"
    )
Path(proof_md_path).write_text("\n".join(summary) + "\n")

print(f"proof.json: {proof_json_path}")
print(f"proof.md: {proof_md_path}")
PY
