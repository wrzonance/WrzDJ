#!/usr/bin/env bash
# WrzDJ Kiosk — OverlayFS SD Card Protection
#
# Makes the root filesystem read-only via overlayfs. All writes go to a
# RAM-backed tmpfs and are lost on reboot. This protects the SD card from
# corruption caused by hard power-offs (which is how most DJs will "shut
# down" the Pi at the end of a gig).
#
# Trade-offs:
#   - Chromium localStorage (kiosk session tokens) is lost on reboot.
#     The kiosk will re-enter pairing mode — re-pairing takes ~30 seconds.
#   - Config changes require disabling overlayfs first (see below).
#   - Log data is lost on reboot.
#
# Usage:
#   sudo ./setup-overlayfs.sh enable    # Enable overlayfs (reboot required)
#   sudo ./setup-overlayfs.sh disable   # Disable overlayfs (reboot required)
#   sudo ./setup-overlayfs.sh status    # Show current state

set -euo pipefail

readonly INITRAMFS_SCRIPT="${WRZDJ_INITRAMFS_SCRIPT:-/etc/initramfs-tools/scripts/overlay}"
readonly FSTAB_BAK="${WRZDJ_FSTAB_BACKUP:-/etc/fstab.overlayfs-backup}"
readonly FSTAB="${WRZDJ_FSTAB:-/etc/fstab}"
readonly BOOT_FIRMWARE_CMDLINE="${WRZDJ_BOOT_FIRMWARE_CMDLINE:-/boot/firmware/cmdline.txt}"
readonly BOOT_CMDLINE="${WRZDJ_BOOT_CMDLINE:-/boot/cmdline.txt}"

info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
error() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }
die()   { error "$@"; exit 1; }

check_root() {
    [ "$(id -u)" -eq 0 ] || die "Must be run as root"
}

is_overlayfs_enabled() {
    local cmdline="$1"
    grep -Eq '(^|[[:space:]])boot=overlay([[:space:]]|$)' "$cmdline" 2>/dev/null
}

boot_cmdline_file() {
    if [ -f "$BOOT_FIRMWARE_CMDLINE" ]; then
        printf '%s\n' "$BOOT_FIRMWARE_CMDLINE"
    elif [ -f "$BOOT_CMDLINE" ]; then
        printf '%s\n' "$BOOT_CMDLINE"
    else
        return 1
    fi
}

enable_overlayfs() {
    local cmdline
    cmdline="$(boot_cmdline_file)" || die "No boot command line file found"
    if is_overlayfs_enabled "$cmdline"; then
        info "OverlayFS is already enabled"
        return
    fi

    info "Installing initramfs-tools..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq initramfs-tools > /dev/null

    info "Creating overlay initramfs script..."
    mkdir -p "$(dirname "$INITRAMFS_SCRIPT")"

    cat > "$INITRAMFS_SCRIPT" <<'OVERLAY_SCRIPT'
#!/bin/sh
# OverlayFS hook for initramfs
# Mounts root as read-only with a tmpfs overlay

PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0 ;; esac

. /scripts/functions

log_begin_msg "Setting up overlayfs root"

# Create mount points
mkdir -p /overlay /overlay/lower /overlay/upper /overlay/work

# Move the real root to lower
mount --move ${rootmnt} /overlay/lower

# Create tmpfs for writable layer
mount -t tmpfs tmpfs-root /overlay/upper -o size=256M
mkdir -p /overlay/upper/upper /overlay/upper/work

# Mount overlay
mount -t overlay overlay ${rootmnt} \
    -o lowerdir=/overlay/lower,upperdir=/overlay/upper/upper,workdir=/overlay/upper/work

# Move lower inside the new root so it's accessible
mkdir -p ${rootmnt}/overlay/lower
mount --move /overlay/lower ${rootmnt}/overlay/lower

log_end_msg
OVERLAY_SCRIPT

    chmod +x "$INITRAMFS_SCRIPT"

    # Back up fstab
    if [ ! -f "$FSTAB_BAK" ]; then
        cp "$FSTAB" "$FSTAB_BAK"
    fi

    # Add boot=overlay to kernel command line
    if ! grep -Eq '(^|[[:space:]])boot=overlay([[:space:]]|$)' "$cmdline"; then
        sed -i 's/$/ boot=overlay/' "$cmdline"
    fi

    # Rebuild initramfs
    info "Rebuilding initramfs (this may take a minute)..."
    update-initramfs -u

    info "OverlayFS enabled. Reboot to activate."
    info "To make changes later: sudo ./setup-overlayfs.sh disable"
}

disable_overlayfs() {
    local cmdline
    cmdline="$(boot_cmdline_file)" || die "No boot command line file found"
    if ! is_overlayfs_enabled "$cmdline"; then
        info "OverlayFS is already disabled"
        return
    fi

    # Remove boot=overlay from cmdline
    sed -i -E \
        -e 's/(^|[[:space:]])boot=overlay([[:space:]]|$)/\1\2/g' \
        -e 's/^[[:space:]]+//' \
        -e 's/[[:space:]]+$//' "$cmdline"

    # Remove initramfs script
    rm -f "$INITRAMFS_SCRIPT"

    # Restore fstab if backup exists
    if [ -f "$FSTAB_BAK" ]; then
        cp "$FSTAB_BAK" "$FSTAB"
    fi

    # Rebuild initramfs
    info "Rebuilding initramfs..."
    update-initramfs -u

    info "OverlayFS disabled. Reboot to deactivate."
}

show_status() {
    local cmdline
    cmdline="$(boot_cmdline_file)" || die "No boot command line file found"
    if is_overlayfs_enabled "$cmdline"; then
        info "OverlayFS: ENABLED (cmdline has boot=overlay)"
    else
        info "OverlayFS: DISABLED"
    fi

    # Check if currently running with overlay
    if mount | grep -q 'overlay on / '; then
        info "Root filesystem: overlayfs (read-only, writes go to RAM)"
    else
        info "Root filesystem: normal (read-write)"
    fi
}

main() {
    check_root

    case "${1:-status}" in
        enable)  enable_overlayfs ;;
        disable) disable_overlayfs ;;
        status)  show_status ;;
        *)       die "Usage: $0 {enable|disable|status}" ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
