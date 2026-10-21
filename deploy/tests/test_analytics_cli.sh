#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/logs"
touch "$scratch/logs/api.example.test.access.log" "$scratch/logs/app.example.test.access.log" \
  "$scratch/logs/default.access.log" "$scratch/goaccess.conf"
cat > "$scratch/bin/goaccess" <<'GOACCESS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_GOACCESS_CALLS"
if [ "${!#}" = - ]; then
  cat > "$WRZDJ_GOACCESS_INPUT"
fi
GOACCESS
chmod +x "$scratch/bin/goaccess"
export PATH="$scratch/bin:$PATH"
export WRZDJ_ANALYTICS_LOG_DIR="$scratch/logs"
export WRZDJ_ANALYTICS_CONFIG="$scratch/goaccess.conf"
export WRZDJ_GOACCESS_CALLS="$scratch/goaccess.log"
export WRZDJ_GOACCESS_INPUT="$scratch/goaccess.input"

expect_invalid() {
  local description="$1"
  shift
  if bash "$repo_root/deploy/scripts/analytics.sh" "$@" >"$scratch/output" 2>&1; then
    echo "$description unexpectedly succeeded" >&2
    cat "$scratch/output" >&2
    exit 1
  fi
  grep -Fq 'Usage:' "$scratch/output"
}

expect_invalid 'conflicting domain selectors' --api --app
expect_invalid 'scanner and domain selectors' --scanners --api
expect_invalid 'unknown option' --bogus
grep -Fq 'Unknown option: --bogus' "$scratch/output"
test ! -s "$WRZDJ_GOACCESS_CALLS"

bash "$repo_root/deploy/scripts/analytics.sh" --help > "$scratch/help"
grep -Fq 'Options:' "$scratch/help"
test ! -s "$WRZDJ_GOACCESS_CALLS"
bash "$repo_root/deploy/scripts/analytics.sh" --api --html -h > "$scratch/short-help"
grep -Fq 'Options:' "$scratch/short-help"
test ! -s "$WRZDJ_GOACCESS_CALLS"
bash "$repo_root/deploy/scripts/analytics.sh" --api
grep -Fq "$scratch/logs/api.example.test.access.log" "$WRZDJ_GOACCESS_CALLS"
bash "$repo_root/deploy/scripts/analytics.sh" --app
grep -Fq "$scratch/logs/app.example.test.access.log" "$WRZDJ_GOACCESS_CALLS"
bash "$repo_root/deploy/scripts/analytics.sh" --scanners
grep -Fq "$scratch/logs/default.access.log" "$WRZDJ_GOACCESS_CALLS"

printf '%s\n' '{"status":200,"request":"/ok"}' '{"status":404,"request":"/missing"}' \
  '{"status":503,"request":"/down"}' > "$scratch/logs/api.example.test.access.log"
bash "$repo_root/deploy/scripts/analytics.sh" --api --errors --html "$scratch/report.html" \
  > "$scratch/report.log"
grep -Fq -- "--config-file=$scratch/goaccess.conf --output=$scratch/report.html -" \
  "$WRZDJ_GOACCESS_CALLS"
printf '%s\n' '{"status":404,"request":"/missing"}' '{"status":503,"request":"/down"}' \
  > "$scratch/errors.expected"
cmp "$scratch/errors.expected" "$WRZDJ_GOACCESS_INPUT"
grep -Fq "HTML report: $scratch/report.html" "$scratch/report.log"

echo 'Analytics validates options, selects each log source, filters errors, and configures HTML output.'
