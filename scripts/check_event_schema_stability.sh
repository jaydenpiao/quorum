#!/usr/bin/env bash
set -euo pipefail

ANCHOR_TAG="${QUORUM_SCHEMA_STABILITY_ANCHOR_TAG:-v0.6.3}"
BASE_REF="${QUORUM_SCHEMA_STABILITY_BASE_REF:-HEAD}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quorum-schema-stability.XXXXXX")"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

closed() {
  printf "schema-stability-failed: %s\n" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || closed "missing required command: $1"
}

require_command git

cd "$ROOT_DIR"

git rev-parse --verify --quiet "$ANCHOR_TAG^{commit}" >/dev/null || \
  closed "missing schema stability anchor: $ANCHOR_TAG"
git rev-parse --verify --quiet "$BASE_REF^{commit}" >/dev/null || \
  closed "missing schema stability base ref: $BASE_REF"

CHANGED="$TMP_DIR/changed-schema-files.txt"

git diff --name-only "$ANCHOR_TAG..$BASE_REF" -- \
  apps/api/app/domain/models.py \
  apps/api/app/services/event_log.py \
  apps/api/app/services/state_store.py \
  apps/api/app/services/postgres_projector.py \
  apps/api/app/db/models.py \
  alembic/versions \
  examples \
  >"$CHANGED"

if [[ -s "$CHANGED" ]]; then
  printf "schema-stability-failed: schema-sensitive files changed since %s\n" "$ANCHOR_TAG" >&2
  sed 's/^/schema-stability-changed: /' "$CHANGED" >&2
  exit 1
fi

printf "schema-stability-ok: anchor=%s base=%s\n" "$ANCHOR_TAG" "$BASE_REF"
