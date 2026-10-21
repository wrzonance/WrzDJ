#!/usr/bin/env bash
# Sandbox integration tests for overlayfs boot configuration workflows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERLAY_SCRIPT="${SCRIPT_DIR}/../overlayfs/setup-overlayfs.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$WORK_DIR/bin" "$WORK_DIR/boot/firmware" "$WORK_DIR/etc"
cat > "$WORK_DIR/bin/apt-get" <<'MOCK'
#!/usr/bin/env bash
printf 'apt-get %s\n' "$*" >> "$MOCK_LOG"
MOCK
cat > "$WORK_DIR/bin/update-initramfs" <<'MOCK'
#!/usr/bin/env bash
printf 'update-initramfs %s\n' "$*" >> "$MOCK_LOG"
MOCK
cat > "$WORK_DIR/bin/mount" <<'MOCK'
#!/usr/bin/env bash
printf 'mount mock\n'
MOCK
cat > "$WORK_DIR/bin/id" <<'MOCK'
#!/usr/bin/env bash
printf '0\n'
MOCK
chmod +x "$WORK_DIR/bin/apt-get" "$WORK_DIR/bin/update-initramfs" "$WORK_DIR/bin/mount" "$WORK_DIR/bin/id"

export PATH="$WORK_DIR/bin:$PATH"
export MOCK_LOG="$WORK_DIR/commands.log"
export WRZDJ_INITRAMFS_SCRIPT="$WORK_DIR/etc/initramfs-tools/scripts/overlay"
export WRZDJ_FSTAB_BACKUP="$WORK_DIR/etc/fstab.overlayfs-backup"
export WRZDJ_FSTAB="$WORK_DIR/etc/fstab"
export WRZDJ_BOOT_FIRMWARE_CMDLINE="$WORK_DIR/boot/firmware/cmdline.txt"
export WRZDJ_BOOT_CMDLINE="$WORK_DIR/boot/cmdline.txt"

printf 'original fstab\n' > "$WRZDJ_FSTAB"
printf 'console=serial0,115200 root=PARTUUID=abcd quiet splash\n' > "$WRZDJ_BOOT_FIRMWARE_CMDLINE"

bash "$OVERLAY_SCRIPT" enable >/dev/null
grep -q '^console=serial0,115200 root=PARTUUID=abcd quiet splash boot=overlay$' \
    "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
test -x "$WRZDJ_INITRAMFS_SCRIPT"
grep -q '^original fstab$' "$WRZDJ_FSTAB_BACKUP"
grep -q '^apt-get install -y -qq initramfs-tools$' "$MOCK_LOG"
grep -q '^update-initramfs -u$' "$MOCK_LOG"

# Enabling twice must not duplicate the boot flag or reinstall the hook.
bash "$OVERLAY_SCRIPT" enable >/dev/null
test "$(grep -o 'boot=overlay' "$WRZDJ_BOOT_FIRMWARE_CMDLINE" | wc -l)" -eq 1

printf 'changed fstab\n' > "$WRZDJ_FSTAB"
bash "$OVERLAY_SCRIPT" disable >/dev/null
grep -q '^console=serial0,115200 root=PARTUUID=abcd quiet splash$' \
    "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
test ! -e "$WRZDJ_INITRAMFS_SCRIPT"
grep -q '^original fstab$' "$WRZDJ_FSTAB"
test "$(grep -c '^update-initramfs -u$' "$MOCK_LOG")" -eq 2

# Removing the flag at the start must not leave leading whitespace.
printf 'boot=overlay root=PARTUUID=first\n' > "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
bash "$OVERLAY_SCRIPT" disable >/dev/null
grep -q '^root=PARTUUID=first$' "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
test "$(grep -c '^update-initramfs -u$' "$MOCK_LOG")" -eq 3

# A stale fallback cmdline must not override the selected firmware cmdline.
printf 'root=PARTUUID=active\n' > "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
printf 'root=PARTUUID=stale boot=overlay\n' > "$WRZDJ_BOOT_CMDLINE"
bash "$OVERLAY_SCRIPT" enable >/dev/null
grep -q '^root=PARTUUID=active boot=overlay$' "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
bash "$OVERLAY_SCRIPT" disable >/dev/null
grep -q '^root=PARTUUID=active$' "$WRZDJ_BOOT_FIRMWARE_CMDLINE"
grep -q '^root=PARTUUID=stale boot=overlay$' "$WRZDJ_BOOT_CMDLINE"
updates_before=$(grep -c '^update-initramfs -u$' "$MOCK_LOG")
bash "$OVERLAY_SCRIPT" disable >/dev/null
test "$(grep -c '^update-initramfs -u$' "$MOCK_LOG")" -eq "$updates_before"

# Missing boot command-line files must fail before package or filesystem changes.
if WRZDJ_BOOT_FIRMWARE_CMDLINE="$WORK_DIR/missing/firmware/cmdline.txt" \
    WRZDJ_BOOT_CMDLINE="$WORK_DIR/missing/cmdline.txt" \
    bash "$OVERLAY_SCRIPT" enable >/dev/null 2>&1; then
    printf 'enable unexpectedly succeeded without a boot command line file\n' >&2
    exit 1
fi
test "$(grep -c '^apt-get ' "$MOCK_LOG")" -eq 2

# State-changing and reporting commands must not equate unavailable state with disabled.
updates_before_missing=$(grep -c '^update-initramfs -u$' "$MOCK_LOG")
for command in disable status; do
    if WRZDJ_BOOT_FIRMWARE_CMDLINE="$WORK_DIR/missing/firmware/cmdline.txt" \
        WRZDJ_BOOT_CMDLINE="$WORK_DIR/missing/cmdline.txt" \
        bash "$OVERLAY_SCRIPT" "$command" > "$WORK_DIR/$command.out" 2>&1; then
        printf '%s unexpectedly succeeded without a boot command line file\n' "$command" >&2
        exit 1
    fi
    grep -q 'No boot command line file found' "$WORK_DIR/$command.out"
done
test "$(grep -c '^update-initramfs -u$' "$MOCK_LOG")" -eq "$updates_before_missing"

printf 'overlayfs sandbox workflows passed\n'
