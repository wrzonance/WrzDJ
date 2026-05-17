#!/bin/sh
set -e

if [ -n "${NEXT_PUBLIC_API_URL:-}" ]; then
  find /app/.next -type f -name "*.js" \
    -exec sed -i "s|__WRZDJ_API_URL__|${NEXT_PUBLIC_API_URL}|g" {} +
else
  echo "WARNING: NEXT_PUBLIC_API_URL not set. Browser requests will fall back to window.location.hostname:8000. CSP will block cross-origin API calls." >&2
fi

exec "$@"
