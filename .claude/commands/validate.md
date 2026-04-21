---
description: Run the canonical green check — ruff check + ruff format --check + pytest
argument-hint: (no args)
---

The single "am I green?" command. Matches `scripts/validate_merge.sh` but faster and scoped to what CI checks.

```bash
set -e
echo "== ruff check =="
ruff check .
echo "== ruff format (check only) =="
ruff format --check .
echo "== pytest =="
pytest -q
echo
echo "All green."
```

If any step fails, stop and fix the root cause before moving on (no `--fix --unsafe-fixes`, no skipping tests).
