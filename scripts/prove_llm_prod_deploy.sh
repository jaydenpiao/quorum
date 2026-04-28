#!/usr/bin/env bash
set -euo pipefail

API="${QUORUM_PROOF_API:-https://quorum-staging.fly.dev}"
CURSOR_DIR="${QUORUM_PROOF_CURSOR_DIR:-$(mktemp -d /tmp/quorum-llm-prod-proof.XXXXXX)}"
POLL_SECONDS="${QUORUM_PROOF_POLL_SECONDS:-900}"
POLL_INTERVAL_SECONDS="${QUORUM_PROOF_POLL_INTERVAL_SECONDS:-15}"
EXECUTE="${QUORUM_PROOF_EXECUTE:-0}"
EXPECT_GUARD="${QUORUM_PROOF_EXPECT_GUARD:-0}"
STAGING_EVIDENCE="${QUORUM_PROOF_STAGING_EVIDENCE:-quorum-execution}"
DEPLOY_STAGING="${QUORUM_PROOF_DEPLOY_STAGING:-0}"
FLY_BINARY="${QUORUM_PROOF_FLY_BINARY:-${QUORUM_FLY_BINARY:-fly}}"

OPERATOR_KEY="${QUORUM_PROOF_OPERATOR_KEY:-}"
CODE_AGENT_KEY="${QUORUM_PROOF_CODE_AGENT_KEY:-}"
DEPLOY_AGENT_KEY="${QUORUM_PROOF_DEPLOY_AGENT_KEY:-}"

EVENTS_FILE="$CURSOR_DIR/events.json"
WINDOW_FILE="$CURSOR_DIR/proof-window.json"
PROPOSAL_FILE="$CURSOR_DIR/proposal-proof.json"
EXECUTION_FILE="$CURSOR_DIR/execution-proof.json"
GUARD_FILE="$CURSOR_DIR/guard-proof.json"
STAGING_FINDING_FILE="$CURSOR_DIR/external-staging-finding.json"
CURSOR_FILE="$CURSOR_DIR/deploy-llm-agent.json"

die() {
  printf "error: %s\n" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

require_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || die "set $name before running this proof"
}

auth_header() {
  printf "Authorization: Bearer %s" "$1"
}

api_get() {
  curl -fsS "$API$1"
}

api_post() {
  local path="$1"
  local token="$2"
  local payload="$3"
  curl -fsS \
    -X POST "$API$path" \
    -H "$(auth_header "$token")" \
    -H "Content-Type: application/json" \
    --data "$payload"
}

refresh_events() {
  api_get "/api/v1/events" >"$EVENTS_FILE"
}

python_events() {
  python3 - "$@" "$EVENTS_FILE" <<'PY'
from __future__ import annotations

import json
import sys


def after_cursor(events: list[dict], cursor: str) -> list[dict]:
    if not cursor:
        return events
    for index, event in enumerate(events):
        if event.get("id") == cursor:
            return events[index + 1 :]
    return events


def latest_cursor(events: list[dict]) -> None:
    print(events[-1]["id"] if events else "")


def latest_image_window(events: list[dict]) -> None:
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.get("event_type") != "image_push_completed":
            continue
        payload = event["payload"]
        cursor = events[index - 1]["id"] if index > 0 else ""
        print(
            json.dumps(
                {
                    "cursor": cursor,
                    "image_push_event_id": event["id"],
                    "image_push_id": payload["id"],
                    "workflow_run_id": payload["workflow_run_id"],
                    "workflow_url": payload["workflow_url"],
                    "staging_digest": payload["staging_digest"],
                    "prod_digest": payload["prod_digest"],
                }
            )
        )
        return
    raise SystemExit("no image_push_completed events found")


def fresh_image_window(events: list[dict], cursor: str) -> None:
    window = after_cursor(events, cursor)
    image_event = next(
        (event for event in reversed(window) if event.get("event_type") == "image_push_completed"),
        None,
    )
    if image_event is None:
        print(
            json.dumps(
                {
                    "ready": False,
                    "reason": "waiting for fresh image_push_completed after scratch cursor",
                }
            )
        )
        return

    payload = image_event["payload"]
    print(
        json.dumps(
            {
                "ready": True,
                "image_push_event_id": image_event["id"],
                "image_push_id": payload["id"],
                "workflow_run_id": payload["workflow_run_id"],
                "workflow_url": payload["workflow_url"],
                "staging_digest": payload["staging_digest"],
                "prod_digest": payload["prod_digest"],
            }
        )
    )


def proof_window(events: list[dict], cursor: str) -> None:
    window = after_cursor(events, cursor)
    image_event = next(
        (event for event in reversed(window) if event.get("event_type") == "image_push_completed"),
        None,
    )
    if image_event is None:
        print(
            json.dumps(
                {
                    "ready": False,
                    "reason": "waiting for fresh image_push_completed after scratch cursor",
                }
            )
        )
        return

    image_payload = image_event["payload"]
    staging_digest = image_payload["staging_digest"]
    proposals: dict[str, dict] = {}
    for event in window:
        if event.get("event_type") == "proposal_created":
            payload = event["payload"]
            proposals[payload["id"]] = payload

    staging_success = None
    for event in window:
        if event.get("event_type") != "execution_succeeded":
            continue
        payload = event["payload"]
        proposal = proposals.get(payload.get("proposal_id", ""))
        if proposal is None:
            continue
        proposal_app = proposal.get("payload", {}).get("app")
        if proposal.get("target") != "quorum-staging" and proposal_app != "quorum-staging":
            continue
        if payload.get("result", {}).get("released_image_digest") != staging_digest:
            continue
        if not all(check.get("passed") is True for check in payload.get("health_checks", [])):
            continue
        staging_success = event

    if staging_success is None:
        print(
            json.dumps(
                {
                    "ready": False,
                    "reason": (
                        "fresh image_push_completed found, but no successful quorum-staging "
                        "execution with matching staging_digest is in the proof window"
                    ),
                    "image_push_event_id": image_event["id"],
                    "image_push_id": image_payload["id"],
                    "staging_digest": staging_digest,
                    "prod_digest": image_payload["prod_digest"],
                }
            )
        )
        return

    staging_payload = staging_success["payload"]
    print(
        json.dumps(
            {
                "ready": True,
                "image_push_event_id": image_event["id"],
                "image_push_id": image_payload["id"],
                "workflow_run_id": image_payload["workflow_run_id"],
                "workflow_url": image_payload["workflow_url"],
                "staging_digest": staging_digest,
                "prod_digest": image_payload["prod_digest"],
                "staging_success_event_id": staging_success["id"],
                "staging_proposal_id": staging_payload["proposal_id"],
                "staging_execution_id": staging_payload["id"],
            }
        )
    )


def verified_prod_proposal(
    events: list[dict],
    cursor: str,
    intent_id: str,
    prod_digest: str,
    image_push_event_id: str,
    image_push_id: str,
    *staging_evidence_values: str,
) -> None:
    window = after_cursor(events, cursor)
    staging_evidence_values = tuple(value for value in staging_evidence_values if value)
    policy_by_proposal = {
        event["payload"]["proposal_id"]: event["payload"]
        for event in window
        if event.get("event_type") == "policy_evaluated"
    }
    for event in reversed(window):
        if event.get("event_type") != "proposal_created":
            continue
        proposal = event["payload"]
        if proposal.get("agent_id") != "deploy-llm-agent":
            continue
        if proposal.get("intent_id") != intent_id:
            continue
        if proposal.get("action_type") != "fly.deploy":
            continue
        if proposal.get("target") != "quorum-prod":
            continue
        if proposal.get("payload", {}).get("app") != "quorum-prod":
            continue
        if proposal.get("payload", {}).get("image_digest") != prod_digest:
            continue

        checks = proposal.get("health_checks", [])
        names = {check.get("name") for check in checks}
        urls = {check.get("url") for check in checks}
        if {"prod-readiness", "prod-api-health"} - names:
            continue
        if "https://quorum-prod.fly.dev/readiness" not in urls:
            continue
        if "https://quorum-prod.fly.dev/api/v1/health" not in urls:
            continue

        evidence = "\n".join(proposal.get("evidence_refs", []))
        image_evidence_ok = image_push_event_id in evidence or image_push_id in evidence
        staging_evidence_ok = any(value in evidence for value in staging_evidence_values)
        if not image_evidence_ok or not staging_evidence_ok:
            continue

        print(
            json.dumps(
                {
                    "proposal_id": proposal["id"],
                    "proposal_event_id": event["id"],
                    "policy_decision": policy_by_proposal.get(proposal["id"], {}),
                    "prod_digest": prod_digest,
                }
            )
        )
        return

    raise SystemExit(
        "no deploy-llm-agent quorum-prod proposal matched the proof contract "
        "(target, digest, health checks, and evidence refs)"
    )


def verified_external_staging_finding(
    events: list[dict],
    cursor: str,
    intent_id: str,
    staging_digest: str,
    fly_platform_digest: str,
    image_push_event_id: str,
    image_push_id: str,
) -> None:
    window = after_cursor(events, cursor)
    for event in reversed(window):
        if event.get("event_type") != "finding_created":
            continue
        finding = event["payload"]
        if finding.get("intent_id") != intent_id:
            continue
        summary = finding.get("summary", "")
        evidence = "\n".join(finding.get("evidence_refs", []))
        if "external_staging_verification" not in summary:
            continue
        if staging_digest not in summary and staging_digest not in evidence:
            continue
        if fly_platform_digest not in evidence:
            continue
        if image_push_event_id not in evidence and image_push_id not in evidence:
            continue
        if "https://quorum-staging.fly.dev/readiness" not in evidence:
            continue
        if "https://quorum-staging.fly.dev/api/v1/health" not in evidence:
            continue
        print(
            json.dumps(
                {
                    "finding_event_id": event["id"],
                    "finding_id": finding["id"],
                    "staging_digest": staging_digest,
                    "fly_platform_digest": fly_platform_digest,
                    "summary": summary,
                    "evidence_refs": finding.get("evidence_refs", []),
                }
            )
        )
        return
    raise SystemExit(
        "no external_staging_verification finding matched the image-push evidence "
        "and staging health proof"
    )


def terminal_prod_execution(events: list[dict], proposal_id: str, prod_digest: str) -> None:
    executions = [
        event
        for event in events
        if event.get("event_type") == "execution_succeeded"
        and event.get("payload", {}).get("proposal_id") == proposal_id
    ]
    if not executions:
        raise SystemExit(f"no execution_succeeded event found for {proposal_id}")
    execution = executions[-1]
    payload = execution["payload"]
    if payload.get("result", {}).get("released_image_digest") != prod_digest:
        raise SystemExit("terminal execution released a different digest than the proof proposal")
    if not all(check.get("passed") is True for check in payload.get("health_checks", [])):
        raise SystemExit("terminal execution did not pass every health check")
    print(
        json.dumps(
            {
                "execution_event_id": execution["id"],
                "execution_id": payload["id"],
                "proposal_id": proposal_id,
                "released_image_digest": prod_digest,
            }
        )
    )


def verified_guard_finding(events: list[dict], cursor: str, intent_id: str) -> None:
    window = after_cursor(events, cursor)
    unexpected_prod_proposals = [
        event
        for event in window
        if event.get("event_type") == "proposal_created"
        and event.get("payload", {}).get("agent_id") == "deploy-llm-agent"
        and event.get("payload", {}).get("intent_id") == intent_id
        and (
            event.get("payload", {}).get("target") == "quorum-prod"
            or event.get("payload", {}).get("payload", {}).get("app") == "quorum-prod"
        )
    ]
    if unexpected_prod_proposals:
        proposal = unexpected_prod_proposals[-1]["payload"]
        raise SystemExit(
            "deploy-llm-agent created an unexpected prod proposal "
            f"{proposal.get('id')} while staging success evidence is missing"
        )

    for event in reversed(window):
        if event.get("event_type") != "finding_created":
            continue
        finding = event["payload"]
        if finding.get("agent_id") != "deploy-llm-agent":
            continue
        if finding.get("intent_id") != intent_id:
            continue
        print(
            json.dumps(
                {
                    "finding_event_id": event["id"],
                    "finding_id": finding["id"],
                    "summary": finding["summary"],
                    "evidence_refs": finding.get("evidence_refs", []),
                }
            )
        )
        return

    raise SystemExit(
        "deploy-llm-agent did not create a guard finding while staging success "
        "evidence is missing"
    )


mode = sys.argv[1]
events_path = sys.argv[-1]
with open(events_path, encoding="utf-8") as handle:
    events = json.load(handle)

if mode == "latest-cursor":
    latest_cursor(events)
elif mode == "latest-image-window":
    latest_image_window(events)
elif mode == "fresh-image-window":
    fresh_image_window(events, sys.argv[2])
elif mode == "proof-window":
    proof_window(events, sys.argv[2])
elif mode == "verified-prod-proposal":
    verified_prod_proposal(
        events,
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5],
        sys.argv[6],
        *sys.argv[7:-1],
    )
elif mode == "terminal-prod-execution":
    terminal_prod_execution(events, sys.argv[2], sys.argv[3])
elif mode == "verified-external-staging-finding":
    verified_external_staging_finding(
        events,
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5],
        sys.argv[6],
        sys.argv[7],
    )
elif mode == "verified-guard-finding":
    verified_guard_finding(events, sys.argv[2], sys.argv[3])
else:
    raise SystemExit(f"unknown mode: {mode}")
PY
}

json_field() {
  local file="$1"
  local key="$2"
  python3 - "$file" "$key" <<'PY'
from __future__ import annotations

import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    current = json.load(handle)
for part in sys.argv[2].split("."):
    current = current[part]
print(current)
PY
}

intent_payload() {
  python3 - <<'PY'
from __future__ import annotations

import json

print(
    json.dumps(
        {
            "title": "Promote verified Quorum image to prod through deploy-llm-agent",
            "description": (
                "Use fresh image-push evidence and successful staging execution "
                "evidence to have deploy-llm-agent propose the gated prod deploy."
            ),
            "environment": "prod",
            "requested_by": "operator",
        }
    )
)
PY
}

vote_payload() {
  local proposal_id="$1"
  local reason="$2"
  python3 - "$proposal_id" "$reason" <<'PY'
from __future__ import annotations

import json
import sys

print(
    json.dumps(
        {
            "proposal_id": sys.argv[1],
            "decision": "approve",
            "reason": sys.argv[2],
        }
    )
)
PY
}

approval_payload() {
  python3 - <<'PY'
from __future__ import annotations

import json

print(
    json.dumps(
        {
            "decision": "granted",
            "reason": (
                "Reviewed deploy-llm-agent proposal, image-push evidence, "
                "staging success evidence, prod health checks, and rollback plan."
            ),
        }
    )
)
PY
}

staging_verification_payload() {
  local intent_id="$1"
  local staging_digest="$2"
  local fly_platform_digest="$3"
  local image_push_event_id="$4"
  local image_push_id="$5"
  local workflow_run_id="$6"
  local workflow_url="$7"
  python3 - "$intent_id" "$staging_digest" "$fly_platform_digest" \
    "$image_push_event_id" "$image_push_id" "$workflow_run_id" "$workflow_url" <<'PY'
from __future__ import annotations

import json
import sys

intent_id = sys.argv[1]
staging_digest = sys.argv[2]
fly_platform_digest = sys.argv[3]
image_push_event_id = sys.argv[4]
image_push_id = sys.argv[5]
workflow_run_id = sys.argv[6]
workflow_url = sys.argv[7]

print(
    json.dumps(
        {
            "intent_id": intent_id,
            "summary": (
                "external_staging_verification passed for quorum-staging "
                f"after requesting image-push manifest {staging_digest}; "
                f"Fly reports platform digest {fly_platform_digest}; staging "
                "/readiness and /api/v1/health returned HTTP 200 before "
                "requesting a prod deploy proposal."
            ),
            "evidence_refs": [
                image_push_event_id,
                image_push_id,
                f"workflow_run:{workflow_run_id}",
                f"workflow_url:{workflow_url}",
                f"staging_digest:{staging_digest}",
                f"fly_platform_digest:{fly_platform_digest}",
                f"external_staging_verification:quorum-staging:{staging_digest}",
                "https://quorum-staging.fly.dev/readiness",
                "https://quorum-staging.fly.dev/api/v1/health",
            ],
            "confidence": 1.0,
        }
    )
)
PY
}

execute_payload() {
  printf '{"actor_id":"operator"}'
}

latest_fly_release_digest() {
  local app="$1"
  "$FLY_BINARY" releases --app "$app" --json | python3 -c '
from __future__ import annotations

import json
import sys

try:
    releases = json.load(sys.stdin)
except json.JSONDecodeError as exc:
    raise SystemExit(f"could not parse fly releases JSON: {exc}") from exc

if not isinstance(releases, list) or not releases:
    raise SystemExit("fly releases returned no releases")

release = releases[0]
if not isinstance(release, dict):
    raise SystemExit("latest fly release is not an object")

for outer_key in ("ImageRef", "imageRef", "image_ref", "image"):
    ref = release.get(outer_key)
    if isinstance(ref, dict):
        for inner_key in ("Digest", "digest"):
            digest = ref.get(inner_key)
            if isinstance(digest, str) and digest.startswith("sha256:"):
                print(digest)
                raise SystemExit(0)
    if isinstance(ref, str) and "@sha256:" in ref:
        print(ref.rsplit("@", 1)[1])
        raise SystemExit(0)

raise SystemExit(f"could not find image digest in latest release: {release!r}")
'
}

verify_staging_health() {
  curl -fsS "https://quorum-staging.fly.dev/readiness" >/dev/null
  curl -fsS "https://quorum-staging.fly.dev/api/v1/health" >/dev/null
}

record_external_staging_verification() {
  local cursor="$1"
  local intent_id="$2"
  local staging_digest="$3"
  local image_push_event_id="$4"
  local image_push_id="$5"
  local workflow_run_id="$6"
  local workflow_url="$7"

  require_command "$FLY_BINARY"
  require_env FLY_API_TOKEN

  local current_digest
  current_digest="$(latest_fly_release_digest quorum-staging)"
  if [[ "$current_digest" != "$staging_digest" ]]; then
    if [[ "$DEPLOY_STAGING" != "1" ]]; then
      die "quorum-staging reports platform digest $current_digest, not literal manifest digest $staging_digest; set QUORUM_PROOF_DEPLOY_STAGING=1 to deploy the requested manifest before recording evidence"
    fi
    printf "\nDeploying quorum-staging to fresh image digest via flyctl.\n"
    "$FLY_BINARY" deploy \
      --app quorum-staging \
      --image "registry.fly.io/quorum-staging@$staging_digest" \
      --strategy rolling \
      --yes
    current_digest="$(latest_fly_release_digest quorum-staging)"
  fi

  printf "Fly-reported platform digest for quorum-staging: %s\n" "$current_digest"

  printf "\nVerifying staging health endpoints before recording external staging evidence.\n"
  verify_staging_health

  api_post "/api/v1/findings" "$OPERATOR_KEY" \
    "$(staging_verification_payload \
      "$intent_id" \
      "$staging_digest" \
      "$current_digest" \
      "$image_push_event_id" \
      "$image_push_id" \
      "$workflow_run_id" \
      "$workflow_url")" >/dev/null

  refresh_events
  python_events verified-external-staging-finding \
    "$cursor" \
    "$intent_id" \
    "$staging_digest" \
    "$current_digest" \
    "$image_push_event_id" \
    "$image_push_id" >"$STAGING_FINDING_FILE"
}

wait_for_image_window() {
  local cursor="$1"
  local deadline
  deadline=$((SECONDS + POLL_SECONDS))
  while true; do
    refresh_events
    python_events fresh-image-window "$cursor" >"$WINDOW_FILE"
    if [[ "$(json_field "$WINDOW_FILE" ready)" == "True" ]]; then
      return 0
    fi
    printf "waiting: %s\n" "$(json_field "$WINDOW_FILE" reason)"
    if (( SECONDS >= deadline )); then
      python3 -m json.tool "$WINDOW_FILE" || true
      die "proof window not ready; trigger image-push on main and rerun after evidence posts"
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
}

wait_for_proof_window() {
  local cursor="$1"
  local deadline
  deadline=$((SECONDS + POLL_SECONDS))
  while true; do
    refresh_events
    python_events proof-window "$cursor" >"$WINDOW_FILE"
    if [[ "$(json_field "$WINDOW_FILE" ready)" == "True" ]]; then
      return 0
    fi
    printf "waiting: %s\n" "$(json_field "$WINDOW_FILE" reason)"
    if (( SECONDS >= deadline )); then
      python3 -m json.tool "$WINDOW_FILE" || true
      die "proof window not ready; trigger image-push on main and make sure staging succeeds"
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
}

run_deploy_agent_once() {
  QUORUM_LLM_CONTROL_PLANE_FLY_APP=quorum-staging \
    uv run --frozen --extra dev --python 3.12 --python-preference only-managed \
      python -m apps.llm_agent.run \
      --agent-id deploy-llm-agent \
      --quorum-url "$API" \
      --cursor-dir "$CURSOR_DIR" \
      --once
}

run_guard_proof() {
  refresh_events
  python_events latest-image-window >"$WINDOW_FILE"
  cursor="$(json_field "$WINDOW_FILE" cursor)"
  printf '{"cursor": "%s"}\n' "$cursor" >"$CURSOR_FILE"

  image_push_event_id="$(json_field "$WINDOW_FILE" image_push_event_id)"
  image_push_id="$(json_field "$WINDOW_FILE" image_push_id)"
  workflow_run_id="$(json_field "$WINDOW_FILE" workflow_run_id)"
  prod_digest="$(json_field "$WINDOW_FILE" prod_digest)"

  printf "guard proof cursor before latest image: %s\n" "${cursor:-<empty-log>}"
  printf "guard proof image evidence: %s / %s / workflow %s\n" \
    "$image_push_event_id" "$image_push_id" "$workflow_run_id"
  printf "guard proof prod digest: %s\n" "$prod_digest"

  intent_json="$(api_post "/api/v1/intents" "$OPERATOR_KEY" "$(intent_payload)")"
  intent_id="$(printf "%s" "$intent_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  printf "created guard intent: %s\n" "$intent_id"

  printf "\nRunning deploy-llm-agent --once to verify it records a finding, not a prod proposal.\n"
  run_deploy_agent_once

  refresh_events
  python_events verified-guard-finding "$cursor" "$intent_id" >"$GUARD_FILE"
  finding_id="$(json_field "$GUARD_FILE" finding_id)"
  printf "verified_guard_finding: %s\n" "$finding_id"
  printf "Guard-only proof complete; staging success evidence is missing, so no prod deploy was proposed.\n"
  printf "Guard proof JSON: %s\n" "$GUARD_FILE"
}

main() {
  require_command curl
  require_command python3
  require_command uv
  require_env ANTHROPIC_API_KEY
  require_env QUORUM_API_KEYS
  case "$STAGING_EVIDENCE" in
    quorum-execution|external-staging-finding) ;;
    *) die "QUORUM_PROOF_STAGING_EVIDENCE must be quorum-execution or external-staging-finding" ;;
  esac
  [[ "$QUORUM_API_KEYS" == *"deploy-llm-agent:"* ]] || die "QUORUM_API_KEYS must include deploy-llm-agent:<key>"
  [[ -n "$OPERATOR_KEY" ]] || die "set QUORUM_PROOF_OPERATOR_KEY for intent creation"

  mkdir -p "$CURSOR_DIR"
  printf "Using Quorum API: %s\n" "$API"
  printf "Using scratch cursor dir: %s\n" "$CURSOR_DIR"
  printf "Using staging evidence mode: %s\n" "$STAGING_EVIDENCE"
  api_get "/readiness" >/dev/null

  if [[ "$EXPECT_GUARD" == "1" ]]; then
    run_guard_proof
    exit 0
  fi

  refresh_events
  cursor="$(python_events latest-cursor)"
  printf '{"cursor": "%s"}\n' "$cursor" >"$CURSOR_FILE"
  printf "captured scratch cursor: %s\n" "${cursor:-<empty-log>}"

  intent_json="$(api_post "/api/v1/intents" "$OPERATOR_KEY" "$(intent_payload)")"
  intent_id="$(printf "%s" "$intent_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  printf "created prod-promotion intent: %s\n" "$intent_id"

  if [[ "$STAGING_EVIDENCE" == "external-staging-finding" ]]; then
    printf "\nWaiting for fresh image_push_completed evidence before external staging verification.\n"
    wait_for_image_window "$cursor"
    staging_digest="$(json_field "$WINDOW_FILE" staging_digest)"
    prod_digest="$(json_field "$WINDOW_FILE" prod_digest)"
    image_push_event_id="$(json_field "$WINDOW_FILE" image_push_event_id)"
    image_push_id="$(json_field "$WINDOW_FILE" image_push_id)"
    workflow_run_id="$(json_field "$WINDOW_FILE" workflow_run_id)"
    workflow_url="$(json_field "$WINDOW_FILE" workflow_url)"

    printf "fresh image evidence: %s / %s\n" "$image_push_event_id" "$image_push_id"
    printf "staging digest for external verification: %s\n" "$staging_digest"
    printf "prod digest for proposal: %s\n" "$prod_digest"

    record_external_staging_verification \
      "$cursor" \
      "$intent_id" \
      "$staging_digest" \
      "$image_push_event_id" \
      "$image_push_id" \
      "$workflow_run_id" \
      "$workflow_url"

    staging_finding_event_id="$(json_field "$STAGING_FINDING_FILE" finding_event_id)"
    staging_finding_id="$(json_field "$STAGING_FINDING_FILE" finding_id)"
    fly_platform_digest="$(json_field "$STAGING_FINDING_FILE" fly_platform_digest)"
    printf "external_staging_verification finding: %s / %s / platform %s\n" \
      "$staging_finding_event_id" "$staging_finding_id" "$fly_platform_digest"
  else
    printf "\nWaiting for fresh image_push_completed and matching quorum-staging success evidence.\n"
    printf "If this times out, trigger the image-push workflow on main and rerun after staging is healthy.\n"
    wait_for_proof_window "$cursor"
    prod_digest="$(json_field "$WINDOW_FILE" prod_digest)"
    image_push_event_id="$(json_field "$WINDOW_FILE" image_push_event_id)"
    image_push_id="$(json_field "$WINDOW_FILE" image_push_id)"
    staging_success_event_id="$(json_field "$WINDOW_FILE" staging_success_event_id)"
    staging_proposal_id="$(json_field "$WINDOW_FILE" staging_proposal_id)"
    staging_execution_id="$(json_field "$WINDOW_FILE" staging_execution_id)"

    printf "fresh image evidence: %s / %s\n" "$image_push_event_id" "$image_push_id"
    printf "staging success evidence: %s / %s / %s\n" \
      "$staging_success_event_id" "$staging_proposal_id" "$staging_execution_id"
    printf "prod digest for proposal: %s\n" "$prod_digest"
  fi

  printf "\nRunning deploy-llm-agent --once against staging.\n"
  run_deploy_agent_once

  refresh_events
  if [[ "$STAGING_EVIDENCE" == "external-staging-finding" ]]; then
    python_events verified-prod-proposal \
      "$cursor" \
      "$intent_id" \
      "$prod_digest" \
      "$image_push_event_id" \
      "$image_push_id" \
      "$staging_finding_event_id" \
      "$staging_finding_id" \
      "external_staging_verification" \
      "staging_digest:$staging_digest" \
      "fly_platform_digest:$fly_platform_digest" >"$PROPOSAL_FILE"
  else
    python_events verified-prod-proposal \
      "$cursor" \
      "$intent_id" \
      "$prod_digest" \
      "$image_push_event_id" \
      "$image_push_id" \
      "$staging_success_event_id" \
      "$staging_proposal_id" \
      "$staging_execution_id" >"$PROPOSAL_FILE"
  fi

  proposal_id="$(json_field "$PROPOSAL_FILE" proposal_id)"
  printf "verified deploy-llm-agent prod proposal: %s\n" "$proposal_id"

  if [[ "$EXECUTE" != "1" ]]; then
    printf "\nProposal proof complete; prod execution was not attempted.\n"
    printf "Set QUORUM_PROOF_EXECUTE=1 with code/deploy/operator keys to vote, approve, execute, and verify.\n"
    printf "Proposal proof JSON: %s\n" "$PROPOSAL_FILE"
    exit 0
  fi

  [[ -n "$CODE_AGENT_KEY" ]] || die "set QUORUM_PROOF_CODE_AGENT_KEY when QUORUM_PROOF_EXECUTE=1"
  [[ -n "$DEPLOY_AGENT_KEY" ]] || die "set QUORUM_PROOF_DEPLOY_AGENT_KEY when QUORUM_PROOF_EXECUTE=1"

  printf "\nQUORUM_PROOF_EXECUTE=1 set; voting, granting human approval, and executing prod deploy.\n"
  api_post "/api/v1/votes" "$CODE_AGENT_KEY" \
    "$(vote_payload "$proposal_id" "prod proposal cites fresh image and staging success evidence")" >/dev/null
  api_post "/api/v1/votes" "$DEPLOY_AGENT_KEY" \
    "$(vote_payload "$proposal_id" "prod health checks and rollback plan reviewed")" >/dev/null
  api_post "/api/v1/approvals/$proposal_id" "$OPERATOR_KEY" "$(approval_payload)" >/dev/null
  api_post "/api/v1/proposals/$proposal_id/execute" "$OPERATOR_KEY" "$(execute_payload)" | python3 -m json.tool

  printf "\nVerifying prod health endpoints.\n"
  curl -fsS "https://quorum-prod.fly.dev/readiness" | python3 -m json.tool
  curl -fsS "https://quorum-prod.fly.dev/api/v1/health" | python3 -m json.tool

  printf "\nVerifying staging event chain.\n"
  api_get "/api/v1/events/verify" | python3 -m json.tool

  refresh_events
  python_events terminal-prod-execution "$proposal_id" "$prod_digest" >"$EXECUTION_FILE"
  printf "terminal prod execution proof: %s\n" "$EXECUTION_FILE"
  python3 -m json.tool "$EXECUTION_FILE"
}

main "$@"
