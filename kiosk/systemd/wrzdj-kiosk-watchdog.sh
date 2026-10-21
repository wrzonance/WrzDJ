#!/usr/bin/env bash
# WrzDJ Kiosk Watchdog
# Runs via systemd timer every 30s. Clears Chromium's crash flag
# (prevents "restore session?" dialog after hard power-off). The tty1
# login session owns Cage startup and recovery.

set -euo pipefail

main() {
    local preferences="${1:-/home/kiosk/.config/chromium/Default/Preferences}"

    if [ -f "$preferences" ]; then
        sed -i \
            -e 's/"exited_cleanly":false/"exited_cleanly":true/g' \
            -e 's/"exit_type":"Crashed"/"exit_type":"Normal"/g' \
            "$preferences"
        chown kiosk:kiosk "$preferences"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
