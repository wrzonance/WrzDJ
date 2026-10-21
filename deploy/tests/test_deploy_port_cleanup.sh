#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash_path="$(command -v bash)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin"
cat > "$scratch/ss" <<'SS'
#!/usr/bin/env bash
printf '%s\n' invoked >> "$WRZDJ_TEST_SS_LOG"
if [ "${WRZDJ_TEST_SS_EXIT:-0}" -ne 0 ]; then
  cat "$WRZDJ_TEST_SS_OUTPUT"
  printf 'mock socket inspection failed\n' >&2
  exit "$WRZDJ_TEST_SS_EXIT"
fi
cat "$WRZDJ_TEST_SS_OUTPUT"
SS
cat > "$scratch/ps" <<'PS'
#!/usr/bin/env bash
printf 'fake-process-%s\n' "$2"
PS
cat > "$scratch/sleep" <<'SLEEP'
#!/usr/bin/env bash
:
SLEEP
chmod +x "$scratch/ss" "$scratch/ps" "$scratch/sleep"
cat > "$scratch/bash-env" <<'ENV'
kill() {
  printf '%s\n' "$*" >> "$WRZDJ_TEST_KILL_LOG"
  if [ "$1" = -0 ]; then
    [ "$2" = 100 ]
    return
  fi
}
ENV
cat > "$scratch/ss-output" <<'SS'
State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0 4096 0.0.0.0:8000 0.0.0.0:* users:(("docker-proxy",pid=100,fd=4))
LISTEN 0 4096 [::]:3000 [::]:* users:(("docker-proxy",pid=200,fd=4))
SS

export BASH_ENV="$scratch/bash-env"
export PATH="$scratch:$PATH"
export WRZDJ_TEST_SS_OUTPUT="$scratch/ss-output"
export WRZDJ_TEST_KILL_LOG="$scratch/kills.log"
export WRZDJ_TEST_SS_LOG="$scratch/ss-calls.log"

# Invalid ports must fail before process inspection or termination. Empty is
# rejected when explicitly supplied; this command requires at least one port.
for invalid_port in 0 65536 abc 999999999999999999999999999999; do
  status=0
  bash "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" "$invalid_port" \
    > "$scratch/invalid-port.log" 2>&1 || status=$?
  test "$status" -eq 2
  grep -Fq 'Invalid port:' "$scratch/invalid-port.log"
  test ! -s "$WRZDJ_TEST_SS_LOG"
  test ! -s "$WRZDJ_TEST_KILL_LOG"
done

# Validate the complete request before inspecting or terminating any process.
status=0
bash "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" 8000 65536 \
  > "$scratch/invalid-later-port.log" 2>&1 || status=$?
test "$status" -eq 2
grep -Fq 'Invalid port: 65536' "$scratch/invalid-later-port.log"
test ! -s "$WRZDJ_TEST_SS_LOG"
test ! -s "$WRZDJ_TEST_KILL_LOG"

status=0
bash "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" '' \
  > "$scratch/empty-port.log" 2>&1 || status=$?
test "$status" -eq 2
test ! -s "$WRZDJ_TEST_SS_LOG"
test ! -s "$WRZDJ_TEST_KILL_LOG"

# Leading zeroes are accepted like setup-nginx.sh and interpreted as decimal.
bash "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" 08000 > "$scratch/leading-zero.log"
grep -Fq 'Port 8000 held by PID 100' "$scratch/leading-zero.log"
grep -Fqx -- '100' "$WRZDJ_TEST_KILL_LOG"
: > "$WRZDJ_TEST_KILL_LOG"
: > "$WRZDJ_TEST_SS_LOG"

bash "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" 8000 3000

grep -Fqx -- '100' "$WRZDJ_TEST_KILL_LOG"
grep -Fqx -- '-9 100' "$WRZDJ_TEST_KILL_LOG"
grep -Fqx -- '200' "$WRZDJ_TEST_KILL_LOG"
if grep -Fqx -- '-9 200' "$WRZDJ_TEST_KILL_LOG"; then
  echo 'cleanup force-killed a process that exited after SIGTERM' >&2
  exit 1
fi

cat > "$scratch/ss-empty-output" <<'SS'
State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0 4096 0.0.0.0:9000 0.0.0.0:* users:("unrelated",pid=900,fd=4)
SS
WRZDJ_TEST_SS_OUTPUT="$scratch/ss-empty-output" bash \
  "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" 8000 > "$scratch/empty-output.log"
grep -Fqx -- '    Port 8000 is free' "$scratch/empty-output.log"

before_failure_kills="$(wc -l < "$WRZDJ_TEST_KILL_LOG")"
set +e
WRZDJ_TEST_SS_EXIT=42 bash "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" 8000 \
  > "$scratch/ss-failure.log" 2>&1
ss_status=$?
set -e
if [ "$ss_status" -eq 0 ]; then
  echo 'cleanup treated failed ss inspection as a free port' >&2
  exit 1
fi
grep -Fq 'Failed to inspect listening ports for port 8000' "$scratch/ss-failure.log"
grep -Fq 'mock socket inspection failed' "$scratch/ss-failure.log"
if [ "$(wc -l < "$WRZDJ_TEST_KILL_LOG")" -ne "$before_failure_kills" ]; then
  echo 'cleanup killed a process after ss failed' >&2
  exit 1
fi

mkdir "$scratch/no-ss-bin"
cp "$scratch/ps" "$scratch/sleep" "$scratch/no-ss-bin/"
before_missing_kills="$(wc -l < "$WRZDJ_TEST_KILL_LOG")"
set +e
PATH="$scratch/no-ss-bin" "$bash_path" "$repo_root/deploy/scripts/cleanup-deploy-ports.sh" 8000 \
  > "$scratch/ss-missing.log" 2>&1
missing_status=$?
set -e
if [ "$missing_status" -eq 0 ]; then
  echo 'cleanup treated missing ss command as a free port' >&2
  exit 1
fi
grep -Fq 'Failed to inspect listening ports for port 8000' "$scratch/ss-missing.log"
grep -Fq 'ss: command not found' "$scratch/ss-missing.log"
if [ "$(wc -l < "$WRZDJ_TEST_KILL_LOG")" -ne "$before_missing_kills" ]; then
  echo 'cleanup killed a process when ss was missing' >&2
  exit 1
fi
echo 'Deploy port cleanup terminates holders and only force-kills survivors.'
