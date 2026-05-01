#!/usr/bin/env bash
set -euo pipefail

RELEASE_TAG="${QUORUM_RELEASE_TAG:-v0.6.5}"
STAGING_URL="${QUORUM_STAGING_URL:-https://quorum-staging.fly.dev}"
PROD_URL="${QUORUM_PROD_URL:-https://quorum-prod.fly.dev}"
GITHUB_REPO="${QUORUM_GITHUB_REPO:-jaydenpiao/quorum}"
MAIN_BRANCH="${QUORUM_MAIN_BRANCH:-main}"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quorum-live-release.XXXXXX")"

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

fetch_json() {
  local url="$1"
  local output="$2"
  curl --fail --silent --show-error --retry 2 --retry-delay 2 "$url" >"$output"
}

require_command curl
require_command gh
require_command python3

STAGING_ROOT="$TMP_DIR/staging-root.json"
PROD_ROOT="$TMP_DIR/prod-root.json"
PROD_READINESS="$TMP_DIR/prod-readiness.json"
PROD_HEALTH="$TMP_DIR/prod-health.json"
STAGING_VERIFY="$TMP_DIR/staging-events-verify.json"
RELEASE_JSON="$TMP_DIR/release.json"

fetch_json "$STAGING_URL/" "$STAGING_ROOT"
fetch_json "$PROD_URL/" "$PROD_ROOT"
fetch_json "$PROD_URL/readiness" "$PROD_READINESS"
fetch_json "$PROD_URL/api/v1/health" "$PROD_HEALTH"
fetch_json "$STAGING_URL/api/v1/events/verify" "$STAGING_VERIFY"

python3 - \
  "$RELEASE_TAG" \
  "$STAGING_ROOT" \
  "$PROD_ROOT" \
  "$PROD_READINESS" \
  "$PROD_HEALTH" \
  "$STAGING_VERIFY" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

release_tag, staging_root, prod_root, prod_readiness, prod_health, staging_verify = sys.argv[1:]


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        fail(f"{path} did not return a JSON object")
    return payload


def require_display_version(path: str, label: str) -> None:
    payload = load(path)
    if payload.get("display_version") != release_tag:
        fail(
            f"{label} display_version drift: expected {release_tag!r}, "
            f"got {payload.get('display_version')!r}"
        )


def require_ok(path: str, label: str) -> None:
    payload = load(path)
    if payload.get("ok") is not True:
        fail(f"{label} must return ok=true")


require_display_version(staging_root, "staging root")
require_display_version(prod_root, "prod root")
require_ok(prod_readiness, "prod /readiness")
require_ok(prod_health, "prod /api/v1/health")
require_ok(staging_verify, "staging /api/v1/events/verify")
PY

EXPECTED_ASSET="quorum-${RELEASE_TAG}.spdx.json"
gh release view "$RELEASE_TAG" \
  --repo "$GITHUB_REPO" \
  --json tagName,isDraft,assets \
  >"$RELEASE_JSON"

python3 - "$RELEASE_JSON" "$RELEASE_TAG" "$EXPECTED_ASSET" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

release_path, expected_tag, expected_asset = sys.argv[1:]
release = json.loads(Path(release_path).read_text(encoding="utf-8"))

if release.get("tagName") != expected_tag:
    raise SystemExit(
        f"error: GitHub release tag drift: expected {expected_tag!r}, "
        f"got {release.get('tagName')!r}"
    )
if release.get("isDraft") is True:
    raise SystemExit("error: GitHub release is still a draft")

assets = {asset.get("name") for asset in release.get("assets", []) if isinstance(asset, dict)}
if expected_asset not in assets:
    raise SystemExit(f"error: missing release SBOM asset {expected_asset!r}")
PY

check_latest_workflow() {
  local workflow="$1"
  local label="$2"
  local output="$TMP_DIR/${label}-run.json"

  gh run list \
    --repo "$GITHUB_REPO" \
    --workflow "$workflow" \
    --branch "$MAIN_BRANCH" \
    --limit 1 \
    --json databaseId,status,conclusion,headSha,url,createdAt \
    >"$output"

  python3 - "$output" "$label" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path, label = sys.argv[1:]
runs = json.loads(Path(path).read_text(encoding="utf-8"))
if not runs:
    raise SystemExit(f"error: no {label} runs found")

run = runs[0]
if run.get("status") != "completed" or run.get("conclusion") != "success":
    raise SystemExit(
        f"error: latest {label} run is not completed/success: "
        f"status={run.get('status')!r} conclusion={run.get('conclusion')!r} "
        f"url={run.get('url')!r}"
    )
PY
}

check_latest_workflow "ci.yml" "ci"
check_latest_workflow "security.yml" "security"
# The Quorum evidence notifier inside image-push is best-effort; this
# monitor only requires the image supply workflow itself to be green.
check_latest_workflow "image-push.yml" "image-push"

printf "live-release-ok: %s staging=%s prod=%s repo=%s main=%s\n" \
  "$RELEASE_TAG" "$STAGING_URL" "$PROD_URL" "$GITHUB_REPO" "$MAIN_BRANCH"
