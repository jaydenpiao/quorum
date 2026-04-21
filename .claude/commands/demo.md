---
description: Seed a demo incident against the running Quorum dev server
argument-hint: (no args)
---

POST `/api/v1/demo/incident` and show the resulting state summary. Requires `make dev` running (port 8080).

```bash
set -e
if ! curl -sf http://127.0.0.1:8080/health > /dev/null 2>&1; then
  echo "Dev server is not running. Start it with \`make dev\` in another terminal, then retry /demo."
  exit 1
fi
curl -sX POST http://127.0.0.1:8080/api/v1/demo/incident | python3 -m json.tool
echo
echo "State snapshot:"
curl -s http://127.0.0.1:8080/api/v1/state | python3 -m json.tool | head -40
```
