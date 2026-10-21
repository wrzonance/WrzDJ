#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$WORK_DIR/bin" "$WORK_DIR/source" "$WORK_DIR/site/images"
cat > "$WORK_DIR/bin/cwebp" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [ "${MOCK_CWEBP_FAIL:-0}" = 1 ]; then
  echo 'conversion failed' >&2
  exit 23
fi
output=
while (($#)); do
  if [ "$1" = -o ]; then
    shift
    output=${1:?output path required}
  fi
  shift
done
: "${output:?cwebp output was not specified}"
printf '%s\n' "$output" >> "$MOCK_LOG"
touch "$output"
MOCK
cat > "$WORK_DIR/bin/rsync" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [ "${MOCK_RSYNC_FAIL:-0}" = 1 ]; then
  echo 'copy failed' >&2
  exit 24
fi
destination=${!#}
shift
for source in "$@"; do
  [ "$source" = "$destination" ] || cp -- "$source" "$destination/"
done
MOCK
chmod +x "$WORK_DIR/bin/cwebp" "$WORK_DIR/bin/rsync"

printf 'png payload\n' > "$WORK_DIR/source/screenshot-current.png"
printf 'old png payload\n' > "$WORK_DIR/source/screenshot-archive.png"
printf 'unrelated\n' > "$WORK_DIR/source/other.png"

PATH="$WORK_DIR/bin:$PATH" MOCK_LOG="$WORK_DIR/cwebp.log" \
  WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/source" bash "$ROOT/scripts/png-to-webp.sh" > "$WORK_DIR/convert.log"
test -f "$WORK_DIR/source/screenshot-current.webp"
test -f "$WORK_DIR/source/screenshot-archive.webp"
test ! -e "$WORK_DIR/source/other.webp"
grep -q '^Encoded 2 PNG' "$WORK_DIR/convert.log"
test "$(wc -l < "$WORK_DIR/cwebp.log")" -eq 2

PATH="$WORK_DIR/bin:$PATH" WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/source" \
  bash "$ROOT/scripts/sync-screenshots-to-wrzdjweb.sh" "$WORK_DIR/site" > "$WORK_DIR/sync.log"
cmp "$WORK_DIR/source/screenshot-current.png" "$WORK_DIR/site/images/screenshot-current.png"
cmp "$WORK_DIR/source/screenshot-current.webp" "$WORK_DIR/site/images/screenshot-current.webp"
cmp "$WORK_DIR/source/screenshot-archive.png" "$WORK_DIR/site/images/screenshot-archive.png"
cmp "$WORK_DIR/source/screenshot-archive.webp" "$WORK_DIR/site/images/screenshot-archive.webp"
test ! -e "$WORK_DIR/site/images/other.png"
grep -q '^Synced 4 file(s)' "$WORK_DIR/sync.log"

if PATH="$WORK_DIR/bin:$PATH" WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/empty" \
  bash "$ROOT/scripts/sync-screenshots-to-wrzdjweb.sh" "$WORK_DIR/site" \
    > "$WORK_DIR/empty.log" 2>&1; then
  echo 'sync should fail when no screenshots are available' >&2
  exit 1
fi
grep -q "no screenshot-.*found" "$WORK_DIR/empty.log"

# Regression coverage for CLI failures at baseline 57cfcdc6867f.
mkdir "$WORK_DIR/no-tools" "$WORK_DIR/failing-source" "$WORK_DIR/empty"
ln -s "$(command -v dirname)" "$WORK_DIR/no-tools/dirname"
bash_executable=$(command -v bash)
if PATH="$WORK_DIR/no-tools" "$bash_executable" "$ROOT/scripts/png-to-webp.sh" \
  > "$WORK_DIR/missing-tool.log" 2>&1; then
  echo 'conversion should fail when cwebp is unavailable' >&2
  exit 1
fi
grep -q '^cwebp not found' "$WORK_DIR/missing-tool.log"

printf 'png payload\n' > "$WORK_DIR/failing-source/screenshot-fail.png"
if PATH="$WORK_DIR/bin:$PATH" MOCK_CWEBP_FAIL=1 \
  WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/failing-source" \
  bash "$ROOT/scripts/png-to-webp.sh" > "$WORK_DIR/conversion-failure.log" 2>&1; then
  echo 'conversion should propagate cwebp failure' >&2
  exit 1
else
  test "$?" -eq 23
fi
grep -q '^conversion failed' "$WORK_DIR/conversion-failure.log"
test ! -e "$WORK_DIR/failing-source/screenshot-fail.webp"
if grep -q '^Encoded' "$WORK_DIR/conversion-failure.log"; then
  echo 'failed conversion must not report success' >&2
  exit 1
fi

PATH="$WORK_DIR/bin:$PATH" WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/empty" \
  bash "$ROOT/scripts/png-to-webp.sh" > "$WORK_DIR/no-input.log"
grep -q '^Encoded 0 PNG' "$WORK_DIR/no-input.log"

if WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/source" \
  bash "$ROOT/scripts/sync-screenshots-to-wrzdjweb.sh" "$WORK_DIR/missing-site" \
  > "$WORK_DIR/missing-destination.log" 2>&1; then
  echo 'sync should reject a missing destination' >&2
  exit 1
fi
grep -q '^wrzdjweb images dir not found' "$WORK_DIR/missing-destination.log"

if PATH="$WORK_DIR/bin:$PATH" MOCK_RSYNC_FAIL=1 \
  WRZDJ_SCREENSHOT_IMAGES_DIR="$WORK_DIR/source" \
  bash "$ROOT/scripts/sync-screenshots-to-wrzdjweb.sh" "$WORK_DIR/site" \
  > "$WORK_DIR/copy-failure.log" 2>&1; then
  echo 'sync should propagate rsync failure' >&2
  exit 1
else
  test "$?" -eq 24
fi
grep -q '^copy failed' "$WORK_DIR/copy-failure.log"
if grep -q '^Synced' "$WORK_DIR/copy-failure.log"; then
  echo 'failed sync must not report success' >&2
  exit 1
fi

echo 'Screenshot conversion and sync sandbox workflows passed.'
