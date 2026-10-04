FROM python:3.14-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151

WORKDIR /app

# Install system dependencies. `apt-get upgrade` pulls the Debian security
# updates published since the pinned base-image digest was built (Trivy gate).
# Trade-off, chosen deliberately: this layer resolves against Debian's mutable
# repositories, so the build is only as reproducible as the digest pin above,
# and Docker keeps the cached layer until that pin changes. Renovate bumps the
# digest as new base images ship, which is what refreshes this layer.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the committed production graph with artifact hash verification. pyaes
# and ratelimit publish only source: preinstall their locked backend, without isolation,
# so source builds cannot download additional, unpinned build dependencies.
# Mount uv for this step so neither it nor its cache enters the runtime image.
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21,source=/uv,target=/bin/uv \
    export UV_NO_CACHE=1 \
    && uv export --quiet --locked --only-group build --no-emit-project --output-file requirements.build \
    && uv pip install --system --no-cache --require-hashes --no-deps --only-binary :all: -r requirements.build \
    && uv export --quiet --locked --no-dev --no-emit-project --output-file requirements.lock \
    && uv pip install --system --no-cache --require-hashes --no-deps --no-build-isolation \
        --only-binary :all: --no-binary pyaes,ratelimit -r requirements.lock \
    && uv pip uninstall --system setuptools \
    && python -m pip uninstall --yes pip

# Run application source directly from /app; no editable installation is needed.
COPY . .

# Make start script executable
RUN chmod +x scripts/start.sh

# Create uploads directory
RUN mkdir -p /app/uploads/banners

# Create non-root user with fixed UID/GID 1000 so bind-mounted host directories
# (e.g. deploy/logs/api) can be chown'd to :1000 with chmod 775 instead of 777.
RUN groupadd -g 1000 appuser \
    && useradd -u 1000 -g 1000 -m appuser \
    && chown -R appuser:appuser /app
USER appuser

# Default port (can be overridden by PaaS via PORT env var)
ENV PORT=8000
EXPOSE 8000

# Health check
# Use 127.0.0.1 (not "localhost") so the probe targets IPv4 directly.
# uvicorn binds 0.0.0.0; curl on "localhost" tries ::1 first and falls back,
# wasting one connect attempt per cycle. Explicit IPv4 is cleaner and matches
# the dashboard healthcheck pattern.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-8000}/health || exit 1

# Use start script for migrations and server startup
CMD ["./scripts/start.sh"]
