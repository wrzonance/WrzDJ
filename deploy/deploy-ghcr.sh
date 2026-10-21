#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [VERSION]" >&2
  exit 2
fi

# WrzDJ GHCR Deploy Script
# Usage: ./deploy/deploy-ghcr.sh [VERSION]
#
# VERSION can be: stable (newest release), latest (HEAD of main), v2026.05.16,
# sha-a3f8c2b (default: stable)
# Pulls pre-built images from GHCR and starts the stack.
# For build-from-source deploys, use deploy/deploy.sh instead.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.ghcr.yml"

# Load env file if present
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

# Optional second Compose file layered over the first (e.g. the resource budget
# in docker-compose.testing.yml for a stack that shares a host with production).
# A relative path is taken from the deploy/ directory.
COMPOSE_FILES=("$COMPOSE_FILE")
if [ -n "${WRZDJ_COMPOSE_OVERRIDE:-}" ]; then
  OVERRIDE_FILE="$WRZDJ_COMPOSE_OVERRIDE"
  [[ "$OVERRIDE_FILE" == /* ]] || OVERRIDE_FILE="$SCRIPT_DIR/$OVERRIDE_FILE"
  if [ ! -f "$OVERRIDE_FILE" ]; then
    echo "ERROR: WRZDJ_COMPOSE_OVERRIDE points at a missing file: $OVERRIDE_FILE" >&2
    exit 1
  fi
  COMPOSE_FILES+=("$OVERRIDE_FILE")
fi
COMPOSE_ARGS=()
for file in "${COMPOSE_FILES[@]}"; do COMPOSE_ARGS+=(-f "$file"); done

# Precedence: argument, then WRZDJ_VERSION from .env, then the newest release.
VERSION="${1:-${WRZDJ_VERSION:-stable}}"
PORT_API="${PORT_API:-8000}"

# Pull first: a missing or misspelled version fails here, while the current
# stack is still serving and before the database has been touched.
echo "==> Pulling WrzDJ $VERSION images..."
WRZDJ_VERSION="$VERSION" docker compose "${COMPOSE_ARGS[@]}" pull api web

# Must run before anything else touches the stack. A compatible volume is a
# no-op; an older PostgreSQL major is upgraded (old data kept in a backup
# volume); anything unrecognised aborts while the current stack keeps serving.
echo "==> Checking PostgreSQL data volume..."
WRZDJ_VERSION="$VERSION" "$SCRIPT_DIR/scripts/upgrade-postgres-volume.sh" "${COMPOSE_FILES[@]}"

echo "==> Stopping existing containers..."
docker compose "${COMPOSE_ARGS[@]}" down --remove-orphans 2>/dev/null || true

PORT_FRONTEND="${PORT_FRONTEND:-3000}"
"$SCRIPT_DIR/scripts/cleanup-deploy-ports.sh" "$PORT_API" "$PORT_FRONTEND"

echo "==> Ensuring log directories exist..."
mkdir -p "$SCRIPT_DIR/logs/api"
chown "$(id -u)":1000 "$SCRIPT_DIR/logs/api"
chmod 775 "$SCRIPT_DIR/logs/api"

echo "==> Starting stack..."
WRZDJ_VERSION="$VERSION" docker compose "${COMPOSE_ARGS[@]}" up -d

echo "==> Waiting for API to become healthy..."
"$SCRIPT_DIR/scripts/wait-for-api-health.sh" "$COMPOSE_FILE" "$PORT_API" "${WRZDJ_API_HEALTH_TIMEOUT:-60}" "$VERSION"

echo ""
echo "==> Service status:"
docker compose "${COMPOSE_ARGS[@]}" ps

echo "==> Deploy complete"
