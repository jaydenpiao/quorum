#!/usr/bin/env bash
set -euo pipefail

RELEASE_TAG="${QUORUM_RELEASE_TAG:-v0.6.6}"
GITHUB_REPO="${QUORUM_GITHUB_REPO:-jaydenpiao/quorum}"
PROOF_DOC="${QUORUM_RELEASE_PROOF_DOC:-docs/releases/${RELEASE_TAG}-proof.md}"
MAIN_BRANCH="${QUORUM_MAIN_BRANCH:-main}"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quorum-release-proof-archive.XXXXXX")"

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

require_command gh
require_command git
require_command python3

[[ -f "$PROOF_DOC" ]] || die "missing release proof archive: $PROOF_DOC"
[[ -f "docs/SESSION_HANDOFF.md" ]] || die "missing docs/SESSION_HANDOFF.md"
[[ -f "docs/REPO_MAP.md" ]] || die "missing docs/REPO_MAP.md"
[[ -x "scripts/check_live_release.sh" ]] || die "missing scripts/check_live_release.sh"

TAG_TYPE="$(git cat-file -t "$RELEASE_TAG" 2>/dev/null || true)"
[[ "$TAG_TYPE" == "tag" ]] || die "$RELEASE_TAG must be an annotated signed tag"

TAG_OBJECT="$(git rev-parse "${RELEASE_TAG}^{tag}")"
TAGGED_COMMIT="$(git rev-parse "${RELEASE_TAG}^{commit}")"
TAG_CONTENT_FILE="$TMP_DIR/tag.txt"
RELEASE_JSON="$TMP_DIR/release.json"
LIVE_MONITOR="$TMP_DIR/live-monitor.txt"

git cat-file tag "$RELEASE_TAG" >"$TAG_CONTENT_FILE"
if ! grep -Eq -- '-----BEGIN (PGP|SSH) SIGNATURE-----' "$TAG_CONTENT_FILE"; then
  die "$RELEASE_TAG tag object does not contain a signature block"
fi

gh release view "$RELEASE_TAG" \
  --repo "$GITHUB_REPO" \
  --json tagName,isDraft,url,assets \
  >"$RELEASE_JSON"

QUORUM_RELEASE_TAG="$RELEASE_TAG" \
  QUORUM_GITHUB_REPO="$GITHUB_REPO" \
  QUORUM_MAIN_BRANCH="$MAIN_BRANCH" \
  scripts/check_live_release.sh >"$LIVE_MONITOR"

python3 - \
  "$RELEASE_TAG" \
  "$GITHUB_REPO" \
  "$PROOF_DOC" \
  "docs/SESSION_HANDOFF.md" \
  "docs/REPO_MAP.md" \
  "$RELEASE_JSON" \
  "$TAG_OBJECT" \
  "$TAGGED_COMMIT" \
  "$LIVE_MONITOR" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

(
    release_tag,
    github_repo,
    proof_doc_path,
    handoff_path,
    repo_map_path,
    release_json_path,
    tag_object,
    tagged_commit,
    live_monitor_path,
) = sys.argv[1:]


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def require_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        fail(f"{label} missing {needle!r}")


def load_release(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        fail("GitHub release metadata did not return a JSON object")
    return payload


proof_doc = Path(proof_doc_path)
proof_text = proof_doc.read_text(encoding="utf-8")
handoff_text = Path(handoff_path).read_text(encoding="utf-8")
repo_map_text = Path(repo_map_path).read_text(encoding="utf-8")
live_monitor_text = Path(live_monitor_path).read_text(encoding="utf-8")
release = load_release(release_json_path)

if release.get("tagName") != release_tag:
    fail(f"GitHub release tag drift: expected {release_tag!r}, got {release.get('tagName')!r}")
if release.get("isDraft") is True:
    fail("GitHub release is still a draft")

release_url = f"https://github.com/{github_repo}/releases/tag/{release_tag}"
if release.get("url") != release_url:
    fail(f"GitHub release URL drift: expected {release_url!r}, got {release.get('url')!r}")

expected_asset_name = f"quorum-{release_tag}.spdx.json"
assets = [asset for asset in release.get("assets", []) if isinstance(asset, dict)]
asset = next((item for item in assets if item.get("name") == expected_asset_name), None)
if asset is None:
    fail(f"missing GitHub release SBOM asset {expected_asset_name!r}")

asset_url = f"https://github.com/{github_repo}/releases/download/{release_tag}/{expected_asset_name}"
if asset.get("url") != asset_url:
    fail(f"SBOM asset URL drift: expected {asset_url!r}, got {asset.get('url')!r}")
asset_digest = asset.get("digest")
if not isinstance(asset_digest, str) or not asset_digest.startswith("sha256:"):
    fail("SBOM asset is missing SHA256 digest")

proof_rel = proof_doc_path
for needle, label in (
    (release_tag, "proof archive"),
    (release_url, "proof archive"),
    (expected_asset_name, "proof archive"),
    (asset_url, "proof archive"),
    (asset_digest, "proof archive"),
    (tag_object, "proof archive"),
    (tagged_commit, "proof archive"),
):
    require_contains(proof_text, needle, label)

require_contains(handoff_text, proof_rel, "session handoff")
require_contains(handoff_text, release_tag, "session handoff")
require_contains(handoff_text, asset_digest, "session handoff")
require_contains(repo_map_text, proof_rel, "repo map")
require_contains(repo_map_text, release_tag, "repo map")

if "live-release-ok" not in live_monitor_text:
    fail("scripts/check_live_release.sh did not print live-release-ok")
require_contains(live_monitor_text, release_tag, "live monitor output")

print(f"release-proof-archive-ok: {release_tag} proof={proof_rel}")
PY
