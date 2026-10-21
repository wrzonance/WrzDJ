#!/usr/bin/env bash
# Sandbox the systemd watchdog against temporary Chromium Preferences files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHDOG="${SCRIPT_DIR}/../systemd/wrzdj-kiosk-watchdog.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$WORK_DIR/bin"
cat > "$WORK_DIR/bin/chown" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CHOWN_LOG"
MOCK
chmod +x "$WORK_DIR/bin/chown"
export PATH="$WORK_DIR/bin:$PATH"
export CHOWN_LOG="$WORK_DIR/chown.log"

preferences="$WORK_DIR/Preferences"
cat > "$preferences" <<'JSON'
{"profile":{"exited_cleanly":false,"exit_type":"Crashed","last_exit":"Crashed"}}
JSON

bash "$WATCHDOG" "$preferences"
grep -Fq '"exited_cleanly":true' "$preferences"
grep -Fq '"exit_type":"Normal"' "$preferences"
grep -Fq '"last_exit":"Crashed"' "$preferences"
grep -Fxq "kiosk:kiosk $preferences" "$CHOWN_LOG"

# Repeated timer runs leave the repaired state stable and still restore ownership.
first_result="$(cat "$preferences")"
bash "$WATCHDOG" "$preferences"
[[ "$(cat "$preferences")" == "$first_result" ]]
[[ "$(wc -l < "$CHOWN_LOG")" -eq 2 ]]

# A not-yet-created Chromium profile is a normal no-op.
missing="$WORK_DIR/missing/Preferences"
bash "$WATCHDOG" "$missing"
[[ ! -e "$missing" ]]
[[ "$(wc -l < "$CHOWN_LOG")" -eq 2 ]]

printf 'Watchdog repair, idempotence, and missing-profile behavior passed.\n'
