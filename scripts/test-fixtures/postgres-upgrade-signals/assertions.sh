#!/usr/bin/env bash

assert_signal_case() { # SIGNAL PHASE CASE_DIR
  local signal=$1 phase=$2 case_dir=$3
  local docker_log="$case_dir/docker.log"

  if [ "$phase" != probe ]; then
    grep -q 'Interrupted.' "$case_dir/upgrade.log" || {
      echo "$signal/$phase did not log interruption" >&2
      return 1
    }
    grep -Fq "rm --force ${COMPOSE_PROJECT_NAME}_postgres_data-pg16-upgrade-old ${COMPOSE_PROJECT_NAME}_postgres_data-pg16-upgrade-new" "$docker_log" || {
      echo "$signal/$phase cancellation cleanup did not remove upgrade containers" >&2
      return 1
    }
  fi

  case "$phase" in
    probe)
      grep -Fq 'rm --force fake-db' "$docker_log" || {
        echo "$signal/probe EXIT cleanup did not remove the discovery container" >&2
        return 1
      }
      ! grep -q ' stop' "$docker_log" || {
        echo "$signal/probe continued after cancellation" >&2
        return 1
      }
      ;;
    stop)
      ! grep -q 'DUMP_STARTED\|WIPE_STARTED' "$docker_log" || {
        echo "$signal/stop continued into upgrade work" >&2
        return 1
      }
      ;;
    dumping)
      assert_dumping_case "$signal" "$docker_log" "$case_dir/backup-created"
      ;;
    replacing)
      assert_replacing_case "$signal" "$docker_log" "$case_dir/upgrade.log" \
        "$case_dir/backup-created"
      ;;
  esac
}

assert_dumping_case() { # SIGNAL DOCKER_LOG BACKUP_MARKER
  local signal=$1 docker_log=$2 backup_marker=$3
  grep -q 'DUMP_STARTED' "$docker_log" || {
    echo "$signal/dumping did not reach backup boundary" >&2
    return 1
  }
  grep -q 'BACKUP_CREATED' "$docker_log" || {
    echo "$signal/dumping did not create the backup before cancellation" >&2
    return 1
  }
  grep -Fq "volume rm ${COMPOSE_PROJECT_NAME}_postgres_data_pg16_backup" "$docker_log" || {
    echo "$signal/dumping did not remove incomplete backup" >&2
    return 1
  }
  [ ! -e "$backup_marker" ] || {
    echo "$signal/dumping left an incomplete backup volume" >&2
    return 1
  }
  if ! grep -Fq 'compose -f' "$docker_log" || ! grep -q ' start db' "$docker_log"; then
    echo "$signal/dumping did not restart the previous stack" >&2
    return 1
  fi
  ! grep -q 'WIPE_STARTED' "$docker_log" || {
    echo "$signal/dumping continued into replacement" >&2
    return 1
  }
}

assert_replacing_case() { # SIGNAL DOCKER_LOG UPGRADE_LOG BACKUP_MARKER
  local signal=$1 docker_log=$2 upgrade_log=$3 backup_marker=$4
  grep -q 'WIPE_STARTED' "$docker_log" || {
    echo "$signal/replacing did not reach wipe boundary" >&2
    return 1
  }
  grep -q 'Restoring the PostgreSQL' "$upgrade_log" || {
    echo "$signal/replacing did not explain rollback recovery" >&2
    return 1
  }
  ! grep -q 'NEW_STARTED' "$docker_log" || {
    echo "$signal/replacing continued after wipe signal" >&2
    return 1
  }
  grep -Fq "volume rm ${COMPOSE_PROJECT_NAME}_postgres_data_pg16_backup" "$docker_log" || {
    echo "$signal/replacing did not remove the rolled-back backup" >&2
    return 1
  }
  [ ! -e "$backup_marker" ] || {
    echo "$signal/replacing left the rolled-back backup volume" >&2
    return 1
  }
  grep -q ' start db' "$docker_log" || {
    echo "$signal/replacing did not restart the restored stack" >&2
    return 1
  }
}
