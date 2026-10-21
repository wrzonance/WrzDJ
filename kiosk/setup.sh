#!/usr/bin/env bash
# WrzDJ Kiosk Setup Script
# Transforms a fresh Raspberry Pi OS Lite (64-bit) into a WrzDJ kiosk.
#
# Usage:
#   sudo ./setup.sh
#
# Idempotent — safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
# shellcheck disable=SC2034 # consumed by sourced setup modules
readonly CONF_FILE="/etc/wrzdj-kiosk.conf"
# shellcheck disable=SC2034 # consumed by sourced setup modules
readonly BOOT_CONF="/boot/firmware/wrzdj-kiosk.conf"
# shellcheck disable=SC2034 # consumed by sourced setup modules
readonly KIOSK_USER="kiosk"

# ---------- helpers ----------

info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
error() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }
die()   { error "$@"; exit 1; }

# ---------- pre-flight checks ----------

preflight() {
    if [ "$(id -u)" -ne 0 ]; then
        die "This script must be run as root (sudo ./setup.sh)"
    fi
    if ! command -v nmcli >/dev/null || ! systemctl is-active --quiet NetworkManager; then
        die "NetworkManager must be installed and active. Use Raspberry Pi OS Bookworm or newer."
    fi

    local arch
    arch="$(uname -m)"
    if [[ "$arch" != aarch64 && "$arch" != armv7l ]]; then
        warn "Detected architecture: ${arch} (expected aarch64 or armv7l)"
        warn "This script is designed for Raspberry Pi — proceed with caution"
    fi

    if ! grep -qi 'raspberry\|bcm2' /proc/cpuinfo 2>/dev/null; then
        warn "This doesn't look like a Raspberry Pi — proceed with caution"
    fi
}

# ---------- setup layers ----------
# Shared module contract: these files are sourced into this shell after SCRIPT_DIR,
# CONF_FILE, BOOT_CONF, KIOSK_USER, and info/warn/error/die are defined. They add
# functions to the setup namespace and exchange configuration through shell globals;
# preserve this source order to keep the config, platform, and runtime layers grouped.

# shellcheck disable=SC1091 # path is resolved relative to this script at runtime
source "${SCRIPT_DIR}/lib/setup-config.sh"
# shellcheck disable=SC1091 # path is resolved relative to this script at runtime
source "${SCRIPT_DIR}/lib/setup-platform.sh"
# shellcheck disable=SC1091 # path is resolved relative to this script at runtime
source "${SCRIPT_DIR}/lib/setup-runtime.sh"

main() {
    info "WrzDJ Kiosk Setup"
    info "========================================="

    preflight
    load_config
    install_packages
    create_kiosk_user
    configure_wifi
    configure_rotation /boot/firmware/config.txt
    install_services
    install_kiosk_launcher
    install_wifi_portal
    write_config
    disable_screen_blanking
    configure_autologin
    disable_unnecessary_services
    set_hostname

    print_summary

    printf 'Reboot now? [Y/n] '
    read -r answer
    case "${answer:-Y}" in
        [Yy]*) reboot ;;
        *)     info "Reboot manually when ready: sudo reboot" ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
