#!/usr/bin/env bash
# Regression for #809 (offending 7f6eb254): cancellation must abort each
# upgrade phase while preserving that phase's recovery contract.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
upgrade="$root/deploy/scripts/upgrade-postgres-volume.sh"
compose_file="$root/deploy/docker-compose.yml"
fixture_dir="$root/scripts/test-fixtures/postgres-upgrade-signals"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=test-fixtures/postgres-upgrade-signals/assertions.sh
source "$fixture_dir/assertions.sh"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

run_signal_case() { # SIGNAL PHASE EXPECTED_STATUS
  local signal=$1 phase=$2 expected_status=$3 case_dir="$scratch/$1-$2"
  mkdir -p "$case_dir/bin"
  cp "$fixture_dir/fake-docker.sh" "$case_dir/bin/docker"
  chmod +x "$case_dir/bin/docker"

  export COMPOSE_PROJECT_NAME="wrzdj-signal-${signal,,}-${phase}"
  export POSTGRES_UPGRADE_BACKUP_DIR="$case_dir/backups"
  export FAKE_DOCKER_LOG="$case_dir/docker.log"
  export FAKE_DOCKER_READY="$case_dir/ready"
  export FAKE_SIGNAL="$signal"
  export FAKE_PHASE="$phase"
  export FAKE_SIGNAL_SENT="$case_dir/signal-sent"
  export FAKE_BACKUP_CREATED="$case_dir/backup-created"
  # shellcheck disable=SC2016 # Perl receives the quoted signal-reset program.
  PATH="$case_dir/bin:$PATH" timeout --kill-after=2s 15s setsid perl -e \
    '$SIG{INT} = "DEFAULT"; $SIG{TERM} = "DEFAULT"; exec @ARGV or die $!' \
    -- bash "$upgrade" "$compose_file" >"$case_dir/upgrade.log" 2>&1 &
  local pid=$! status
  for ((attempt = 0; attempt < 100; attempt++)); do
    [ -e "$FAKE_DOCKER_READY" ] && break
    sleep 0.05
  done
  [ -e "$FAKE_DOCKER_READY" ] || { echo "$signal/$phase case never reached the signal boundary" >&2; return 1; }
  set +e
  wait "$pid"
  status=$?
  set -e
  if [ "$status" != "$expected_status" ]; then
    echo "$signal/$phase exited $status, expected $expected_status" >&2
    cat "$case_dir/upgrade.log" >&2
    cat "$FAKE_DOCKER_LOG" >&2
    return 1
  fi
  assert_signal_case "$signal" "$phase" "$case_dir"
}

for signal in INT TERM; do
  status=130
  [ "$signal" = TERM ] && status=143
  run_signal_case "$signal" probe "$status"
  run_signal_case "$signal" stop "$status"
  run_signal_case "$signal" dumping "$status"
  run_signal_case "$signal" replacing "$status"
done
echo 'INT and TERM abort each upgrade phase with cleanup and recovery preserved.'
