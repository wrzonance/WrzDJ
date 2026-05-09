FROM python:3.11-slim@sha256:233de06753d30d120b1a3ce359d8d3be8bda78524cd8f520c99883bfe33964cf

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY pyproject.toml .
RUN pip install --upgrade "pip>=26.1"
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Make start script executable
RUN chmod +x scripts/start.sh

# Create uploads directory
RUN mkdir -p /app/uploads/banners

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
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
