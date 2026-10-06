#!/bin/bash
set -e

# Wait for database to be ready
echo "Waiting for database..."
MAX_RETRIES=30
RETRY_INTERVAL=2

for i in $(seq 1 $MAX_RETRIES); do
    if python -c "
from app.db.session import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('SELECT 1'))
" 2>/dev/null; then
        echo "Database is ready!"
        break
    fi

    if [ $i -eq $MAX_RETRIES ]; then
        echo "ERROR: Database not available after $MAX_RETRIES attempts"
        exit 1
    fi

    echo "Attempt $i/$MAX_RETRIES - Database not ready, waiting ${RETRY_INTERVAL}s..."
    sleep $RETRY_INTERVAL
done

# Run migrations
echo "Running database migrations..."
alembic upgrade head

# Bootstrap admin user if configured
echo "Checking bootstrap admin..."
python -m app.scripts.bootstrap

# Ensure uploads directory structure exists (Docker volume may be empty on first run)
UPLOADS_DIR=${UPLOADS_DIR:-/app/uploads}
echo "Ensuring uploads directories exist at $UPLOADS_DIR..."
mkdir -p "$UPLOADS_DIR/banners"

# Start the server
PORT=${PORT:-8000}
echo "Starting server on port $PORT..."
# One worker, stated explicitly: login lockout, kiosk pairing nonces and the SSE
# event bus are in-process state, so a second worker would split them (lockouts
# bypassed, pairings and live updates lost depending on which worker answers).
# The flag overrides WEB_CONCURRENCY, which uvicorn otherwise honors and some
# hosts set by default. See "Single API process" in SECURITY.md before raising it.
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
