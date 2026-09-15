FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

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

# Copy requirements and install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade "pip>=26.1" "setuptools>=83.0.0"
RUN pip install --no-cache-dir -e .

# Copy application code
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
