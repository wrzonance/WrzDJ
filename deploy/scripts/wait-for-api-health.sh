#!/usr/bin/env bash
set -euo pipefail

port_validation_dir="${BASH_SOURCE[0]%/*}"
[[ "$port_validation_dir" != "${BASH_SOURCE[0]}" ]] || port_validation_dir=.
# shellcheck source=port-validation.sh
source "$port_validation_dir/port-validation.sh"
unset port_validation_dir

epoch_realtime_to_ms() {
  local timestamp="${1//[^0-9]/}"
  printf '%s' "${timestamp:0:13}"
}

now_ms() {
  epoch_realtime_to_ms "$EPOCHREALTIME"
}

main() {
  if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: wait-for-api-health.sh COMPOSE_FILE PORT MAX_WAIT [VERSION]" >&2
    return 2
  fi

  local compose_file=$1 port_api=$2 max_wait=$3 version=${4:-}
  if [[ ! "$max_wait" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid maximum wait: $max_wait" >&2
    return 2
  fi
  if ! port_api=$(normalize_port "$port_api"); then
    return 2
  fi

  local started_ms deadline_ms remaining_ms curl_timeout elapsed_ms elapsed_seconds
  local sleep_ms sleep_seconds
  started_ms=$(now_ms)
  deadline_ms=$((started_ms + max_wait * 1000))

  while :; do
    remaining_ms=$((deadline_ms - $(now_ms)))
    [ "$remaining_ms" -gt 0 ] || break
    printf -v curl_timeout '%d.%03d' "$((remaining_ms / 1000))" "$((remaining_ms % 1000))"
    if curl --max-time "$curl_timeout" -sf \
      "http://127.0.0.1:${port_api}/health" >/dev/null 2>&1; then
      elapsed_ms=$(($(now_ms) - started_ms))
      printf -v elapsed_seconds '%d.%d' "$((elapsed_ms / 1000))" "$(((elapsed_ms % 1000) / 100))"
      echo "    API healthy after ${elapsed_seconds}s"
      return 0
    fi
    if [ "$remaining_ms" -eq "$((max_wait * 1000))" ]; then
      printf '    Waiting'
    fi
    printf '.'
    remaining_ms=$((deadline_ms - $(now_ms)))
    [ "$remaining_ms" -gt 0 ] || break
    sleep_ms=$((remaining_ms < 2000 ? remaining_ms : 2000))
    printf -v sleep_seconds '%d.%03d' "$((sleep_ms / 1000))" "$((sleep_ms % 1000))"
    sleep "$sleep_seconds"
  done

  echo ""
  echo "ERROR: API did not become healthy within ${max_wait}s" >&2
  echo "==> API logs:" >&2
  if [ -n "$version" ]; then
    WRZDJ_VERSION="$version" docker compose -f "$compose_file" logs --tail=20 api
  else
    docker compose -f "$compose_file" logs --tail=20 api
  fi
  return 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
