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
  echo "WARNING: API did not become healthy within 60s"
  echo "==> API logs:"
  docker compose -f "$COMPOSE_FILE" logs --tail=20 api
fi

echo ""
echo "==> Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo "==> Deploy complete"
