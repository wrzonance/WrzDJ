#!/usr/bin/env bash
# Generate .webp variants for every screenshot-*.png in docs/images/.
# Idempotent: re-encodes every time the screenshot suite runs so .webp stays in sync.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGES_DIR="${WRZDJ_SCREENSHOT_IMAGES_DIR:-$REPO_ROOT/docs/images}"

if ! command -v cwebp >/dev/null 2>&1; then
  echo "cwebp not found — install libwebp-tools (Manjaro: 'pacman -S libwebp', macOS: 'brew install webp')" >&2
  exit 1
fi

shopt -s nullglob
count=0
for png in "$IMAGES_DIR"/screenshot-*.png; do
  webp="${png%.png}.webp"
  cwebp -quiet -q 85 "$png" -o "$webp"
  count=$((count + 1))
done

echo "Encoded $count PNG→WebP pair(s) in $IMAGES_DIR"
