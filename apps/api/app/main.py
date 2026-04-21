from __future__ import annotations

from pathlib import Path
import yaml

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.app.api.routes import router
from apps.api.app.services.event_log import EventLog, EventLogTamperError
from apps.api.app.services.executor import Executor
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.quorum_engine import QuorumEngine
from apps.api.app.services.state_store import StateStore


def load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


system_config = load_yaml("config/system.yaml")
app = FastAPI(title="Quorum Control Plane", version="0.1.0")

event_log = EventLog(system_config["app"]["log_path"])
# Fail loudly if the persisted log has been modified outside EventLog.
# A broken chain means the product's audit-trail promise is broken.
try:
    event_log.verify()
except EventLogTamperError as _tamper:  # pragma: no cover — exercised via integration
    raise RuntimeError(
        f"Event log integrity check failed: {_tamper}. "
        "The log must be restored from backup or explicitly reset "
        "(see SECURITY.md for incident response)."
    ) from _tamper
policy_engine = PolicyEngine("config/policies.yaml")
quorum_engine = QuorumEngine()
state_store = StateStore()
executor = Executor(event_log, policy_engine)

app.state.event_log = event_log
app.state.policy_engine = policy_engine
app.state.quorum_engine = quorum_engine
app.state.state_store = state_store
app.state.executor = executor

app.include_router(router)
app.mount("/console-static", StaticFiles(directory="apps/console"), name="console-static")


@app.get("/")
def root() -> dict:
    return {
        "service": "quorum-control-plane",
        "docs": "/docs",
        "console": "/console",
        "api_base": "/api/v1",
    }


@app.get("/console")
def console() -> FileResponse:
    return FileResponse("apps/console/index.html")
