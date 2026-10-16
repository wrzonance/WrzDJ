#!/usr/bin/env bash
# Regression for #809 (offending 7f6eb254): cancellation must abort each
# upgrade phase while preserving that phase's recovery contract.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
upgrade="$root/deploy/scripts/upgrade-postgres-volume.sh"
compose_file="$root/deploy/docker-compose.yml"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

run_signal_case() { # SIGNAL PHASE EXPECTED_STATUS
  local signal=$1 phase=$2 expected_status=$3 case_dir="$scratch/$1-$2"
  mkdir -p "$case_dir/bin"
  cat >"$case_dir/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"
signal_upgrade() {
  local process_group
  process_group=$(ps -o pgid= -p "$PPID" | tr -d ' ')
  kill -"$FAKE_SIGNAL" -- "-$process_group"
}

if [ "$1" = compose ]; then
  shift
  command_line="$*"
  case "$command_line" in
    *'run --detach'*'--name'*)
      printf 'NEW_STARTED\n' >>"$FAKE_DOCKER_LOG"
      echo fake-new
      exit 0
      ;;
    *'run --detach'*) echo fake-db; exit 0 ;;
    *'run --rm'*'--entrypoint cat'*) echo 16; exit 0 ;;
    *'run --rm'*'echo "$PG_MAJOR"'*) echo 18; exit 0 ;;
    *'run --rm'*) exit 3 ;;
    *'ps --services'*) echo db; exit 0 ;;
    *'stop'*)
      if [ "$FAKE_PHASE" = stop ]; then
        : >"$FAKE_DOCKER_READY"
        signal_upgrade
      fi
      exit 0
      ;;
  esac
fi

case "$1" in
  inspect)
    if [ "$FAKE_PHASE" = probe ] && [ ! -e "$FAKE_SIGNAL_SENT" ]; then
      : >"$FAKE_SIGNAL_SENT"
      : >"$FAKE_DOCKER_READY"
      signal_upgrade
    fi
    if [[ "$*" == *'.Mounts'* ]]; then echo "${COMPOSE_PROJECT_NAME}_postgres_data"; else
      printf '%s\n' 'POSTGRES_USER=wrzdj' 'POSTGRES_DB=wrzdj'
    fi
    ;;
  pull) ;;
  run)
    if [[ "$*" == *'du -sk /v'* ]]; then
      echo 1
    elif [[ "$*" == *'df -Pk /v'* ]]; then
      echo 100000
    elif [[ "$*" == *'-delete'* ]]; then
      printf 'WIPE_STARTED\n' >>"$FAKE_DOCKER_LOG"
      if [ "$FAKE_PHASE" = replacing ] && [ ! -e "$FAKE_SIGNAL_SENT" ]; then
        : >"$FAKE_SIGNAL_SENT"
        signal_upgrade
      fi
    elif [[ "$*" == *'--detach --name'* ]]; then
      : >"$FAKE_DOCKER_READY"
      printf 'DUMP_STARTED\n' >>"$FAKE_DOCKER_LOG"
    fi
    ;;
  exec)
    if [[ "$*" == *pg_isready* ]]; then exit 0; fi
    if [[ "$*" == *pg_dumpall* ]]; then echo '-- PostgreSQL database cluster dump complete'; fi
    ;;
  stop|start) ;;
  volume)
    if [ "$2" = inspect ]; then
      [ -e "$FAKE_BACKUP_CREATED" ] && exit 0 || exit 1
    fi
    if [ "$2" = create ] && [[ "$3" == *_pg16_backup ]]; then
      : >"$FAKE_BACKUP_CREATED"
      printf 'BACKUP_CREATED\n' >>"$FAKE_DOCKER_LOG"
      if [ "$FAKE_PHASE" = dumping ] && [ ! -e "$FAKE_SIGNAL_SENT" ]; then
        : >"$FAKE_SIGNAL_SENT"
        : >"$FAKE_DOCKER_READY"
        signal_upgrade
      fi
    fi
    if [ "$2" = rm ] && [[ "$3" == *_pg16_backup ]]; then rm -f "$FAKE_BACKUP_CREATED"; fi
    ;;
  rm) ;;
esac
DOCKER
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
  if [ "$phase" != probe ]; then
    grep -q 'Interrupted.' "$case_dir/upgrade.log" || {
      echo "$signal/$phase did not log interruption" >&2; return 1;
    }
    grep -Fq "rm --force ${COMPOSE_PROJECT_NAME}_postgres_data-pg16-upgrade-old ${COMPOSE_PROJECT_NAME}_postgres_data-pg16-upgrade-new" "$FAKE_DOCKER_LOG" || {
      echo "$signal/$phase cancellation cleanup did not remove upgrade containers" >&2; return 1;
    }
  fi
  case "$phase" in
    probe)
      grep -Fq 'rm --force fake-db' "$FAKE_DOCKER_LOG" || {
        echo "$signal/probe EXIT cleanup did not remove the discovery container" >&2; return 1;
      }
      ! grep -q ' stop' "$FAKE_DOCKER_LOG" || {
        echo "$signal/probe continued after cancellation" >&2; return 1;
      }
      ;;
    stop)
      ! grep -q 'DUMP_STARTED\|WIPE_STARTED' "$FAKE_DOCKER_LOG" || {
        echo "$signal/stop continued into upgrade work" >&2; return 1;
      }
      ;;
    dumping)
      grep -q 'DUMP_STARTED' "$FAKE_DOCKER_LOG" || {
        echo "$signal/dumping did not reach backup boundary" >&2; return 1;
      }
      grep -q 'BACKUP_CREATED' "$FAKE_DOCKER_LOG" || {
        echo "$signal/dumping did not create the backup before cancellation" >&2; return 1;
      }
      grep -Fq "volume rm ${COMPOSE_PROJECT_NAME}_postgres_data_pg16_backup" "$FAKE_DOCKER_LOG" || {
        echo "$signal/dumping did not remove incomplete backup" >&2; return 1;
      }
      [ ! -e "$FAKE_BACKUP_CREATED" ] || {
        echo "$signal/dumping left an incomplete backup volume" >&2; return 1;
      }
      if ! grep -Fq 'compose -f' "$FAKE_DOCKER_LOG" || ! grep -q ' start db' "$FAKE_DOCKER_LOG"; then
        echo "$signal/dumping did not restart the previous stack" >&2; return 1;
      fi
      ! grep -q 'WIPE_STARTED' "$FAKE_DOCKER_LOG" || {
        echo "$signal/dumping continued into replacement" >&2; return 1;
      }
      ;;
    replacing)
      grep -q 'WIPE_STARTED' "$FAKE_DOCKER_LOG" || {
        echo "$signal/replacing did not reach wipe boundary" >&2; return 1;
      }
      grep -q 'Restoring the PostgreSQL' "$case_dir/upgrade.log" || {
        echo "$signal/replacing did not explain rollback recovery" >&2; return 1;
      }
      ! grep -q 'NEW_STARTED' "$FAKE_DOCKER_LOG" || {
        echo "$signal/replacing continued after wipe signal" >&2; return 1;
      }
      grep -Fq "volume rm ${COMPOSE_PROJECT_NAME}_postgres_data_pg16_backup" "$FAKE_DOCKER_LOG" || {
        echo "$signal/replacing did not remove the rolled-back backup" >&2; return 1;
      }
      [ ! -e "$FAKE_BACKUP_CREATED" ] || {
        echo "$signal/replacing left the rolled-back backup volume" >&2; return 1;
      }
      grep -q ' start db' "$FAKE_DOCKER_LOG" || {
        echo "$signal/replacing did not restart the restored stack" >&2; return 1;
      }
      ;;
  esac
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
