#!/usr/bin/env bash
set -euo pipefail

# WrzDJ GHCR Deploy Script
# Usage: ./deploy/deploy-ghcr.sh [VERSION]
#
# VERSION can be: latest, v2026.05.16, sha-a3f8c2b (default: latest)
# Pulls pre-built images from GHCR and starts the stack.
# For build-from-source deploys, use deploy/deploy.sh instead.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.ghcr.yml"
VERSION="${1:-latest}"

# Load env file if present
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

PORT_API="${PORT_API:-8000}"

echo "==> Pulling WrzDJ $VERSION images..."
WRZDJ_VERSION="$VERSION" docker compose -f "$COMPOSE_FILE" pull api web

echo "==> Stopping existing containers..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true

# Mirror deploy.sh: kill any non-Docker process (or Docker proxy) holding the
# service ports between `down` and `up`. docker compose down alone does not
# always release these — see MEMORY.md "Production Deploy (VPS)" notes.
PORT_FRONTEND="${PORT_FRONTEND:-3000}"
echo "==> Checking for processes holding ports $PORT_API and $PORT_FRONTEND..."
for PORT in $PORT_API $PORT_FRONTEND; do
  PIDS=$(ss -tlnp 2>/dev/null | grep ":${PORT}" | grep -oP 'pid=\K[0-9]+' | sort -u || true)
  if [ -n "${PIDS:-}" ]; then
    for PID in $PIDS; do
      PROC=$(ps -p "$PID" -o comm= 2>/dev/null || echo "unknown")
      echo "    Port $PORT held by PID $PID ($PROC) — killing"
      kill "$PID" 2>/dev/null || true
    done
    sleep 1
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

echo "==> Ensuring log directories exist..."
mkdir -p "$SCRIPT_DIR/logs/api"

echo "==> Starting stack..."
WRZDJ_VERSION="$VERSION" docker compose -f "$COMPOSE_FILE" up -d

echo "==> Waiting for API to become healthy..."
ELAPSED=0
while [ $ELAPSED -lt 60 ]; do
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

if [ $ELAPSED -ge 60 ]; then
  echo ""
  echo "ERROR: API did not become healthy within 60s"
  echo "==> API logs:"
  docker compose -f "$COMPOSE_FILE" logs --tail=20 api
  exit 1
fi

echo ""
echo "==> Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo "==> Deploy complete"
