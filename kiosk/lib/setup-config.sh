#!/usr/bin/env bash
# Parse, validate, and report kiosk configuration; sourced by setup.sh.
# Requires setup.sh globals SCRIPT_DIR, BOOT_CONF, CONF_FILE, KIOSK_USER and
# helpers info(), warn(), die(). Exports parse_config_file(), load_config(),
# prepare_hotspot_config(), write_config(), and print_summary(); load_config()
# initializes KIOSK_URL, KIOSK_ROTATION, WIFI_SSID, WIFI_PASSWORD, WIFI_COUNTRY,
# EXTRA_CHROMIUM_FLAGS, HOTSPOT_SSID, and HOTSPOT_PASSWORD for the other layers.
# shellcheck disable=SC2034 # configured Wi-Fi values are consumed by setup-platform.sh

normalize_config_entry() {
    local key="$1" value="$2"
    # Match parse_config_file semantics without evaluating or sourcing file contents.
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#\"}"
    value="${value%\"}"
    NORMALIZED_CONFIG_KEY="$key"
    NORMALIZED_CONFIG_VALUE="$value"
}

parse_config_file() {
    local file="$1"
    while IFS='=' read -r key value || [[ -n "$key$value" ]]; do
        # Skip comments and blank lines
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        normalize_config_entry "$key" "$value"
        key="$NORMALIZED_CONFIG_KEY"
        value="$NORMALIZED_CONFIG_VALUE"
        # Only allow known keys
        case "$key" in
            KIOSK_URL)              KIOSK_URL="$value" ;;
            KIOSK_ROTATION)         KIOSK_ROTATION="$value" ;;
            WIFI_SSID)              WIFI_SSID="$value" ;;
            WIFI_PASSWORD)          WIFI_PASSWORD="$value" ;;
            WIFI_COUNTRY)           WIFI_COUNTRY="$value" ;;
            EXTRA_CHROMIUM_FLAGS)   EXTRA_CHROMIUM_FLAGS="$value" ;;
            HOTSPOT_SSID)           HOTSPOT_SSID="$value" ;;
            HOTSPOT_PASSWORD)       HOTSPOT_PASSWORD="$value" ;;
            *)                      warn "Unknown config key: ${key}" ;;
        esac
    done < "$file"
}

load_config() {
    # Initialize defaults
    KIOSK_URL=""
    KIOSK_ROTATION="0"
    WIFI_SSID=""
    WIFI_PASSWORD=""
    WIFI_COUNTRY="US"
    EXTRA_CHROMIUM_FLAGS=""
    HOTSPOT_SSID=""
    HOTSPOT_PASSWORD=""

    # Priority: boot partition > local file
    if [ -f "$BOOT_CONF" ]; then
        info "Loading config from ${BOOT_CONF}"
        parse_config_file "$BOOT_CONF"
    elif [ -f "${SCRIPT_DIR}/wrzdj-kiosk.conf" ]; then
        info "Loading config from ${SCRIPT_DIR}/wrzdj-kiosk.conf"
        parse_config_file "${SCRIPT_DIR}/wrzdj-kiosk.conf"
    fi

    if [ -z "$KIOSK_URL" ]; then
        info "No KIOSK_URL found in config — using default"
        KIOSK_URL="https://app.wrzdj.com/kiosk-pair"
    fi

    # Validate URL
    if [[ ! "$KIOSK_URL" =~ ^https?:// ]]; then
        die "KIOSK_URL must start with http:// or https:// (got: ${KIOSK_URL})"
    fi

    # Validate rotation
    case "$KIOSK_ROTATION" in
        0|90|180|270) ;;
        *) warn "Invalid KIOSK_ROTATION '${KIOSK_ROTATION}', defaulting to 0"
           KIOSK_ROTATION="0" ;;
    esac
}

prepare_hotspot_config() {
    local existing_config="$1" key value
    : "${HOTSPOT_SSID:=WrzDJ-Kiosk}"
    if [ -z "$HOTSPOT_PASSWORD" ] && [ -f "$existing_config" ]; then
        while IFS='=' read -r key value || [[ -n "$key$value" ]]; do
            [[ "$key" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$key" ]] && continue
            normalize_config_entry "$key" "$value"
            if [ "$NORMALIZED_CONFIG_KEY" = HOTSPOT_PASSWORD ]; then
                HOTSPOT_PASSWORD="$NORMALIZED_CONFIG_VALUE"
            fi
        done < "$existing_config"
    fi
    if [ -z "$HOTSPOT_PASSWORD" ]; then
        HOTSPOT_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
    fi
}

write_config() {
    info "Writing ${CONF_FILE}..."

    prepare_hotspot_config "$CONF_FILE"

    cat > "$CONF_FILE" <<CONF
# WrzDJ Kiosk Configuration
# Edit and restart: sudo systemctl restart getty@tty1

KIOSK_URL="${KIOSK_URL}"
KIOSK_ROTATION="${KIOSK_ROTATION}"
EXTRA_CHROMIUM_FLAGS="${EXTRA_CHROMIUM_FLAGS}"
HOTSPOT_SSID="${HOTSPOT_SSID}"
HOTSPOT_PASSWORD="${HOTSPOT_PASSWORD}"
CONF

    # 644: kiosk user's .bash_profile sources this file (set -a) to pick up
    # EXTRA_CHROMIUM_FLAGS. Only the displayed setup-hotspot password is stored here,
    # never the venue's WiFi credentials.
    chmod 644 "$CONF_FILE"
}

print_summary() {
    printf '\n'
    printf '\033[1;32m%s\033[0m\n' "================================================"
    printf '\033[1;32m%s\033[0m\n' "  WrzDJ Kiosk Setup Complete"
    printf '\033[1;32m%s\033[0m\n' "================================================"
    printf '\n'
    printf '  Launcher:  http://localhost (local Wi-Fi portal)\n'
    printf '  Portal URL: %s\n' "$KIOSK_URL"
    printf '  Rotation:  %s degrees\n' "$KIOSK_ROTATION"
    printf '  Hostname:  wrzdj-kiosk\n'
    printf '  User:      %s\n' "$KIOSK_USER"
    printf '\n'
    printf '  Hotspot:   %s (password shown on kiosk portal)\n' "$HOTSPOT_SSID"
    printf '\n'
    printf '  Config:    %s\n' "$CONF_FILE"
    printf '  Launcher:  /home/%s/.bash_profile\n' "$KIOSK_USER"
    printf '  Portal:    wrzdj-wifi-portal.service\n'
    printf '  Watchdog:  wrzdj-kiosk-watchdog.timer\n'
    printf '\n'
    printf '  To change the portal URL later:\n'
    printf '    sudo nano %s\n' "$CONF_FILE"
    printf '    sudo systemctl restart wrzdj-wifi-portal getty@tty1\n'
    printf '\n'
    printf '  For SD card protection (optional):\n'
    printf '    sudo %s/overlayfs/setup-overlayfs.sh\n' "$SCRIPT_DIR"
    printf '\n'
}
