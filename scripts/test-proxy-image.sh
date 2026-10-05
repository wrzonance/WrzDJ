#!/usr/bin/env bash
# Exercise the real development templates against an isolated HTTP upstream.
set -euo pipefail
image=${1:?Usage: test-proxy-image.sh IMAGE}
root=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d)
network=
upstream=
proxy=
id=
trap '
  if [ "$?" -ne 0 ] && [ -n "$proxy" ]; then docker logs "$proxy" >&2 || true; fi
  for id in "$proxy" "$upstream"; do
    if [ -n "$id" ]; then docker rm --force "$id" >/dev/null || true; fi
  done
  if [ -n "$network" ]; then docker network rm "$network" >/dev/null || true; fi
  rm -rf "$scratch"
' EXIT
mkdir "$scratch/conf" "$scratch/certs"
for template in "$root"/deploy/dev-proxy/nginx/*.conf.template; do
  sed "s/\${LAN_IP}/127.0.0.1/g" "$template" > "$scratch/conf/$(basename "${template%.template}")"
done
openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
  -keyout "$scratch/certs/key.pem" -out "$scratch/certs/cert.pem" \
  -subj '/CN=app.local' 2>/dev/null
cat > "$scratch/upstream.conf" <<'CONF'
server {
    listen 3000;
    listen 8000;
    location / { return 200 "upstream:$server_port:$request_uri"; }
    location = /unavailable { return 503 "private upstream detail"; }
}
CONF
network=$(docker network create --internal "wrzdj-proxy-smoke-$(basename "$scratch")")
upstream=$(docker run --detach --network "$network" --network-alias host.docker.internal \
  --volume "$scratch/upstream.conf:/etc/nginx/conf.d/default.conf:ro" "$image")
proxy=$(docker run --detach --network "$network" \
  --volume "$scratch/conf:/etc/nginx/conf.d:ro" \
  --volume "$scratch/certs:/etc/nginx/certs:ro" "$image")
docker exec "$proxy" nginx -t
for ((attempt = 0; attempt < 30; attempt++)); do
  if docker exec "$proxy" curl --fail --silent --max-time 1 \
    http://host.docker.internal:3000/ >/dev/null; then break; fi
  sleep 1
done
if [ "$attempt" = 30 ]; then echo 'Upstream did not become ready.' >&2; exit 1; fi

request() {
  docker exec "$proxy" curl --insecure --silent --show-error --max-time 5 \
    --dump-header - --header "Host: $1" "$2" | tr -d '\r'
}
expect() {
  if ! grep -Fqi -- "$1" <<< "$response"; then
    echo "Missing expected response: $1" >&2
    echo "$response" >&2
    exit 1
  fi
}
response=$(request app.local http://127.0.0.1/check)
expect '301'
expect 'Location: https://app.local/check'
response=$(request api.local http://127.0.0.1/check)
expect 'Location: https://api.local:8443/check'
response=$(request app.local https://127.0.0.1/check)
expect 'upstream:3000:/check'
expect 'X-Frame-Options: SAMEORIGIN'
expect "frame-ancestors 'none'"
expect 'Strict-Transport-Security:'
expect 'X-Content-Type-Options: nosniff'
response=$(request app.local https://127.0.0.1/e/test/overlay)
expect 'upstream:3000:/e/test/overlay'
expect 'frame-ancestors *'
if grep -Fqi 'X-Frame-Options:' <<< "$response"; then
  echo 'Overlay must remain embeddable.' >&2; exit 1
fi
response=$(request api.local https://127.0.0.1:8443/health)
expect 'upstream:8000:/health'
expect 'X-Frame-Options: DENY'
expect "default-src 'none'"
response=$(request api.local https://127.0.0.1:8443/uploads/test.png)
expect 'upstream:8000:/uploads/test.png'
expect 'Access-Control-Allow-Origin: *'
response=$(request api.local https://127.0.0.1:8443/unavailable)
expect '502'
expect '{"error":"Service temporarily unavailable"}'
expect 'Access-Control-Allow-Origin: https://127.0.0.1'
if grep -Fqi 'private upstream detail' <<< "$response"; then
  echo 'Upstream details leaked.' >&2; exit 1
fi
echo 'Proxy TLS routing, redirects, security/overlay/upload headers and error handling passed.'
