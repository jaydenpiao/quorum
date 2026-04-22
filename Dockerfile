# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1: builder
# Install uv, sync the locked virtualenv, then copy source in.
# =============================================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv via pip — version pinned in uv.lock; this just bootstraps it.
RUN pip install --no-cache-dir uv

# Copy dependency manifests first so Docker can cache the sync layer.
COPY pyproject.toml uv.lock ./

# Install only production dependencies into /app/.venv.
# --frozen: refuse to update uv.lock; --no-dev: skip test / lint tools.
RUN uv sync --frozen --no-dev

# Copy the rest of the source (filtered by .dockerignore).
COPY apps/ ./apps/
COPY config/ ./config/

# =============================================================================
# Stage 2: runtime
# Lean image — only the venv and the application source.
# =============================================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

# Create a non-root user and group.
RUN groupadd --system quorum && useradd --system --gid quorum --no-create-home quorum

# Copy the virtualenv (contains all installed packages).
COPY --from=builder /app/.venv /app/.venv

# Copy application source and config.
COPY --from=builder /app/apps /app/apps
COPY --from=builder /app/config /app/config

# Create the data directory and give ownership to quorum.
# This directory is the mount point for the persistent event log.
RUN mkdir -p /app/data && chown -R quorum:quorum /app

USER quorum

EXPOSE 8080

# Persistent event log lives here; mount a volume at /app/data to survive restarts.
VOLUME ["/app/data"]

# Liveness probe — hits the authenticated-free health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health')" || exit 1

# Use exec form so uvicorn is PID 1 and receives SIGTERM directly.
ENTRYPOINT ["/app/.venv/bin/uvicorn", "apps.api.app.main:app", \
            "--host", "0.0.0.0", "--port", "8080"]
