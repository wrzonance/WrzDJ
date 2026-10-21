#!/usr/bin/env bash
# Unit tests for setup.sh pure logic functions.
# Tests config parsing, URL validation, rotation mapping, and hostname escaping.
#
# Usage:
#   bash kiosk/tests/test_setup.sh
#
# These tests source setup.sh functions in a sandbox (no root, no Pi needed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SH="${SCRIPT_DIR}/../setup.sh"
SETUP_CONFIG_SH="${SCRIPT_DIR}/../lib/setup-config.sh"

# ---------- test harness ----------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    TESTS_RUN=$((TESTS_RUN + 1))
    printf '  \033[32m✓\033[0m %s\n' "$1"
}

fail() {
    TESTS_FAILED=$((TESTS_FAILED + 1))
    TESTS_RUN=$((TESTS_RUN + 1))
    printf '  \033[31m✗\033[0m %s\n    Expected: %s\n    Got:      %s\n' "$1" "$2" "$3"
}

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        pass "$desc"
    else
        fail "$desc" "$expected" "$actual"
    fi
}

assert_ne() {
    local desc="$1" unexpected="$2" actual="$3"
    if [ "$unexpected" != "$actual" ]; then
        pass "$desc"
    else
        fail "$desc" "not $unexpected" "$actual"
    fi
}

run_load_config() {
    # shellcheck disable=SC2016 # The isolated loader process owns these positional parameters.
    bash -c '
        set -euo pipefail
        info() { :; }
        warn() { :; }
        die() { printf "DIE: %s\\n" "$*" >&2; exit 1; }
        BOOT_CONF="$1"
        SCRIPT_DIR=/nonexistent
        source "$2"
        load_config
        printf "%s" "$KIOSK_URL"
    ' setup-test "$1" "$SETUP_CONFIG_SH"
}

assert_load_config_rejects_url() {
    local description="$1" url="$2" config output
    config=$(mktemp)
    printf 'KIOSK_URL=%s\n' "$url" > "$config"

    if output=$(run_load_config "$config" 2>&1); then
        fail "$description" "load_config rejects the URL" "load_config succeeded"
    elif [[ "$output" == *"DIE: KIOSK_URL must start with http:// or https://"* ]]; then
        pass "$description"
    else
        fail "$description" "production URL validation error" "$output"
    fi

    rm -f "$config"
}

assert_load_config_defaults_empty_url() {
    local config output
    config=$(mktemp)
    printf 'KIOSK_URL=\n' > "$config"
    output=$(run_load_config "$config")
    assert_eq "empty KIOSK_URL uses the configured default" \
        "https://app.wrzdj.com/kiosk-pair" "$output"
    rm -f "$config"
}

section() {
    printf '\n\033[1;36m%s\033[0m\n' "$1"
}

# ---------- source the configuration module ----------

# Source modules in an isolated shell process instead of slicing function text.
# shellcheck disable=SC2329 # Sourced configuration functions call this stub indirectly.
info()  { :; }
# shellcheck disable=SC2329 # Sourced configuration functions call this stub indirectly.
warn()  { :; }
# shellcheck disable=SC2329 # Sourced configuration functions call this stub indirectly.
error() { :; }
# shellcheck disable=SC2329 # Sourced configuration functions call this stub indirectly.
die()   { echo "DIE: $*" >&2; return 1; }

# Load configuration functions at the process boundary.
# shellcheck disable=SC1090 # module path is resolved from this test script at runtime
source "$SETUP_CONFIG_SH"

BOOT_CONF="/boot/firmware/wrzdj-kiosk.conf"

# ---------- parse_config_file tests ----------

section "parse_config_file()"

# Test: reads basic key=value
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
KIOSK_URL=https://example.com
HOTSPOT_SSID=TestNet
HOTSPOT_PASSWORD=secret
EOF
KIOSK_URL="" HOTSPOT_SSID="" HOTSPOT_PASSWORD=""
parse_config_file "$tmp"
assert_eq "reads KIOSK_URL" "https://example.com" "$KIOSK_URL"
assert_eq "reads HOTSPOT_SSID" "TestNet" "$HOTSPOT_SSID"
assert_eq "reads HOTSPOT_PASSWORD" "secret" "$HOTSPOT_PASSWORD"
rm -f "$tmp"

# Test: reads a final config setting without a trailing newline.
tmp=$(mktemp)
printf 'KIOSK_URL=https://unterminated.example' > "$tmp"
KIOSK_URL=""
parse_config_file "$tmp"
assert_eq "reads final setting without newline" "https://unterminated.example" "$KIOSK_URL"
rm -f "$tmp"

# Test: ignores comments
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
# This is a comment
HOTSPOT_SSID=NotComment
  # Indented comment
EOF
HOTSPOT_SSID=""
parse_config_file "$tmp"
assert_eq "ignores comments" "NotComment" "$HOTSPOT_SSID"
rm -f "$tmp"

# Test: handles blank lines
tmp=$(mktemp)
cat > "$tmp" <<'EOF'

HOTSPOT_SSID=AfterBlank

EOF
HOTSPOT_SSID=""
parse_config_file "$tmp"
assert_eq "handles blank lines" "AfterBlank" "$HOTSPOT_SSID"
rm -f "$tmp"

# Test: strips surrounding quotes
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
HOTSPOT_SSID="Quoted Value"
EOF
HOTSPOT_SSID=""
parse_config_file "$tmp"
assert_eq "strips quotes" "Quoted Value" "$HOTSPOT_SSID"
rm -f "$tmp"

# Test: rejects unknown keys (should not set anything)
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
UNKNOWN_KEY=badvalue
HOTSPOT_SSID=GoodValue
EOF
HOTSPOT_SSID=""
parse_config_file "$tmp"
assert_eq "ignores unknown keys" "GoodValue" "$HOTSPOT_SSID"
rm -f "$tmp"

# Test: all allowed keys
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
KIOSK_URL=https://test.com
KIOSK_ROTATION=90
WIFI_SSID=mynet
WIFI_PASSWORD=mypass
WIFI_COUNTRY=GB
EXTRA_CHROMIUM_FLAGS=--flag
HOTSPOT_SSID=hs
HOTSPOT_PASSWORD=hp
EOF
KIOSK_URL="" KIOSK_ROTATION="" WIFI_SSID="" WIFI_PASSWORD="" WIFI_COUNTRY=""
EXTRA_CHROMIUM_FLAGS="" HOTSPOT_SSID="" HOTSPOT_PASSWORD=""
parse_config_file "$tmp"
assert_eq "KIOSK_URL allowed" "https://test.com" "$KIOSK_URL"
assert_eq "KIOSK_ROTATION allowed" "90" "$KIOSK_ROTATION"
assert_eq "WIFI_SSID allowed" "mynet" "$WIFI_SSID"
assert_eq "WIFI_PASSWORD allowed" "mypass" "$WIFI_PASSWORD"
assert_eq "WIFI_COUNTRY allowed" "GB" "$WIFI_COUNTRY"
assert_eq "EXTRA_CHROMIUM_FLAGS allowed" "--flag" "$EXTRA_CHROMIUM_FLAGS"
assert_eq "HOTSPOT_SSID allowed" "hs" "$HOTSPOT_SSID"
assert_eq "HOTSPOT_PASSWORD allowed" "hp" "$HOTSPOT_PASSWORD"
rm -f "$tmp"

# Test: preserves the hotspot password from a final line without a newline.
tmp=$(mktemp)
printf 'HOTSPOT_PASSWORD="preserved-without-newline"' > "$tmp"
HOTSPOT_PASSWORD=""
prepare_hotspot_config "$tmp"
assert_eq "preserves final hotspot password without newline" \
    "preserved-without-newline" "$HOTSPOT_PASSWORD"
rm -f "$tmp"

# Regression for baseline 57cfcdc6867f: a whitespace-padded local key was missed,
# causing setup to replace an existing hotspot password when boot config omitted it.
KIOSK_ROOT=$(mktemp -d)
mkdir -p "$KIOSK_ROOT/boot"
BOOT_CONF="$KIOSK_ROOT/boot/wrzdj-kiosk.conf"
CONF_FILE="$KIOSK_ROOT/wrzdj-kiosk.conf"
: > "$BOOT_CONF"
printf 'HOTSPOT_PASSWORD = "  preserve this literal  "\n' > "$CONF_FILE"
HOTSPOT_PASSWORD=""
load_config
prepare_hotspot_config "$CONF_FILE"
assert_eq "preserves quoted local hotspot password after empty boot config" \
    "  preserve this literal  " "$HOTSPOT_PASSWORD"
rm -rf "$KIOSK_ROOT"

# ---------- load_config tests ----------

section "load_config()"

# Test: defaults when no config files exist
# Override file checks to return false
BOOT_CONF="/nonexistent/boot.conf"
SCRIPT_DIR="/nonexistent/dir"
load_config
assert_eq "default KIOSK_URL" "https://app.wrzdj.com/kiosk-pair" "$KIOSK_URL"
assert_eq "default KIOSK_ROTATION" "0" "$KIOSK_ROTATION"
assert_eq "default WIFI_COUNTRY" "US" "$WIFI_COUNTRY"

# Test: URL validation — valid https
tmp=$(mktemp)
echo "KIOSK_URL=https://valid.com" > "$tmp"
BOOT_CONF="$tmp"
SCRIPT_DIR="/nonexistent"
load_config
assert_eq "valid https URL accepted" "https://valid.com" "$KIOSK_URL"
rm -f "$tmp"

# Test: URL validation — valid http
tmp=$(mktemp)
echo "KIOSK_URL=http://192.168.1.5:3000" > "$tmp"
BOOT_CONF="$tmp"
load_config
assert_eq "valid http URL accepted" "http://192.168.1.5:3000" "$KIOSK_URL"
rm -f "$tmp"

# Regression coverage for commit 57cfcdc6867f: exercise URL validation through load_config().
assert_load_config_rejects_url "invalid URL scheme rejected (ftp://)" "ftp://evil.com"
assert_load_config_rejects_url "javascript: URL rejected" "javascript:alert(1)"
assert_load_config_rejects_url "data: URL rejected" "data:text/html,<h1>hi</h1>"
assert_load_config_defaults_empty_url

# Test: rotation validation — valid values
BOOT_CONF="/nonexistent"
for rot in 0 90 180 270; do
    tmp=$(mktemp)
    echo "KIOSK_ROTATION=$rot" > "$tmp"
    BOOT_CONF="$tmp"
    load_config
    assert_eq "rotation $rot accepted" "$rot" "$KIOSK_ROTATION"
    rm -f "$tmp"
done

# Test: rotation validation — invalid value defaults to 0
tmp=$(mktemp)
echo "KIOSK_ROTATION=45" > "$tmp"
# shellcheck disable=SC2034 # The evaluated load_config function reads BOOT_CONF.
BOOT_CONF="$tmp"
load_config
assert_eq "invalid rotation defaults to 0" "0" "$KIOSK_ROTATION"

section "print_summary URL instructions"
KIOSK_URL="https://portal.example/pair"
KIOSK_ROTATION=0
# These globals are consumed by print_summary from the sourced config module.
# shellcheck disable=SC2034
KIOSK_USER=kiosk
HOTSPOT_SSID=TestNet
HOTSPOT_PASSWORD=test-password
# shellcheck disable=SC2034
CONF_FILE=/etc/wrzdj-kiosk.conf
SCRIPT_DIR=/opt/wrzdj/kiosk
summary="$(print_summary)"
if [[ "$summary" == *"Launcher:  http://localhost (local Wi-Fi portal)"* && \
    "$summary" == *"Portal URL: https://portal.example/pair"* && \
    "$summary" == *"sudo systemctl restart wrzdj-wifi-portal getty@tty1"* ]]; then
    pass "explains portal URL and restarts portal plus tty1 launcher"
else
    fail "explains portal URL and restarts portal plus tty1 launcher" \
        "portal URL, local launcher, both restarts" "$summary"
fi
if [[ "$summary" != *"$HOTSPOT_PASSWORD"* ]]; then
    pass "does not print hotspot password to installer output"
else
    fail "does not print hotspot password to installer output" \
        "password absent" "$summary"
fi
rm -f "$tmp"

# ---------- rotation value mapping ----------

section "configure_rotation() mapping"

# Test the production rotation function against a temporary firmware config.
for deg_val in "90:1" "180:2" "270:3"; do
    deg="${deg_val%%:*}"
    expected="${deg_val##*:}"
    tmp=$(mktemp)
    printf 'dtoverlay=vc4-kms-v3d\ndisplay_rotate=9\n' > "$tmp"
    KIOSK_ROTATION="$deg" bash -c 'source "$1"; configure_rotation "$2"' \
        rotation-test "$SETUP_SH" "$tmp"
    actual="$(sed -n 's/^display_rotate=//p' "$tmp")"
    assert_eq "rotation $deg → display_rotate=$expected" "$expected" "$actual"
    rm -f "$tmp"
done

# ---------- hostname regex escaping ----------

section "hostname regex escaping"

# Test: simple hostname (no special chars)
current="raspberrypi"
# shellcheck disable=SC2016 # The dollar sign is a literal regex anchor in sed's expression.
escaped="$(printf '%s' "$current" | sed 's/[.[\*^$()+?{|\\]/\\&/g')"
assert_eq "simple hostname unchanged" "raspberrypi" "$escaped"

# Test: hostname with dot
current="my.host"
# shellcheck disable=SC2016 # The dollar sign is a literal regex anchor in sed's expression.
escaped="$(printf '%s' "$current" | sed 's/[.[\*^$()+?{|\\]/\\&/g')"
assert_eq "dot escaped" 'my\.host' "$escaped"

# Test: hostname with special regex chars
current="host(name)"
# shellcheck disable=SC2016 # The dollar sign is a literal regex anchor in sed's expression.
escaped="$(printf '%s' "$current" | sed 's/[.[\*^$()+?{|\\]/\\&/g')"
# escaped should contain backslash-paren
assert_ne "parens escaped" "host(name)" "$escaped"

# ---------- summary ----------

printf '\n\033[1m─── Results ───\033[0m\n'
printf 'Total: %d  Passed: %d  Failed: %d\n\n' "$TESTS_RUN" "$TESTS_PASSED" "$TESTS_FAILED"

if [ "$TESTS_FAILED" -gt 0 ]; then
    printf '\033[1;31mFAILED\033[0m\n'
    exit 1
else
    printf '\033[1;32mALL PASSED\033[0m\n'
    exit 0
fi
