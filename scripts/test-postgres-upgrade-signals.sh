#!/usr/bin/env bash
# Regression for #809 (offending 7f6eb254): cancellation must abort each
# upgrade phase while preserving that phase's recovery contract.
# The exec shim introduced in 94c19b44 exposed Ubuntu 26.04/uutils timeout 0.10.0's status 2 on group SIGINT.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
upgrade="$root/deploy/scripts/upgrade-postgres-volume.sh"
compose_file="$root/deploy/docker-compose.yml"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

record_process_identity() {
  local pid=$1 identity_file=$2 stat rest
  local -a fields
  IFS= read -r stat 2>/dev/null <"/proc/$pid/stat" || return 1
  rest=${stat##*) }
  read -r -a fields <<<"$rest"
  printf '%s %s %s\n' "$pid" "${fields[2]}" "${fields[19]}" >>"$identity_file"
}
export -f record_process_identity

read_process_identity() {
  local pid=$1 expected_group=$2 expected_start=$3 stat rest
  local -a fields
  PROCESS_STATE=
  IFS= read -r stat 2>/dev/null <"/proc/$pid/stat" || return 1
  rest=${stat##*) }
  read -r -a fields <<<"$rest"
  [[ "${fields[2]}" = "$expected_group" && "${fields[19]}" = "$expected_start" ]] || return 1
  PROCESS_STATE=${fields[0]}
}

run_with_signal_supervisor() { # TIMEOUT KILL_AFTER COMMAND [ARG...]
  local timeout_after=$1 kill_after=$2
  local -a supervisor_command
  shift 2
  # shellcheck disable=SC2016 # Perl runs the single-quoted supervisor program.
  supervisor_command=(perl -e '
    use Errno qw(EINTR);
    use POSIX qw(:sys_wait_h setpgid);

    sub seconds {
      my ($value) = @_;
      $value =~ /^(\d+)(?:s)?$/ or die "invalid duration: $value";
      return 0 + $1;
    }

    my $timeout_seconds = seconds(shift @ARGV);
    my $kill_after_seconds = seconds(shift @ARGV);
    if (my $pid_file = $ENV{WRZDJ_SUPERVISOR_PID_FILE}) {
      open my $handle, ">", $pid_file or die "open supervisor pid file: $!";
      print {$handle} "$$\n" or die "write supervisor pid file: $!";
      close $handle or die "close supervisor pid file: $!";
    }
    my $child = fork();
    defined $child or die "fork: $!";
    if ($child == 0) {
      setpgid(0, 0) == 0 or die "setpgid: $!";
      $SIG{INT} = "DEFAULT";
      $SIG{TERM} = "DEFAULT";
      exec @ARGV or die "exec: $!";
    }

    my ($timed_out, $kill_sent, $term_sent, $external_signal, $leader_reaped, $leader_status);
    my $send_term = sub {
      my ($signal) = @_;
      return if $term_sent;
      $term_sent = 1;
      kill $signal, -$child;
      alarm($kill_after_seconds);
    };
    $SIG{INT} = sub { $external_signal ||= "INT"; $send_term->("INT"); };
    $SIG{TERM} = sub { $external_signal ||= "TERM"; $send_term->("TERM"); };
    $SIG{ALRM} = sub {
      if (!$term_sent) {
        $timed_out = 1;
        $send_term->("TERM");
      } else {
        if (kill 0, -$child) {
          kill "KILL", -$child;
          $kill_sent = 1;
        }
        alarm(0);
      }
    };
    alarm($timeout_seconds);

    while (1) {
      if (!$leader_reaped) {
        my $waited = waitpid($child, WNOHANG);
        if ($waited == $child) {
          $leader_status = $?;
          $leader_reaped = 1;
        } else {
          next if $waited == -1 && $! == EINTR;
          die "waitpid: $!" if $waited == -1;
        }
      }

      if ($leader_reaped) {
        if ($kill_sent) {
          alarm(0);
          exit($timed_out ? 137 : $external_signal eq "INT" ? 130 : 143);
        }
        if ($term_sent) {
          if (!kill 0, -$child) {
            alarm(0);
            exit($timed_out ? 124 : $external_signal eq "INT" ? 130 : 143);
          }
        } else {
          alarm(0);
          exit(128 + ($leader_status & 127)) if $leader_status & 127;
          exit($leader_status >> 8);
        }
      }

      select undef, undef, undef, 0.05;
    }
  ' -- "$timeout_after" "$kill_after" "$@")
  if [ "${WRZDJ_TEST_ISOLATE_SUPERVISOR:-0}" = 1 ]; then
    setsid "${supervisor_command[@]}"
  else
    "${supervisor_command[@]}"
  fi
}

cleanup_stuck_child() {
  local pid_file=$1 child_pid child_pgid child_start
  [ -s "$pid_file" ] || return 0
  while read -r child_pid child_pgid child_start; do
    [[ "$child_pid" =~ ^[0-9]+$ && "$child_pgid" =~ ^[0-9]+$ && "$child_start" =~ ^[0-9]+$ ]] || continue
    read_process_identity "$child_pid" "$child_pgid" "$child_start" || continue
    if [ "$child_pgid" != "$(ps -o pgid= -p "$$" | tr -d ' ')" ]; then
      kill -KILL -- "-$child_pgid" 2>/dev/null || true
    else
      kill -KILL "$child_pid" 2>/dev/null || true
    fi
  done <"$pid_file"
}

assert_child_stopped() {
  local label=$1 pid_file=$2 child_pid child_pgid child_start child_state attempt live_child
  if [ ! -s "$pid_file" ]; then
    echo "$label did not record its PID" >&2
    return 1
  fi
  for ((attempt = 0; attempt < 20; attempt++)); do
    live_child=
    while read -r child_pid child_pgid child_start; do
      read_process_identity "$child_pid" "$child_pgid" "$child_start" || continue
      child_state=$PROCESS_STATE
      case "$child_state" in
        Z*|X*) ;;
        *) live_child="$child_pid:$child_state"; break ;;
      esac
    done <"$pid_file"
    [ -z "$live_child" ] && return 0
    sleep 0.05
  done
  cleanup_stuck_child "$pid_file"
  echo "$label process $live_child is still running after timeout" >&2
  return 1
}

run_timeout_case() { # NAME TIMEOUT KILL_AFTER EXPECTED_STATUS COMMAND [ARG...]
  local name=$1 timeout_after=$2 kill_after=$3 expected_status=$4
  local case_dir="$scratch/$1" status
  shift 4
  mkdir -p "$case_dir"
  set +e
  run_with_signal_supervisor "$timeout_after" "$kill_after" "$@" \
    >"$case_dir/timeout.log" 2>&1
  status=$?
  set -e
  if [ "$status" -ne "$expected_status" ]; then
    cleanup_stuck_child "$case_dir/child.pid"
    echo "$name exited $status, expected $expected_status" >&2
    cat "$case_dir/timeout.log" >&2
    return 1
  fi
  assert_child_stopped "$name" "$case_dir/child.pid" || {
    cat "$case_dir/timeout.log" >&2
    return 1
  }
}

run_external_cancel_case() {
  local case_dir="$scratch/external-cancel" runner supervisor_pid status attempt
  mkdir -p "$case_dir"
  # shellcheck disable=SC2016 # The child shell expands its PID and path at runtime.
  WRZDJ_TEST_ISOLATE_SUPERVISOR=1 WRZDJ_SUPERVISOR_PID_FILE="$case_dir/supervisor.pid" \
    run_with_signal_supervisor 15s 1s bash -c \
      'record_process_identity "$BASHPID" "$1"; trap "exit 0" TERM; while :; do :; done' \
      bash "$case_dir/child.pid" >"$case_dir/supervisor.log" 2>&1 &
  runner=$!
  for ((attempt = 0; attempt < 100; attempt++)); do
    [ -s "$case_dir/supervisor.pid" ] && [ -s "$case_dir/child.pid" ] && break
    sleep 0.05
  done
  if [ ! -s "$case_dir/supervisor.pid" ] || [ ! -s "$case_dir/child.pid" ]; then
    echo 'external-cancel case did not start its supervisor and child' >&2
    cat "$case_dir/supervisor.log" >&2
    return 1
  fi

  read -r supervisor_pid <"$case_dir/supervisor.pid"
  kill -TERM -- "-$supervisor_pid"
  set +e
  wait "$runner"
  status=$?
  set -e
  if [ "$status" -ne 143 ]; then
    cleanup_stuck_child "$case_dir/child.pid"
    echo "external-cancel supervisor exited $status, expected 143" >&2
    cat "$case_dir/supervisor.log" >&2
    return 1
  fi
  assert_child_stopped 'external-cancel child' "$case_dir/child.pid" || {
    cat "$case_dir/supervisor.log" >&2
    return 1
  }
}

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
  PATH="$case_dir/bin:$PATH" run_with_signal_supervisor 15s 2s \
    bash "$upgrade" "$compose_file" >"$case_dir/upgrade.log" 2>&1 &
  local pid=$! status
  for ((attempt = 0; attempt < 100; attempt++)); do
    [ -e "$FAKE_DOCKER_READY" ] && break
    sleep 0.05
  done
  [ -e "$FAKE_DOCKER_READY" ] || {
    echo "$signal/$phase case never reached the signal boundary" >&2
    cat "$case_dir/upgrade.log" >&2
    cat "$FAKE_DOCKER_LOG" >&2
    return 1
  }
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
# shellcheck disable=SC2016 # The child shell expands its PID and path at runtime.
run_timeout_case cooperative 1s 1s 124 bash -c \
  'record_process_identity "$BASHPID" "$1"; trap "exit 0" TERM; while :; do :; done' \
  bash "$scratch/cooperative/child.pid"
# shellcheck disable=SC2016 # The child shell expands its PID and path at runtime.
run_timeout_case stuck 1s 1s 137 bash -c \
  'record_process_identity "$BASHPID" "$1"; trap "" TERM; while :; do :; done' \
  bash "$scratch/stuck/child.pid"
run_external_cancel_case
# shellcheck disable=SC2016 # The child shell expands its PID and path at runtime.
run_timeout_case leader-exits-first 1s 1s 137 bash -c \
  'record_process_identity "$BASHPID" "$1"; (record_process_identity "$BASHPID" "$1"; trap "" TERM; while :; do :; done) & trap "exit 0" TERM; while :; do :; done' \
  bash "$scratch/leader-exits-first/child.pid"
echo 'INT and TERM preserve upgrade recovery; timeout and external cancellation leave no live child group.'
