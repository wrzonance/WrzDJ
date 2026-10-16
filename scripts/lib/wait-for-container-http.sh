#!/usr/bin/env bash

wait_for_container_http() {
  local container=${1:?container is required}
  local url=${2:?URL is required}
  local description=${3:?description is required}
  local attempts=${WRZDJ_READINESS_ATTEMPTS:-30}
  local delay=${WRZDJ_READINESS_DELAY:-1}
  local attempt

  if ! [[ $attempts =~ ^[1-9][0-9]*$ ]] || \
    ! [[ $delay =~ ^[0-9]+([.][0-9]+)?$|^[.][0-9]+$ ]]; then
    printf 'Invalid readiness configuration: attempts=%s delay=%s.\n' "$attempts" "$delay" >&2
    return 2
  fi

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if docker exec "$container" curl --fail --silent --max-time 1 "$url" >/dev/null; then
      return 0
    fi
    if [ "$attempt" -lt "$attempts" ]; then
      sleep "$delay"
    fi
  done

  echo "$description did not become ready after $attempts attempts." >&2
  return 1
}
