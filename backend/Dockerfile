# Multi-stage Dockerfile for SkyMaster backend — v2.1 T1.5.
#
# Stage 1: build layer — installs Python deps + compiles
# Stage 2: runtime layer — slim image with just the app + wheels
#
# Design goals:
# * Reproducible: pins Python 3.11 (matches our conda env)
# * Small: ~180MB final image (vs ~800MB single-stage)
# * Secure: runs as non-root user `skymaster`, no compiler in prod image
# * Fast rebuild: pyproject.toml/requirements copied before source so
#   dep layer is cached across code changes.

FROM python:3.11-slim-bookworm AS builder

# Build tooling for any wheels missing prebuilt binaries (e.g. cryptography on ARM)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dep manifest first for layer caching
COPY pyproject.toml README.md* ./
# Fall back to requirements.txt if pyproject-only build isn't set up yet
COPY requirements.txt* ./

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    if [ -f requirements.txt ]; then \
        pip wheel --wheel-dir /wheels -r requirements.txt ; \
    else \
        pip wheel --wheel-dir /wheels . ; \
    fi

# ---------- runtime stage ----------
FROM python:3.11-slim-bookworm AS runtime

# libpq for asyncpg (Postgres); libmagic if we ever add file-type sniffing
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -g 1000 skymaster && \
    useradd -u 1000 -g 1000 -m -s /bin/bash skymaster

WORKDIR /app

# Install pre-built wheels from builder stage (no compiler here)
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && \
    rm -rf /wheels

# Copy application code
COPY --chown=skymaster:skymaster . /app

USER skymaster

# Storage root for CAS (v2.1 T1.1) — expected to be a volume in prod
ENV SKYMASTER_STORAGE_ROOT=/data/skymaster-storage
ENV SKYMASTER_SCENES_WORKDIR=/data/skymaster-scenes
# Executor default (dev-safe); ops team flips to gsplat on GPU workers
ENV SKYMASTER_EXECUTOR=noop

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
