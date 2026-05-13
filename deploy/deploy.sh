#!/usr/bin/env bash
set -euo pipefail

# WrzDJ Production Deploy Script
# Usage: ./deploy/deploy.sh
#
# Safely rebuilds the Docker stack by:
# 1. Stopping existing containers
# 2. Killing any process holding service ports (configurable via PORT_API / PORT_FRONTEND)
# 3. Rebuilding and starting fresh
# 4. Waiting for API health check to pass
#
# Reads deploy/.env if present for PORT_API (default 8000) and PORT_FRONTEND (default 3000)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

# Load env file if present (for PORT_API / PORT_FRONTEND overrides)
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

PORT_API="${PORT_API:-8000}"
PORT_FRONTEND="${PORT_FRONTEND:-3000}"

echo "==> Stopping existing containers..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true

echo "==> Checking for processes holding ports $PORT_API and $PORT_FRONTEND..."
for PORT in $PORT_API $PORT_FRONTEND; do
  PIDS=$(ss -tlnp | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | sort -u || true)
  if [ -n "${PIDS:-}" ]; then
    for PID in $PIDS; do
      PROC=$(ps -p "$PID" -o comm= 2>/dev/null || echo "unknown")
      echo "    Port $PORT held by PID $PID ($PROC) — killing"
      kill "$PID" 2>/dev/null || true
    done
    sleep 1
    # Force kill any survivors
    for PID in $PIDS; do
      if kill -0 "$PID" 2>/dev/null; then
        echo "    PID $PID still alive — sending SIGKILL"
        kill -9 "$PID" 2>/dev/null || true
      fi
    done
  else
    echo "    Port $PORT is free"
  fi
done

echo "==> Verifying uploads directory structure..."
# The api_uploads Docker volume handles persistence, but ensure the banners
# subdirectory exists inside it. On first deploy with an empty volume,
# start.sh also creates this, but we verify here as a safety net.
UPLOADS_VOLUME="api_uploads"
if docker volume inspect "${UPLOADS_VOLUME}" > /dev/null 2>&1; then
  echo "    Volume ${UPLOADS_VOLUME} exists"
else
  echo "    Volume ${UPLOADS_VOLUME} will be created by Docker Compose"
fi

echo "==> Ensuring log directories exist..."
mkdir -p "$SCRIPT_DIR/logs/api"

echo "==> Rebuilding and starting stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "==> Waiting for API to become healthy..."
MAX_WAIT=60
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
  if curl -sf "http://127.0.0.1:${PORT_API}/health" > /dev/null 2>&1; then
    echo "    API healthy after ${ELAPSED}s"
    break
  fi
  if [ $ELAPSED -eq 0 ]; then
    printf "    Waiting"
  fi
  printf "."
  sleep 2
  ELAPSED=$((ELAPSED + 2))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
  echo ""
  echo "WARNING: API did not become healthy within ${MAX_WAIT}s"
  echo "==> API logs:"
  docker compose -f "$COMPOSE_FILE" logs --tail=20 api
fi

echo ""
echo "==> Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo "==> Deploy complete"
