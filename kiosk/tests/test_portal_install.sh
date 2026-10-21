#!/usr/bin/env bash
# Sandbox the portal installer and verify its systemd/runtime wiring.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIOSK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SETUP_RUNTIME_SH="$KIOSK_DIR/lib/setup-runtime.sh"
SERVICE_FILE="$KIOSK_DIR/systemd/wrzdj-wifi-portal.service"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$WORK_DIR/bin"
cat > "$WORK_DIR/bin/mkdir" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
mapped=()
for arg in "$@"; do
  if [[ "$arg" = /usr/local/* || "$arg" = /etc/* ]]; then
    arg="$SANDBOX_ROOT$arg"
  fi
  mapped+=("$arg")
done
/bin/mkdir "${mapped[@]}"
MOCK
cat > "$WORK_DIR/bin/install" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
mode=644
if [ "$1" = -m ]; then
  mode=$2
  shift 2
fi
destination=${!#}
source_count=$(( $# - 1 ))
sources=("${@:1:source_count}")
if [[ "$destination" = /usr/local/* || "$destination" = /etc/* ]]; then
  destination="$SANDBOX_ROOT$destination"
fi
if [ "$source_count" -gt 1 ]; then
  /bin/mkdir -p "$destination"
  for source in "${sources[@]}"; do
    /usr/bin/install -m "$mode" "$source" "$destination/"
  done
else
  /bin/mkdir -p "$(dirname "$destination")"
  /usr/bin/install -m "$mode" "${sources[0]}" "$destination"
fi
MOCK
cat > "$WORK_DIR/bin/cp" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
source=$1
destination=$2
if [[ "$destination" = /usr/local/* || "$destination" = /etc/* ]]; then
  destination="$SANDBOX_ROOT$destination"
fi
/bin/mkdir -p "$(dirname "$destination")"
/bin/cp -- "$source" "$destination"
MOCK
cat > "$WORK_DIR/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$SANDBOX_LOG"
if [[ "${SYSTEMCTL_FAIL_DISABLE:-0}" = 1 && "$*" = 'disable --now wrzdj-kiosk.service' ]]; then
  exit 1
fi
MOCK
cat > "$WORK_DIR/bin/rm" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
mapped=()
for arg in "$@"; do
  if [[ "$arg" = /etc/* || "$arg" = /usr/local/* ]]; then
    arg="$SANDBOX_ROOT$arg"
  fi
  mapped+=("$arg")
done
/bin/rm "${mapped[@]}"
MOCK
chmod +x "$WORK_DIR/bin/mkdir" "$WORK_DIR/bin/install" "$WORK_DIR/bin/cp" \
  "$WORK_DIR/bin/systemctl" "$WORK_DIR/bin/rm"

export SANDBOX_ROOT="$WORK_DIR/root"
export SANDBOX_LOG="$WORK_DIR/systemctl.log"
export KIOSK_ROOT="$SANDBOX_ROOT"
export KIOSK_USER=kiosk
export PATH="$WORK_DIR/bin:$PATH"
mkdir -p "$SANDBOX_ROOT/etc/systemd/system"
mkdir -p "$SANDBOX_ROOT/home/kiosk"
cat > "$SANDBOX_ROOT/etc/systemd/system/wrzdj-kiosk.service" <<'LEGACY'
[Unit]
Description=WrzDJ Kiosk Display
# This file is kept as a reference for Chromium flags and security hardening.
LEGACY

{
  printf 'set -euo pipefail\n'
  printf 'SCRIPT_DIR=%q\n' "$KIOSK_DIR"
  printf 'KIOSK_ROOT=%q\n' "$SANDBOX_ROOT"
  printf 'KIOSK_USER=kiosk\n'
  printf 'info() { :; }\n'
  printf 'chown() { :; }\n'
  printf 'source %q\n' "$SETUP_RUNTIME_SH"
  printf 'install_services\n'
  printf 'install_kiosk_launcher\n'
  printf 'install_wifi_portal\n'
  printf 'configure_autologin\n'
} > "$WORK_DIR/run-installer.sh"
bash "$WORK_DIR/run-installer.sh"

installed="$SANDBOX_ROOT/usr/local/lib/wrzdj"
while IFS= read -r module; do
  test -f "$installed/$module"
done < <(find "$KIOSK_DIR/wifi-portal" -maxdepth 1 -type f -name 'portal*.py' -printf '%f\n' | sort)
test -x "$installed/portal.py"

unit_dir="$SANDBOX_ROOT/etc/systemd/system"
test ! -e "$unit_dir/wrzdj-kiosk.service"
test -f "$unit_dir/wrzdj-kiosk-watchdog.service"
test -f "$unit_dir/wrzdj-kiosk-watchdog.timer"
test -f "$unit_dir/wrzdj-wifi-portal.service"
if grep -Eq 'wrzdj-kiosk\.service' "$unit_dir/wrzdj-wifi-portal.service"; then
  echo 'portal service must not depend on the retired kiosk unit' >&2
  exit 1
fi
grep -Fxq 'enable wrzdj-kiosk-watchdog.timer' "$SANDBOX_LOG"
grep -Fxq 'enable wrzdj-wifi-portal.service' "$SANDBOX_LOG"
grep -Fxq 'disable --now wrzdj-kiosk.service' "$SANDBOX_LOG"
if grep -Eq 'enable .*wrzdj-kiosk\.service' "$SANDBOX_LOG"; then
  echo 'the retired kiosk systemd unit must not be enabled' >&2
  exit 1
fi

launcher="$SANDBOX_ROOT/home/kiosk/.bash_profile"
test -f "$launcher"
# shellcheck disable=SC2016 # Assert the literal condition emitted into the launcher.
grep -Fq '[ "$(tty)" = "/dev/tty1" ]' "$launcher"
grep -Fxq '        http://localhost' "$launcher"
autologin="$unit_dir/getty@tty1.service.d/autologin.conf"
# shellcheck disable=SC2016 # Assert systemd receives its literal $TERM variable.
grep -Fxq 'ExecStart=-/sbin/agetty --autologin kiosk --noclear %I $TERM' "$autologin"

# A locally customized unit is not owned by setup and must remain untouched.
printf '[Unit]\nDescription=Local kiosk service customization\n' \
  > "$unit_dir/wrzdj-kiosk.service"
{
  printf 'set -euo pipefail\n'
  printf 'SCRIPT_DIR=%q\n' "$KIOSK_DIR"
  printf 'info() { :; }\n'
  printf 'warn() { printf "%%s\\n" "$*"; }\n'
  printf 'source %q\n' "$SETUP_RUNTIME_SH"
  printf 'install_services\n'
} > "$WORK_DIR/run-cleanup.sh"
bash "$WORK_DIR/run-cleanup.sh" > "$WORK_DIR/cleanup-output"
grep -Fq 'Description=Local kiosk service customization' "$unit_dir/wrzdj-kiosk.service"
grep -Fq 'Existing kiosk service has local changes' "$WORK_DIR/cleanup-output"

# If systemd cannot stop an owned legacy service, keep the unit for recovery.
cat > "$unit_dir/wrzdj-kiosk.service" <<'LEGACY'
[Unit]
Description=WrzDJ Kiosk Display
# This file is kept as a reference for Chromium flags and security hardening.
LEGACY
SYSTEMCTL_FAIL_DISABLE=1 bash "$WORK_DIR/run-cleanup.sh" > "$WORK_DIR/cleanup-failure-output"
test -f "$unit_dir/wrzdj-kiosk.service"
grep -Fq 'Could not disable retired kiosk service' "$WORK_DIR/cleanup-failure-output"

installed_service="$SANDBOX_ROOT/etc/systemd/system/wrzdj-wifi-portal.service"
cmp "$SERVICE_FILE" "$installed_service"
service_entry=$(sed -n 's|^ExecStart=/usr/bin/python3 ||p' "$installed_service")
test "$service_entry" = /usr/local/lib/wrzdj/portal.py
grep -Fxq 'daemon-reload' "$SANDBOX_LOG"
grep -Fxq 'enable wrzdj-wifi-portal.service' "$SANDBOX_LOG"

PYTHONPATH="$installed" python3 - "$installed" <<'PY'
import importlib
import sys
from pathlib import Path

install_dir = Path(sys.argv[1])
for module_path in sorted(install_dir.glob("portal*.py")):
    importlib.import_module(module_path.stem)
PY

echo 'WiFi portal install, systemd entrypoint, and runtime imports passed.'
