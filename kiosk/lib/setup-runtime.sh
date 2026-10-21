#!/usr/bin/env bash
# Install systemd units, portal modules, and the tty1 kiosk launcher; sourced by setup.sh.
# Requires setup.sh globals SCRIPT_DIR, KIOSK_USER, and helpers info(), warn(), die().
# KIOSK_ROOT is optional and prefixes selected paths for isolated installation/testing.
# The generated launcher reads WRZDJ_KIOSK_CONFIG at runtime; service units are static.
# Exports install_services(),
# install_kiosk_launcher(), install_wifi_portal(), and configure_autologin().

install_services() {
    info "Installing systemd services..."

    # Remove only the reference unit previously installed by this setup.
    # Preserve locally customized units so setup never deletes user-owned content.
    local root="${KIOSK_ROOT:-}"
    local retired_service="${root}/etc/systemd/system/wrzdj-kiosk.service"
    if [ -f "$retired_service" ]; then
        if grep -Fqx '# This file is kept as a reference for Chromium flags and security hardening.' \
            "$retired_service"; then
            if systemctl disable --now wrzdj-kiosk.service 2>/dev/null; then
                rm -f "$retired_service"
                info "Removed retired kiosk service"
            else
                warn "Could not disable retired kiosk service; leaving its unit in place"
            fi
        else
            warn "Existing kiosk service has local changes; leaving its unit in place"
        fi
    fi

    # Watchdog
    cp "${SCRIPT_DIR}/systemd/wrzdj-kiosk-watchdog.service" \
        /etc/systemd/system/wrzdj-kiosk-watchdog.service
    cp "${SCRIPT_DIR}/systemd/wrzdj-kiosk-watchdog.timer" \
        /etc/systemd/system/wrzdj-kiosk-watchdog.timer

    # Watchdog script
    install -m 755 "${SCRIPT_DIR}/systemd/wrzdj-kiosk-watchdog.sh" \
        /usr/local/bin/wrzdj-kiosk-watchdog.sh

    systemctl daemon-reload
    systemctl enable wrzdj-kiosk-watchdog.timer

    info "Services installed and enabled"
}

install_kiosk_launcher() {
    info "Installing kiosk launcher (.bash_profile)..."

    # Cage needs logind seat access (DRM/input devices). System services
    # don't get this — the process must run inside the user's login session.
    # Auto-login on tty1 creates the session; .bash_profile launches Cage.
    # When Cage exits, the login session ends, getty restarts auto-login,
    # and .bash_profile re-launches Cage — self-healing by design.

    local root="${KIOSK_ROOT:-}"
    local profile="${root}/home/${KIOSK_USER}/.bash_profile"

    cat > "$profile" <<'LAUNCHER'
# WrzDJ Kiosk Launcher
# Launches Cage + Chromium on tty1 (skipped for SSH sessions).
# Config: /etc/wrzdj-kiosk.conf

if [ "$(tty)" = "/dev/tty1" ]; then
    # Source kiosk config for EXTRA_CHROMIUM_FLAGS
    set -a
    . "${WRZDJ_KIOSK_CONFIG:-/etc/wrzdj-kiosk.conf}" 2>/dev/null || true
    set +a

    # Treat configured extras as whitespace-separated arguments without eval or globbing.
    IFS=$' \t\n' read -r -a extra_chromium_flags <<< "${EXTRA_CHROMIUM_FLAGS:-}"

    # Wait for the lightweight local readiness endpoint. The root page may need
    # slow connectivity probes, which should not delay kiosk startup.
    printf 'Waiting for WiFi portal...\n'
    portal_wait_attempts="${WRZDJ_PORTAL_WAIT_ATTEMPTS:-60}"
    if ! [[ "$portal_wait_attempts" =~ ^[1-9][0-9]{0,2}$ ]]; then
        portal_wait_attempts=60
    fi
    portal_ready=0
    for ((attempt = 0; attempt < portal_wait_attempts; attempt++)); do
        if curl --connect-timeout 2 --max-time 5 -fsS -o /dev/null \
            http://localhost/api/ready 2>/dev/null; then
            portal_ready=1
            break
        fi
        if ((attempt + 1 < portal_wait_attempts)); then
            sleep 1
        fi
    done
    if ((portal_ready == 0)); then
        printf 'WiFi portal did not become ready after %s attempts.\n' \
            "$portal_wait_attempts" >&2
        exit 1
    fi

    # Cage needs these for Wayland
    export WLR_NO_HARDWARE_CURSORS=1
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

    exec cage -- /usr/bin/chromium-browser \
        --kiosk \
        --noerrdialogs \
        --disable-infobars \
        --no-first-run \
        --disable-translate \
        --disable-session-crashed-bubble \
        --disable-component-update \
        --disable-pinch \
        --touch-events=enabled \
        --ozone-platform=wayland \
        --disable-dev-shm-usage \
        --disable-background-networking \
        --disable-sync \
        --metrics-recording-only \
        --disable-default-apps \
        --no-default-browser-check \
        --autoplay-policy=no-user-gesture-required \
        "${extra_chromium_flags[@]}" \
        http://localhost
fi
LAUNCHER

    chown "${KIOSK_USER}:${KIOSK_USER}" "$profile"
    chmod 644 "$profile"

    info "Kiosk launcher installed at ${profile}"
}

install_wifi_portal() {
    info "Installing WiFi captive portal..."

    # Install the portal entrypoint and its rendering modules together.
    mkdir -p /usr/local/lib/wrzdj
    install -m 755 "${SCRIPT_DIR}/wifi-portal/portal.py" \
        /usr/local/lib/wrzdj/portal.py
    install -m 644 "${SCRIPT_DIR}/wifi-portal/portal_pages.py" \
        "${SCRIPT_DIR}/wifi-portal/portal_defaults.py" \
        "${SCRIPT_DIR}/wifi-portal/portal_config.py" \
        "${SCRIPT_DIR}/wifi-portal/portal_requests.py" \
        "${SCRIPT_DIR}/wifi-portal/portal_network.py" \
        "${SCRIPT_DIR}/wifi-portal/portal_types.py" \
        "${SCRIPT_DIR}/wifi-portal/portal_state.py" /usr/local/lib/wrzdj/

    # Install dnsmasq config for captive portal DNS redirect
    # NM's shared-mode dnsmasq uses this directory; the config is inert
    # when no hotspot is active
    mkdir -p /etc/NetworkManager/dnsmasq-shared.d
    install -m 644 "${SCRIPT_DIR}/wifi-portal/dnsmasq-captive.conf" \
        /etc/NetworkManager/dnsmasq-shared.d/captive-portal.conf

    # Install and enable the portal systemd service
    cp "${SCRIPT_DIR}/systemd/wrzdj-wifi-portal.service" \
        /etc/systemd/system/wrzdj-wifi-portal.service
    systemctl daemon-reload
    systemctl enable wrzdj-wifi-portal.service

    info "WiFi portal installed"
}

configure_autologin() {
    info "Configuring auto-login for ${KIOSK_USER}..."

    local override_dir="${KIOSK_ROOT:-}/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "$override_dir"

    cat > "${override_dir}/autologin.conf" <<LOGIN
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
LOGIN

    systemctl daemon-reload
}
