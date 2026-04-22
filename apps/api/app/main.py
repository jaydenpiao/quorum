from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

import structlog
from pydantic import ValidationError

from apps.api.app.api.history import router as history_router
from apps.api.app.api.routes import router
from apps.api.app.logging_config import configure_logging
from apps.api.app.middleware import SecurityHeadersMiddleware
from apps.api.app.request_context import RequestContextMiddleware
from apps.api.app.db.engine import make_engine
from apps.api.app.services.actuators.github import (
    GitHubAppAuthError,
    GitHubAppClient,
    load_github_config,
)
from apps.api.app.services.event_log import EventLog, EventLogTamperError
from apps.api.app.services.executor import Executor
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.postgres_projector import PostgresProjector
from apps.api.app.services.projector import NoOpProjector, Projector
from apps.api.app.services.quorum_engine import QuorumEngine
from apps.api.app.services.state_store import StateStore
from apps.api.app.tracing import configure_tracing

configure_logging()
_log = structlog.get_logger(__name__)


def _build_github_client() -> GitHubAppClient | None:
    """Return a GitHub App client iff config/github.yaml + env key are ready.

    The actuator stays disabled (returns None) on any of:
      - config/github.yaml missing or invalid
      - app_id placeholder (validation rejects app_id == 0)
      - private key env var unset or unreadable
    Each of these is an expected state on deploys that have not enabled
    the GitHub actuator, so we log at INFO and continue. Hard failures
    would turn a configurable feature into a deployment blocker.
    """
    try:
        cfg = load_github_config("config/github.yaml")
    except FileNotFoundError:
        _log.info("github_actuator_disabled", reason="config/github.yaml not found")
        return None
    except ValidationError as exc:
        _log.info("github_actuator_disabled", reason=f"config invalid: {exc.error_count()} errors")
        return None

    try:
        return GitHubAppClient(cfg)
    except GitHubAppAuthError as exc:
        _log.info("github_actuator_disabled", reason=str(exc))
        return None


def load_yaml(path: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(Path(path).read_text(encoding="utf-8")))


system_config = load_yaml("config/system.yaml")
http_config = system_config.get("http", {})
default_rate = http_config.get("rate_limit_default", "120/minute")
cors_origins = http_config.get(
    "cors_allowed_origins", ["http://127.0.0.1:8080", "http://localhost:8080"]
)

limiter = Limiter(key_func=get_remote_address, default_limits=[default_rate])

app = FastAPI(title="Quorum Control Plane", version="0.1.0")
app.state.limiter = limiter

# OpenTelemetry tracing — no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
# Must be called before middleware registration so the instrumentor wraps
# the full middleware stack.
configure_tracing(app)

app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)
# RequestContextMiddleware last so it's installed first in the chain:
# its contextvars (request_id, method, path) are bound before any other
# middleware runs and stay available for downstream loggers.
app.add_middleware(RequestContextMiddleware)

# Prometheus metrics — public, no auth, excluded from rate-limit accounting.
# Must come after all add_middleware() calls so the /metrics route is
# registered after SlowAPIMiddleware and therefore not subject to rate limits.
# excluded_handlers=["/metrics"] prevents self-scrape hits from polluting
# the http_requests_total counter.
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics"],
).instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False,
    should_gzip=True,
)


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"rate limit exceeded: {exc.detail}"},
    )


_pg_engine = make_engine()
_projector: Projector = PostgresProjector(_pg_engine) if _pg_engine is not None else NoOpProjector()
event_log = EventLog(system_config["app"]["log_path"], projector=_projector)
# Fail loudly if the persisted log has been modified outside EventLog.
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
github_client = _build_github_client()
executor = Executor(event_log, policy_engine, github_client=github_client)

app.state.event_log = event_log
app.state.policy_engine = policy_engine
app.state.quorum_engine = quorum_engine
app.state.state_store = state_store
app.state.executor = executor
app.state.github_client = github_client
# Engine is None when DATABASE_URL is unset — history endpoints return 503 in that mode.
app.state.pg_engine = _pg_engine

app.include_router(router)
app.include_router(history_router)
app.mount("/console-static", StaticFiles(directory="apps/console"), name="console-static")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "quorum-control-plane",
        "docs": "/docs",
        "console": "/console",
        "api_base": "/api/v1",
    }


@app.get("/health")
def liveness() -> dict[str, bool]:
    """Liveness probe — does not touch the event log."""
    return {"ok": True}


@app.get("/console")
def console() -> FileResponse:
    return FileResponse("apps/console/index.html")
