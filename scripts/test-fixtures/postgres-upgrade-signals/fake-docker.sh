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
  # shellcheck disable=SC2016 # Match Compose's literal PG_MAJOR interpolation below.
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
