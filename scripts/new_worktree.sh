#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:?usage: ./scripts/new_worktree.sh agent/backend/my-task}"
BASE_DIR="../quorum-worktrees"
TARGET_DIR="${BASE_DIR}/${BRANCH//\//-}"

mkdir -p "${BASE_DIR}"

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git worktree add "${TARGET_DIR}" "${BRANCH}"
else
  git worktree add -b "${BRANCH}" "${TARGET_DIR}" main
fi

echo "Created worktree at ${TARGET_DIR}"
