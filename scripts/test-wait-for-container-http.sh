#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/wait-for-container-http.sh"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
state="$scratch/attempts"
calls="$scratch/calls"
printf '0\n' > "$state"
: > "$calls"
mkdir "$scratch/bin"
cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
state=${WRZDJ_TEST_STATE:?}
calls=${WRZDJ_TEST_CALLS:?}
printf '%s\n' "$*" >> "$calls"
attempt=$(<"$state")
attempt=$((attempt + 1))
printf '%s\n' "$attempt" > "$state"
if [ "$attempt" -lt 3 ]; then
  exit 1
fi
exit 0
DOCKER
chmod +x "$scratch/bin/docker"

if ! PATH="$scratch/bin:$PATH" WRZDJ_TEST_STATE="$state" \
  WRZDJ_TEST_CALLS="$calls" WRZDJ_READINESS_ATTEMPTS=5 WRZDJ_READINESS_DELAY=0 \
  wait_for_container_http proxy http://127.0.0.1/ 'proxy HTTP readiness'; then
  echo 'readiness should tolerate transient connection failures' >&2
  exit 1
fi

if [ "$(<"$state")" != 3 ]; then
  echo 'readiness should stop after the first successful probe' >&2
  exit 1
fi
if ! grep -Fqx -- 'exec proxy curl --fail --silent --max-time 1 http://127.0.0.1/' "$calls"; then
  echo 'readiness should use the expected container curl probe' >&2
  exit 1
fi

echo 'Container HTTP readiness tolerates transient connection failures.'

printf '0\n' > "$state"
if PATH="$scratch/bin:$PATH" WRZDJ_TEST_STATE="$state" WRZDJ_TEST_CALLS="$calls" \
  WRZDJ_READINESS_ATTEMPTS=2 WRZDJ_READINESS_DELAY=0 \
  wait_for_container_http proxy http://127.0.0.1/ 'proxy HTTP readiness'; then
  echo 'readiness should fail after the bounded attempt cap' >&2
  exit 1
fi

if [ "$(<"$state")" != 2 ]; then
  echo 'readiness should make exactly the configured number of attempts' >&2
  exit 1
fi

echo 'Container HTTP readiness enforces its bounded timeout.'

if PATH="$scratch/bin:$PATH" WRZDJ_TEST_STATE="$state" WRZDJ_TEST_CALLS="$calls" \
  WRZDJ_READINESS_ATTEMPTS=0 WRZDJ_READINESS_DELAY=0 \
  wait_for_container_http proxy http://127.0.0.1/ 'proxy HTTP readiness' 2>"$scratch/invalid.log"; then
  echo 'invalid readiness configuration should fail' >&2
  exit 1
else
  invalid_rc=$?
fi
if [ "$invalid_rc" -ne 2 ] || ! grep -Fq -- 'attempts=0 delay=0' "$scratch/invalid.log"; then
  echo 'invalid readiness configuration should report status 2 and values' >&2
  exit 1
fi

echo 'Container HTTP readiness validates invalid configuration.'
