#!/usr/bin/env bash
set -euo pipefail

port_validation_dir="${BASH_SOURCE[0]%/*}"
[[ "$port_validation_dir" != "${BASH_SOURCE[0]}" ]] || port_validation_dir=.
# shellcheck source=port-validation.sh
source "$port_validation_dir/port-validation.sh"
unset port_validation_dir

if [ "$#" -eq 0 ]; then
  echo "Usage: cleanup-deploy-ports.sh PORT [PORT...]" >&2
  exit 2
fi

PORTS=()
for input_port in "$@"; do
  if ! PORT=$(normalize_port "$input_port"); then
    exit 2
  fi
  PORTS+=("$PORT")
done

for PORT in "${PORTS[@]}"; do

  echo "==> Checking for processes holding port $PORT..."
  if SS_OUTPUT=$(ss -tlnp 2>&1); then
    :
  else
    SS_STATUS=$?
    echo "Failed to inspect listening ports for port $PORT (ss exited $SS_STATUS): $SS_OUTPUT" >&2
    exit 1
  fi

  if PID_OUTPUT=$(awk -v port=":$PORT" '
    $4 ~ (port "$") {
      line = $0
      while (match(line, /pid=[0-9]+/)) {
        print substr(line, RSTART + 4, RLENGTH - 4)
        line = substr(line, RSTART + RLENGTH)
      }
    }
  ' <<< "$SS_OUTPUT" | sort -u); then
    :
  else
    PARSE_STATUS=$?
    echo "Failed to parse listening ports for port $PORT (pipeline exited $PARSE_STATUS)" >&2
    exit "$PARSE_STATUS"
  fi

  PIDS=()
  if [ -n "$PID_OUTPUT" ]; then
    mapfile -t PIDS <<< "$PID_OUTPUT"
  fi
  if [ "${#PIDS[@]}" -eq 0 ]; then
    echo "    Port $PORT is free"
    continue
  fi

  for PID in "${PIDS[@]}"; do
    PROC=$(ps -p "$PID" -o comm= 2>/dev/null || echo "unknown")
    echo "    Port $PORT held by PID $PID ($PROC) — killing"
    kill "$PID" 2>/dev/null || true
  done
  sleep 1

  for PID in "${PIDS[@]}"; do
    if kill -0 "$PID" 2>/dev/null; then
      echo "    PID $PID still alive — sending SIGKILL"
      kill -9 "$PID" 2>/dev/null || true
    fi
  done
done
