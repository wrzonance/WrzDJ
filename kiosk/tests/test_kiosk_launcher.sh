#!/usr/bin/env bash
# Sandbox the installed login launcher and tty1 autologin override.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIOSK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SETUP_ENTRYPOINT="$KIOSK_DIR/setup.sh"
SETUP_RUNTIME_SH="$KIOSK_DIR/lib/setup-runtime.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# Refuse to execute installer functions unless all destination paths are redirected.
if ! grep -q 'KIOSK_ROOT' "$SETUP_RUNTIME_SH"; then
    echo 'installer functions do not yet support a sandbox root' >&2
    exit 1
fi

export KIOSK_ROOT="$WORK_DIR/root"
export KIOSK_USER=kiosk
export KIOSK_ROTATION=90
export WRZDJ_KIOSK_CONFIG="$KIOSK_ROOT/etc/wrzdj-kiosk.conf"
export CALL_TRACE="$WORK_DIR/calls"
export CAGE_ARGS="$WORK_DIR/cage-args"
export CURL_COUNT="$WORK_DIR/curl-count"
export CURL_ARGS="$WORK_DIR/curl-args"
mkdir -p "$WORK_DIR/bin" "$KIOSK_ROOT/home/kiosk" "$KIOSK_ROOT/etc"
: > "$CALL_TRACE"
: > "$CAGE_ARGS"
printf 'KIOSK_ROTATION="90"\nEXTRA_CHROMIUM_FLAGS="--test=one --literal=*"\n' > "$WRZDJ_KIOSK_CONFIG"

cat > "$WORK_DIR/bin/curl" <<'CURL'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$CURL_ARGS"
count=0
[[ -f "$CURL_COUNT" ]] && read -r count < "$CURL_COUNT"
count=$((count + 1))
printf '%s\n' "$count" > "$CURL_COUNT"
[[ "${CURL_ALWAYS_FAIL:-0}" != 1 ]]
CURL
cat > "$WORK_DIR/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
:
SLEEP
cat > "$WORK_DIR/bin/cage" <<'CAGE'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$CAGE_ARGS"
CAGE
chmod +x "$WORK_DIR/bin/"*
export PATH="$WORK_DIR/bin:$PATH"

info() { :; }
chown() { printf 'chown %s\n' "$*" >> "$CALL_TRACE"; }
systemctl() { printf 'systemctl %s\n' "$*" >> "$CALL_TRACE"; }
# shellcheck disable=SC1090 # entrypoint path is resolved from this test script at runtime
source "$SETUP_ENTRYPOINT"

install_kiosk_launcher
profile="$KIOSK_ROOT/home/kiosk/.bash_profile"
[[ -f "$profile" ]]

run_profile() {
    local tty_name="$1"
    shift
    # Keep the generated login-session expansion literal until the child Bash runs it.
    # shellcheck disable=SC2016
    env PROFILE="$profile" TEST_TTY="$tty_name" "$@" bash -c '
        tty() { printf "%s\n" "$TEST_TTY"; }
        source "$PROFILE"
    '
}

# Non-tty1 login sessions must not start Cage.
if run_profile /dev/tty2 >/dev/null; then :; else
    echo 'launcher failed outside tty1' >&2
    exit 1
fi
[[ ! -s "$CAGE_ARGS" ]]
[[ ! -f "$CURL_COUNT" ]]

# A portal outage is bounded, reported as failure, and never starts Cage.
rm -f "$CURL_COUNT"
if CURL_ALWAYS_FAIL=1 WRZDJ_PORTAL_WAIT_ATTEMPTS=3 \
    run_profile /dev/tty1 >/dev/null 2>&1; then
    echo 'launcher unexpectedly succeeded while portal was unavailable' >&2
    exit 1
fi
[[ "$(cat "$CURL_COUNT")" == 3 ]]
grep -Fxq -- '--connect-timeout' "$CURL_ARGS"
grep -Fxq -- '2' "$CURL_ARGS"
grep -Fxq -- '--max-time' "$CURL_ARGS"
grep -Fxq -- '5' "$CURL_ARGS"
grep -Fxq -- 'http://localhost/api/ready' "$CURL_ARGS"
[[ ! -s "$CAGE_ARGS" ]]

# A ready portal launches Chromium with safe, literal extra flags and the local gateway URL.
rm -f "$CURL_COUNT"
run_profile /dev/tty1
 grep -Fxq -- '--test=one' "$CAGE_ARGS"
grep -Fxq -- '--literal=*' "$CAGE_ARGS"
grep -Fxq -- 'http://localhost' "$CAGE_ARGS"

# Rotation remains a boot-config setting and maps to the requested firmware value.
boot_config="$WORK_DIR/config.txt"
printf 'dtoverlay=vc4-kms-v3d\n' > "$boot_config"
configure_rotation "$boot_config"
grep -Fxq 'display_rotate=1' "$boot_config"

# Autologin is installed only for tty1 and names the configured account.
configure_autologin
login_override="$KIOSK_ROOT/etc/systemd/system/getty@tty1.service.d/autologin.conf"
[[ -f "$login_override" ]]
# The getty unit must receive the literal systemd $TERM variable.
# shellcheck disable=SC2016
grep -Fxq 'ExecStart=-/sbin/agetty --autologin kiosk --noclear %I $TERM' "$login_override"
[[ ! -e "$KIOSK_ROOT/etc/systemd/system/getty@tty2.service.d/autologin.conf" ]]
grep -Fxq 'systemctl daemon-reload' "$CALL_TRACE"
echo 'Kiosk launcher readiness, tty gating, flags, rotation, and autologin passed.'
