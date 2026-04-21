#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="${1:-Quorum}"

if command -v gh >/dev/null 2>&1; then
  if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
    echo "GitHub repo '$REPO_NAME' already exists or is already accessible."
  else
    gh repo create "$REPO_NAME" --public --source . --remote origin --push
    echo "Created and pushed to GitHub via gh CLI."
  fi
  exit 0
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Neither gh CLI nor GITHUB_TOKEN is available."
  echo "Set GITHUB_TOKEN with repo scope or install/authenticate gh."
  exit 1
fi

OWNER="${GITHUB_OWNER:-$(git config github.user || true)}"
if [ -z "${OWNER}" ]; then
  echo "Set GITHUB_OWNER when using token mode."
  exit 1
fi

curl -sS -X POST \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/user/repos \
  -d "{\"name\": \"${REPO_NAME}\", \"private\": false}"

git remote remove origin 2>/dev/null || true
git remote add origin "git@github.com:${OWNER}/${REPO_NAME}.git"
git push -u origin main

echo "Created and pushed to GitHub via REST API."
