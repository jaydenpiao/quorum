#!/usr/bin/env bash
set -euo pipefail

RELEASE_TAG="${QUORUM_RELEASE_TAG:-v0.6.5}"
NOT_BEFORE="${QUORUM_PHASE6_NOT_BEFORE:-2026-05-14}"
TODAY="${QUORUM_PHASE6_TODAY:-$(date -u +%F)}"
GITHUB_REPO="${QUORUM_GITHUB_REPO:-jaydenpiao/quorum}"
MAIN_BRANCH="${QUORUM_MAIN_BRANCH:-main}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quorum-phase6-gate.XXXXXX")"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

closed() {
  printf "phase6-gate-closed: %s\n" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || closed "missing required command: $1"
}

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
    raise SystemExit(f"phase6-gate-closed: no {label} runs found")

run = runs[0]
if run.get("status") != "completed" or run.get("conclusion") != "success":
    raise SystemExit(
        f"phase6-gate-closed: latest {label} run is not completed/success: "
        f"status={run.get('status')!r} conclusion={run.get('conclusion')!r} "
        f"url={run.get('url')!r}"
    )
print(
    f"phase6-gate-check: {label} ok "
    f"run={run.get('databaseId')} sha={run.get('headSha')} url={run.get('url')}"
)
PY
}

if [[ "$TODAY" < "$NOT_BEFORE" ]]; then
  printf "phase6-gate-closed: not before %s (today=%s)\n" "$NOT_BEFORE" "$TODAY" >&2
  exit 1
fi

require_command gh
require_command python3

printf "phase6-gate-check: calendar ok today=%s not_before=%s\n" "$TODAY" "$NOT_BEFORE"

LIVE_OUT="$TMP_DIR/live-release.out"
LIVE_ERR="$TMP_DIR/live-release.err"
if ! (
  cd "$ROOT_DIR"
  QUORUM_RELEASE_TAG="$RELEASE_TAG" \
    QUORUM_GITHUB_REPO="$GITHUB_REPO" \
    QUORUM_MAIN_BRANCH="$MAIN_BRANCH" \
    scripts/check_live_release.sh
) >"$LIVE_OUT" 2>"$LIVE_ERR"; then
  if [[ -s "$LIVE_ERR" ]]; then
    sed 's/^/live-release-monitor: /' "$LIVE_ERR" >&2
  fi
  if [[ -s "$LIVE_OUT" ]]; then
    sed 's/^/live-release-monitor: /' "$LIVE_OUT" >&2
  fi
  closed "scripts/check_live_release.sh failed for $RELEASE_TAG"
fi
if ! grep -q "live-release-ok" "$LIVE_OUT"; then
  closed "scripts/check_live_release.sh did not print live-release-ok"
fi
sed 's/^/live-release-monitor: /' "$LIVE_OUT"

check_latest_workflow "live-release-monitor.yml" "live-release-monitor"
check_latest_workflow "ci.yml" "ci"
check_latest_workflow "security.yml" "security"
check_latest_workflow "image-push.yml" "image-push"

OPEN_PRS="$TMP_DIR/open-prs.json"
gh pr list \
  --repo "$GITHUB_REPO" \
  --state open \
  --json number,title,headRefName,url \
  >"$OPEN_PRS"
python3 - "$OPEN_PRS" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

prs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if prs:
    details = ", ".join(f"#{item.get('number')} {item.get('headRefName')}" for item in prs)
    raise SystemExit(f"phase6-gate-closed: open PRs remain: {details}")
print("phase6-gate-check: open-prs ok count=0")
PY

PROOF_DOC_REL="docs/releases/${RELEASE_TAG}-proof.md"
PROOF_DOC="$ROOT_DIR/$PROOF_DOC_REL"
HANDOFF="$ROOT_DIR/docs/SESSION_HANDOFF.md"
[[ -f "$PROOF_DOC" ]] || closed "missing release proof archive: $PROOF_DOC_REL"
grep -Fq "$RELEASE_TAG" "$PROOF_DOC" || closed "$PROOF_DOC_REL does not mention $RELEASE_TAG"
grep -Fq "quorum-${RELEASE_TAG}.spdx.json" "$PROOF_DOC" || \
  closed "$PROOF_DOC_REL does not mention expected SBOM asset"
grep -Fq "$PROOF_DOC_REL" "$HANDOFF" || \
  closed "docs/SESSION_HANDOFF.md does not point to $PROOF_DOC_REL"
grep -Fq "$RELEASE_TAG" "$HANDOFF" || \
  closed "docs/SESSION_HANDOFF.md does not mention $RELEASE_TAG"
printf "phase6-gate-check: proof archive ok path=%s\n" "$PROOF_DOC_REL"

printf "phase6-gate-ready: %s release=%s repo=%s main=%s\n" \
  "$TODAY" "$RELEASE_TAG" "$GITHUB_REPO" "$MAIN_BRANCH"
