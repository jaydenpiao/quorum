#!/usr/bin/env bash
set -euo pipefail

if [ ! -d .git ]; then
  git init -b main
fi

git add .
if ! git diff --cached --quiet; then
  git commit -m "chore: bootstrap Quorum POC"
else
  echo "No staged changes to commit."
fi
