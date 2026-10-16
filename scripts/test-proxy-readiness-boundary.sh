#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
proxy_script=${WRZDJ_PROXY_SCRIPT:-$root/scripts/test-proxy-image.sh}
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin"
printf '0\n0\n' > "$scratch/state"

cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
state=${WRZDJ_PROXY_TEST_STATE:?}
mapfile -t attempts < "$state"
upstream_attempt=${attempts[0]:-0}
proxy_attempt=${attempts[1]:-0}
write_state() { printf '%s\n%s\n' "$upstream_attempt" "$proxy_attempt" > "$state"; }
case "${1:-}" in
  network)
    [ "${2:-}" = create ] && printf 'network-id\n' && exit 0
    [ "${2:-}" = rm ] && exit 0
    ;;
  run)
    if [[ "$*" == *'--network-alias host.docker.internal'* ]]; then
      printf 'upstream-id\n'
    else
      printf 'proxy-id\n'
    fi
    exit 0
    ;;
  logs|rm)
    exit 0
    ;;
  exec)
    command_line="$*"
    if [[ "$command_line" == *'nginx -t'* ]]; then exit 0; fi
    if [[ "$command_line" == *'host.docker.internal:3000/'* ]]; then
      upstream_attempt=$((upstream_attempt + 1)); write_state; exit 0
    fi
    if [[ "$command_line" == *'http://127.0.0.1/' ]]; then
      proxy_attempt=$((proxy_attempt + 1)); write_state
      if [ "$proxy_attempt" -lt 3 ]; then exit 7; fi
      exit 0
    fi
    if [[ "$command_line" == *'Host: app.local'*'http://127.0.0.1/check'* ]]; then
      if [ "$proxy_attempt" -lt 3 ]; then
        echo 'curl: (7) Failed to connect to 127.0.0.1 port 80' >&2
        exit 7
      fi
      printf 'HTTP/1.1 301 Moved Permanently\nLocation: https://app.local/check\n'
      exit 0
    fi
    if [[ "$command_line" == *'Host: api.local'*'http://127.0.0.1/check'* ]]; then
      printf 'HTTP/1.1 301 Moved Permanently\nLocation: https://api.local:8443/check\n'
      exit 0
    fi
    if [[ "$command_line" == *'Host: app.local'*'https://127.0.0.1/e/test/overlay'* ]]; then
      printf 'upstream:3000:/e/test/overlay\nframe-ancestors *\n'
      exit 0
    fi
    if [[ "$command_line" == *'Host: app.local'*'https://127.0.0.1/check'* ]]; then
      printf 'upstream:3000:/check\nX-Frame-Options: SAMEORIGIN\nframe-ancestors '\''none'\''\nStrict-Transport-Security: max-age=31536000; includeSubDomains\nX-Content-Type-Options: nosniff\n'
      exit 0
    fi
    if [[ "$command_line" == *'Host: api.local'*'https://127.0.0.1:8443/health'* ]]; then
      printf 'upstream:8000:/health\nX-Frame-Options: DENY\ndefault-src '\''none'\''\n'
      exit 0
    fi
    if [[ "$command_line" == *'Host: api.local'*'https://127.0.0.1:8443/uploads/test.png'* ]]; then
      printf 'upstream:8000:/uploads/test.png\nAccess-Control-Allow-Origin: *\n'
      exit 0
    fi
    if [[ "$command_line" == *'Host: api.local'*'https://127.0.0.1:8443/unavailable'* ]]; then
      printf 'HTTP/1.1 502 Bad Gateway\n{"error":"Service temporarily unavailable"}\nAccess-Control-Allow-Origin: https://127.0.0.1\n'
      exit 0
    fi
    ;;
esac
echo "unexpected docker invocation: $*" >&2
exit 1
DOCKER
chmod +x "$scratch/bin/docker"

if ! PATH="$scratch/bin:$PATH" WRZDJ_PROXY_TEST_STATE="$scratch/state" \
  WRZDJ_READINESS_ATTEMPTS=5 WRZDJ_READINESS_DELAY=0 \
  bash "$proxy_script" fake-image; then
  echo 'proxy smoke should wait for nginx before its first request' >&2
  exit 1
fi

echo 'Proxy smoke waits for nginx readiness before assertions.'

failure_log="$scratch/failure.log"
printf '0\n0\n' > "$scratch/state"
if PATH="$scratch/bin:$PATH" WRZDJ_PROXY_TEST_STATE="$scratch/state" \
  WRZDJ_READINESS_ATTEMPTS=1 WRZDJ_READINESS_DELAY=0 \
  bash "$proxy_script" fake-image >"$failure_log" 2>&1; then
  echo 'proxy smoke should fail when nginx never becomes ready' >&2
  exit 1
fi
if ! grep -Fq -- 'Proxy HTTP service did not become ready after 1 attempts.' "$failure_log"; then
  echo 'proxy smoke should report the readiness timeout' >&2
  cat "$failure_log" >&2
  exit 1
fi

echo 'Proxy smoke reports bounded readiness failure.'
