#!/usr/bin/env bash

# Print a decimal port only when it is a valid TCP/UDP port number.
normalize_port() {
  local port="$1" normalized
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    echo "Invalid port: $port (must be an integer from 1 through 65535)" >&2
    return 1
  fi

  normalized="${port#"${port%%[!0]*}"}"
  if [[ -z "$normalized" ]] || (( ${#normalized} > 5 )) ||
    (( 10#$normalized < 1 || 10#$normalized > 65535 )); then
    echo "Invalid port: $port (must be an integer from 1 through 65535)" >&2
    return 1
  fi
  printf '%d' "$((10#$normalized))"
}
