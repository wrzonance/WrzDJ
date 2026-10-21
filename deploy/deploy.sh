#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "Usage: $0" >&2
  exit 2
fi

# WrzDJ Production Deploy Script
# Usage: ./deploy/deploy.sh
#
# Safely rebuilds the Docker stack by:
# 1. Checking the PostgreSQL data volume, upgrading an older major version if needed
# 2. Stopping existing containers
# 3. Killing any process holding service ports (configurable via PORT_API / PORT_FRONTEND)
# 4. Rebuilding and starting fresh
# 5. Waiting for API health check to pass
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

# Must run before anything else touches the stack. A compatible volume is a
# no-op; an older PostgreSQL major is upgraded (old data kept in a backup
# volume); anything unrecognised aborts while the current stack keeps serving.
echo "==> Checking PostgreSQL data volume..."
"$SCRIPT_DIR/scripts/upgrade-postgres-volume.sh" "$COMPOSE_FILE"

echo "==> Stopping existing containers..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true

"$SCRIPT_DIR/scripts/cleanup-deploy-ports.sh" "$PORT_API" "$PORT_FRONTEND"

echo "==> Ensuring log directories exist..."
mkdir -p "$SCRIPT_DIR/logs/api"
chown "$(id -u)":1000 "$SCRIPT_DIR/logs/api"
chmod 775 "$SCRIPT_DIR/logs/api"

echo "==> Rebuilding and starting stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "==> Waiting for API to become healthy..."
"$SCRIPT_DIR/scripts/wait-for-api-health.sh" "$COMPOSE_FILE" "$PORT_API" "${WRZDJ_API_HEALTH_TIMEOUT:-60}"

echo ""
echo "==> Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo "==> Deploy complete"
