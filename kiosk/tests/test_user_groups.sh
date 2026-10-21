#!/usr/bin/env bash
# Verify a failed device-group update cannot masquerade as successful setup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_PLATFORM_SH="${SCRIPT_DIR}/../lib/setup-platform.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

{
  printf 'set -euo pipefail\n'
  printf 'KIOSK_USER=kiosk\n'
  printf 'id() { return 0; }\n'
  printf 'getent() { return 0; }\n'
  printf 'info() { :; }\n'
  # shellcheck disable=SC2016 # This source string is emitted into the isolated test process.
  printf 'usermod() { printf "%%s\\n" "$*" >> "$TRACE_FILE"; [ "$2" != video ]; }\n'
  printf 'die() { printf "%%s\\n" "$*" >&2; exit 1; }\n'
  printf 'source %q\n' "$SETUP_PLATFORM_SH"
  printf 'create_kiosk_user\n'
} > "$WORK_DIR/run.sh"

if TRACE_FILE="$WORK_DIR/usermod.log" bash "$WORK_DIR/run.sh" \
  > "$WORK_DIR/output.log" 2>&1; then
  echo 'setup should fail when required device-group membership cannot be applied' >&2
  exit 1
fi
grep -Fxq 'Failed to add '\''kiosk'\'' to '\''video'\'' group' "$WORK_DIR/output.log"
grep -Fxq -- '-aG input kiosk' "$WORK_DIR/usermod.log"
grep -Fxq -- '-aG video kiosk' "$WORK_DIR/usermod.log"
if grep -Fq -- '-aG render kiosk' "$WORK_DIR/usermod.log"; then
  echo 'setup must stop after the first failed required group update' >&2
  exit 1
fi

echo 'Kiosk group membership failures are reported and stop setup.'
