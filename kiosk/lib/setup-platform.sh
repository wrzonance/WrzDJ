#!/usr/bin/env bash
# Prepare kiosk packages, user, network, and host settings; sourced by setup.sh.
# Requires setup.sh globals KIOSK_USER and the config globals KIOSK_ROTATION,
# WIFI_COUNTRY, WIFI_SSID, and WIFI_PASSWORD, plus info(), warn(), and die().
# Exports configure_rotation(), install_packages(), create_kiosk_user(),
# configure_wifi(), disable_screen_blanking(), disable_unnecessary_services(),
# and set_hostname().

configure_rotation() {
    if [ "$KIOSK_ROTATION" = "0" ]; then
        info "Screen rotation: 0 (default, no change needed)"
        return
    fi

    info "Configuring screen rotation: ${KIOSK_ROTATION} degrees"

    local config_file="${1:-/boot/firmware/config.txt}"
    if [ ! -f "$config_file" ]; then
        config_file="/boot/config.txt"
    fi

    if [ ! -f "$config_file" ]; then
        warn "Cannot find config.txt — skipping rotation"
        return
    fi

    local rotate_value
    case "$KIOSK_ROTATION" in
        90)  rotate_value=1 ;;
        180) rotate_value=2 ;;
        270) rotate_value=3 ;;
        *)   warn "Invalid rotation: ${KIOSK_ROTATION} — skipping"; return ;;
    esac

    sed -i '/^display_rotate=/d' "$config_file"
    printf 'display_rotate=%s\n' "$rotate_value" >> "$config_file"
}

install_packages() {
    info "Updating package lists..."
    apt-get update -qq

    info "Installing cage, chromium-browser, dnsmasq, curl, and emoji fonts..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        cage \
        chromium-browser \
        curl \
        dnsmasq \
        fonts-noto-color-emoji \
        > /dev/null

    info "Packages installed"
}

create_kiosk_user() {
    if id "$KIOSK_USER" &>/dev/null; then
        info "User '${KIOSK_USER}' already exists"
    else
        info "Creating user '${KIOSK_USER}'..."
        useradd \
            --create-home \
            --shell /bin/bash \
            --groups input,video,render \
            "$KIOSK_USER"
    fi

    # Ensure group membership even if user already existed
    for grp in input video render; do
        if getent group "$grp" &>/dev/null; then
            if ! usermod -aG "$grp" "$KIOSK_USER"; then
                die "Failed to add '${KIOSK_USER}' to '${grp}' group"
            fi
        fi
    done
}

configure_wifi() {
    # Set WiFi regulatory domain — required for the radio to activate on
    # many Pi models. Without this, wlan0 may refuse to connect.
    info "Setting WiFi regulatory domain: ${WIFI_COUNTRY}"
    if [ -d /etc/default ]; then
        printf 'REGDOMAIN=%s\n' "$WIFI_COUNTRY" > /etc/default/crda
    fi
    mkdir -p /etc/modprobe.d
    printf 'options cfg80211 ieee80211_regdom=%s\n' "$WIFI_COUNTRY" \
        > /etc/modprobe.d/wifi-regdom.conf

    # Enable NM-wait-online so services that depend on network (like the
    # WiFi portal) don't start before WiFi is connected
    if systemctl list-unit-files NetworkManager-wait-online.service &>/dev/null; then
        systemctl enable NetworkManager-wait-online.service 2>/dev/null || true
    fi

    if [ -z "$WIFI_SSID" ]; then
        info "No WIFI_SSID set — skipping WiFi connection setup"
        return
    fi

    info "Configuring WiFi for SSID: ${WIFI_SSID}"

    if nmcli -t -f NAME connection show | grep -qx "wrzdj-wifi"; then
        nmcli connection modify wrzdj-wifi \
            wifi.ssid "$WIFI_SSID" wifi-sec.psk "$WIFI_PASSWORD"
    else
        nmcli connection add type wifi con-name wrzdj-wifi \
            ifname wlan0 ssid "$WIFI_SSID" \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$WIFI_PASSWORD"
    fi
    nmcli connection up wrzdj-wifi || warn "WiFi connection failed — check credentials"
}

disable_screen_blanking() {
    info "Disabling screen blanking..."

    local cmdline="/boot/firmware/cmdline.txt"
    if [ ! -f "$cmdline" ]; then
        cmdline="/boot/cmdline.txt"
    fi

    if [ -f "$cmdline" ]; then
        # Add consoleblank=0 if not present
        if ! grep -q 'consoleblank=0' "$cmdline"; then
            sed -i '/\S/s/$/ consoleblank=0/' "$cmdline"
        fi
    fi
}

disable_unnecessary_services() {
    info "Disabling unnecessary services..."

    local services=(
        bluetooth.service
        hciuart.service
        triggerhappy.service
    )

    for svc in "${services[@]}"; do
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            if systemctl disable --now "$svc" 2>/dev/null; then
                info "  Disabled: ${svc}"
            else
                warn "  Could not disable ${svc}; continuing setup"
            fi
        fi
    done
}

set_hostname() {
    local current
    current="$(hostnamectl hostname 2>/dev/null || cat /etc/hostname)"

    if [ "$current" = "wrzdj-kiosk" ]; then
        info "Hostname already set to wrzdj-kiosk"
        return
    fi

    info "Setting hostname to wrzdj-kiosk..."
    hostnamectl set-hostname wrzdj-kiosk 2>/dev/null || {
        echo "wrzdj-kiosk" > /etc/hostname
        # Escape regex metacharacters in the current hostname
        local escaped_current
        # Dollar is a literal member of the regex character class.
        # shellcheck disable=SC2016
        escaped_current="$(printf '%s' "$current" | sed 's/[.[\*^$()+?{|\\]/\\&/g')"
        sed -i "s/${escaped_current}/wrzdj-kiosk/g" /etc/hosts
    }
}
