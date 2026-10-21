#!/usr/bin/env bash
# Service cleanup must report failed optional service changes honestly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_MODULE="${SCRIPT_DIR}/../lib/setup-platform.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cat > "$WORK_DIR/run.sh" <<'RUN'
set -euo pipefail
info() { printf 'INFO %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; }
systemctl() {
  if [ "$1" = is-enabled ]; then
    return 0
  fi
  printf '%s\n' "$3" >> "$TRACE_FILE"
  return 1
}
source "$PLATFORM_MODULE"
disable_unnecessary_services
RUN

if TRACE_FILE="$WORK_DIR/disabled-services" PLATFORM_MODULE="$PLATFORM_MODULE" \
  bash "$WORK_DIR/run.sh" > "$WORK_DIR/output"; then
  :
else
  echo 'service cleanup should continue after optional disable failures' >&2
  exit 1
fi

for service in bluetooth.service hciuart.service triggerhappy.service; do
  grep -Fxq "$service" "$WORK_DIR/disabled-services"
  grep -Fq "WARN   Could not disable ${service}" "$WORK_DIR/output"
done
if grep -Fq 'INFO   Disabled:' "$WORK_DIR/output"; then
  echo 'failed systemctl operations must not be reported as successful disables' >&2
  exit 1
fi

echo 'Kiosk optional service cleanup reports failures accurately.'
