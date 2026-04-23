# syntax=docker/dockerfile:1

ARG UV_VERSION=0.11.7
ARG FLYCTL_VERSION=0.4.39
ARG FLYCTL_SHA256=87c89a59106e65569fb1d91aa2404a4d472248d240d87a5edfcace920d382f10

# =============================================================================
# Stage 1: flyctl
# Download a pinned flyctl binary for the runtime image. The Python base is
# pinned to the linux/amd64 digest used by CI/Fly builds; refresh deliberately.
# =============================================================================
FROM python:3.12-slim@sha256:4386a385d81dba9f72ed72a6fe4237755d7f5440c84b417650f38336bbc43117 AS flyctl

ARG FLYCTL_VERSION
ARG FLYCTL_SHA256

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gzip tar \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/flyctl.tar.gz \
        "https://github.com/superfly/flyctl/releases/download/v${FLYCTL_VERSION}/flyctl_${FLYCTL_VERSION}_Linux_x86_64.tar.gz" \
    && echo "${FLYCTL_SHA256}  /tmp/flyctl.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/flyctl.tar.gz -C /usr/local/bin flyctl \
    && mv /usr/local/bin/flyctl /usr/local/bin/fly \
    && chmod 0755 /usr/local/bin/fly \
    && /usr/local/bin/fly version \
    && rm -f /tmp/flyctl.tar.gz

# =============================================================================
# Stage 2: builder
# Install uv, sync the locked virtualenv, then copy source in.
# =============================================================================
FROM python:3.12-slim@sha256:4386a385d81dba9f72ed72a6fe4237755d7f5440c84b417650f38336bbc43117 AS builder

ARG UV_VERSION

WORKDIR /app

# Install a pinned uv bootstrap binary. uv.lock pins project deps.
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# Copy dependency manifests first so Docker can cache the sync layer.
COPY pyproject.toml uv.lock ./

# Install only production dependencies into /app/.venv.
# --frozen: refuse to update uv.lock; --no-dev: skip test / lint tools.
RUN uv sync --frozen --no-dev

# Copy the rest of the source (filtered by .dockerignore).
COPY apps/ ./apps/
COPY config/ ./config/

# =============================================================================
# Stage 3: runtime
# Lean image — only the venv and the application source.
# =============================================================================
FROM python:3.12-slim@sha256:4386a385d81dba9f72ed72a6fe4237755d7f5440c84b417650f38336bbc43117 AS runtime

WORKDIR /app

# Create a non-root user and writable home for flyctl's config/cache lookups.
RUN groupadd --system quorum \
    && useradd --system --gid quorum --create-home --home-dir /home/quorum quorum

ENV HOME=/home/quorum

# Copy the virtualenv (contains all installed packages).
COPY --from=builder /app/.venv /app/.venv

# Copy application source and config.
COPY --from=builder /app/apps /app/apps
COPY --from=builder /app/config /app/config

# Copy only the verified flyctl binary needed by the fly.deploy actuator.
COPY --from=flyctl /usr/local/bin/fly /usr/local/bin/fly

# Create the data directory and give ownership to quorum.
# This directory is the mount point for the persistent event log.
RUN mkdir -p /app/data && chown -R quorum:quorum /app /home/quorum

USER quorum

RUN fly version

EXPOSE 8080

# Persistent event log lives here; mount a volume at /app/data to survive restarts.
VOLUME ["/app/data"]

# Liveness probe — hits the authenticated-free health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health')" || exit 1

# Use exec form so uvicorn is PID 1 and receives SIGTERM directly.
ENTRYPOINT ["/app/.venv/bin/uvicorn", "apps.api.app.main:app", \
            "--host", "0.0.0.0", "--port", "8080"]
