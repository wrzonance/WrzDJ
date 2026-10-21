#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin"

cat > "$scratch/bin/curl" <<'CURL'
#!/usr/bin/env bash
set -euo pipefail
timeout='missing'
while [ "$#" -gt 0 ]; do
  if [ "$1" = --max-time ]; then
    timeout=$2
    shift 2
  else
    shift
  fi
done
printf '%s\n' "$timeout" >> "$WRZDJ_CURL_TIMEOUTS"
if [ "${WRZDJ_CURL_MODE:-fail}" = stall ]; then
  /usr/bin/sleep "$timeout"
  exit 28
fi
if [ "${WRZDJ_CURL_MODE:-fail}" = healthy ]; then
  exit 0
fi
exit 22
CURL
cat > "$scratch/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
printf '%s\n' "$1" >> "$WRZDJ_SLEEP_INTERVALS"
/usr/bin/sleep "$1"
SLEEP
cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_DOCKER_CALLS"
DOCKER
chmod +x "$scratch/bin"/*

export PATH="$scratch/bin:$PATH"
export WRZDJ_CURL_TIMEOUTS="$scratch/curl-timeouts"
export WRZDJ_SLEEP_INTERVALS="$scratch/sleep-intervals"
export WRZDJ_DOCKER_CALLS="$scratch/docker-calls"
helper="$repo_root/deploy/scripts/wait-for-api-health.sh"

# Reject invalid ports before curl or Docker can be reached. Empty remains an
# invalid explicit argument; the helper has no default port.
for invalid_port in '' 0 65536 abc 999999999999999999999999999999; do
  : > "$WRZDJ_CURL_TIMEOUTS"
  : > "$WRZDJ_DOCKER_CALLS"
  status=0
  bash "$helper" compose.yml "$invalid_port" 1 > "$scratch/invalid-port.log" 2>&1 || status=$?
  test "$status" -eq 2
  grep -Fq 'Invalid port:' "$scratch/invalid-port.log"
  test ! -s "$WRZDJ_CURL_TIMEOUTS"
  test ! -s "$WRZDJ_DOCKER_CALLS"
done

# Match setup-nginx.sh's digit-only policy: leading zeroes are accepted.
WRZDJ_CURL_MODE=healthy bash "$helper" compose.yml 00080 1 > "$scratch/leading-zero.log"
grep -Fq 'API healthy' "$scratch/leading-zero.log"
: > "$WRZDJ_CURL_TIMEOUTS"
: > "$WRZDJ_DOCKER_CALLS"

# EPOCHREALTIME may use either decimal separator under the caller's locale.
# Verify the parser at its shell-function boundary with both representations.
# shellcheck source=../scripts/wait-for-api-health.sh
source "$helper"
test "$(epoch_realtime_to_ms '1792489191.378913')" = '1792489191378'
test "$(epoch_realtime_to_ms '1792489191,378913')" = '1792489191378'

status=0
WRZDJ_CURL_MODE=stall bash "$helper" compose.yml 8000 1 > "$scratch/stalled.log" 2>&1 || status=$?
test "$status" -eq 1
awk 'NR != 1 || $1 <= 0 || $1 > 1.001 { exit 1 }' "$WRZDJ_CURL_TIMEOUTS"
grep -Fq 'did not become healthy within 1s' "$scratch/stalled.log"

: > "$WRZDJ_CURL_TIMEOUTS"
: > "$WRZDJ_SLEEP_INTERVALS"
status=0
bash "$helper" compose.yml 8000 3 > "$scratch/odd-limit.log" 2>&1 || status=$?
test "$status" -eq 1
awk 'NR == 1 && ($1 <= 0 || $1 > 3.001) { exit 1 } END { if (NR == 0) exit 1 }' \
  "$WRZDJ_CURL_TIMEOUTS"
awk '$1 <= 0 || $1 > 2.001 { exit 1 }' "$WRZDJ_SLEEP_INTERVALS"
awk '$1 <= 0 || $1 > 3.000 { exit 1 }' "$WRZDJ_CURL_TIMEOUTS"
grep -Fq 'did not become healthy within 3s' "$scratch/odd-limit.log"

WRZDJ_CURL_MODE=healthy bash "$helper" compose.yml 8000 3 > "$scratch/healthy.log" 2>&1
if ! grep -Eq 'API healthy after [0-3]\.[0-9]s' "$scratch/healthy.log"; then
  echo 'successful health check reported an invalid elapsed duration' >&2
  cat "$scratch/healthy.log" >&2
  exit 1
fi

echo 'Health probing bounds stalled curl requests and caps polling sleeps to the remaining timeout.'
