#!/usr/bin/env bash
# Regression for the runtime image at 124d211d: npm brought vulnerable build
# dependencies into the standalone server. Verify the actual shipped container.
set -euo pipefail

image=${1:?Usage: test-web-image.sh IMAGE}
container=$(docker run --detach --network none \
  --env NEXT_PUBLIC_API_URL=http://localhost:8000 "$image")
trap 'docker rm --force "$container" >/dev/null' EXIT

# The standalone app must start as an unprivileged user without build tools.
if docker exec "$container" sh -c 'command -v npm || command -v npx'; then
  echo 'The web runtime still exposes npm/npx and their build dependencies.' >&2
  exit 1
fi
if [ "$(docker exec "$container" id -u)" = 0 ]; then
  echo 'The web runtime must not run as root.' >&2
  exit 1
fi

# Exercise the real entrypoint and HTTP server; the container has no network
# access except loopback and is always removed, including on failure.
for ((attempt = 0; attempt < 30; attempt++)); do
  if docker exec "$container" wget --quiet --timeout=2 --spider http://127.0.0.1:3000/; then
    echo 'Web runtime smoke test passed.'
    exit 0
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]; then
    break
  fi
  sleep 1
done

docker logs "$container" >&2
echo 'The web runtime did not serve HTTP successfully within 30 attempts.' >&2
exit 1
