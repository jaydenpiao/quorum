---
description: Start the Quorum dev server (uvicorn, port 8080, auto-reload)
argument-hint: (no args)
---

Launches the FastAPI app via uvicorn. Keep this running in a dedicated terminal — `/demo`, `/validate`, and API smoke tests assume it's up.

```bash
set -e
if curl -sf http://127.0.0.1:8080/health > /dev/null 2>&1; then
  echo "Dev server is already running on port 8080. Console: http://127.0.0.1:8080/console"
  exit 0
fi
echo "Starting dev server on http://127.0.0.1:8080 (reload enabled)..."
echo "Console: http://127.0.0.1:8080/console"
echo "Ctrl+C to stop."
exec make dev
```
