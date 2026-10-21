#!/usr/bin/env bash
# Verify setup.sh is source-safe and main runs the installation stages in order.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SH="${SCRIPT_DIR}/../setup.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# The entrypoint must load each setup layer while remaining safe to source.
# shellcheck disable=SC1090
source "$SETUP_SH"
for function in load_config install_packages install_services install_kiosk_launcher \
    install_wifi_portal configure_autologin disable_unnecessary_services; do
  declare -F "$function" >/dev/null || {
    printf 'setup function was not loaded: %s\n' "$function" >&2
    exit 1
  }
done

export TRACE_FILE="$WORK_DIR/stages"
: > "$TRACE_FILE"

{
  printf 'set -euo pipefail\n'
  printf 'source %q\n' "$SETUP_SH"
  # The generated workflow must keep these expansions literal until Bash runs it.
  # shellcheck disable=SC2016
  printf 'test ! -s "$TRACE_FILE"\n'
  # shellcheck disable=SC2016
  printf 'record_stage() { printf "%%s\\n" "$1" >> "$TRACE_FILE"; }\n'
  for stage in \
    preflight load_config install_packages create_kiosk_user configure_wifi \
    configure_rotation install_services install_kiosk_launcher install_wifi_portal \
    write_config disable_screen_blanking configure_autologin \
    disable_unnecessary_services set_hostname print_summary; do
    printf '%s() { record_stage %q; }\n' "$stage" "$stage"
  done
  printf 'read() { answer=n; }\n'
  printf 'main\n'
} > "$WORK_DIR/workflow.sh"
bash "$WORK_DIR/workflow.sh" >/dev/null

cat > "$WORK_DIR/expected-stages" <<'STAGES'
preflight
load_config
install_packages
create_kiosk_user
configure_wifi
configure_rotation
install_services
install_kiosk_launcher
install_wifi_portal
write_config
disable_screen_blanking
configure_autologin
disable_unnecessary_services
set_hostname
print_summary
STAGES
cmp "$WORK_DIR/expected-stages" "$TRACE_FILE"
echo 'Kiosk setup source guard and orchestration order passed.'
