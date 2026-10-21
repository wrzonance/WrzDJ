#!/usr/bin/env bash
# Copy every screenshot-*.{png,webp} from docs/images/ → ../wrzdjweb/images/.
# Run after `npm run screenshots` to keep the marketing site in sync.
#
# Usage: scripts/sync-screenshots-to-wrzdjweb.sh [WRZDJWEB_PATH]
#   WRZDJWEB_PATH defaults to ~/github/wrzdjweb

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${WRZDJ_SCREENSHOT_IMAGES_DIR:-$REPO_ROOT/docs/images}"
DST="${1:-$HOME/github/wrzdjweb}/images"

if [[ ! -d "$DST" ]]; then
  echo "wrzdjweb images dir not found: $DST" >&2
  exit 1
fi

shopt -s nullglob
files=("$SRC"/screenshot-*.png "$SRC"/screenshot-*.webp)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "no screenshot-*.{png,webp} found in $SRC — run 'npm run screenshots' first" >&2
  exit 1
fi

rsync -a "${files[@]}" "$DST/"
echo "Synced ${#files[@]} file(s) → $DST"
echo "Next: cd $(dirname "$DST")/.. && git status, branch, PR, rsync to Dreamhost"
