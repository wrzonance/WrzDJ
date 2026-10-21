#!/usr/bin/env bash
set -euo pipefail

# WrzDJ Analytics — GoAccess convenience wrapper
#
# Usage:
#   analytics.sh              Interactive prompt: pick log file, terminal mode
#   analytics.sh --api        API traffic (terminal)
#   analytics.sh --app        Frontend traffic (terminal)
#   analytics.sh --scanners   Bot/scanner traffic from catch-all block
#   analytics.sh --errors     4xx/5xx only (pre-filtered)
#   analytics.sh --html [PATH]  Generate HTML report (default: /tmp/wrzdj-analytics.html)
#
# Combine flags:
#   analytics.sh --api --html /tmp/api.html
#   analytics.sh --app --errors

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GOACCESS_CONF="${WRZDJ_ANALYTICS_CONFIG:-$SCRIPT_DIR/../nginx/goaccess.conf}"
LOG_DIR="${WRZDJ_ANALYTICS_LOG_DIR:-/var/log/nginx}"

# Defaults
LOG_FILE=""
HTML_MODE=false
HTML_PATH="/tmp/wrzdj-analytics.html"
ERRORS_ONLY=false
DOMAIN_FILTER=""
SELECTOR_SET=false

usage() {
  local status="${1:-0}"
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --api          Analyze API traffic (${LOG_DIR}/api.*.access.log)
  --app          Analyze frontend traffic (${LOG_DIR}/app.*.access.log)
  --scanners     Analyze scanner/bot traffic (${LOG_DIR}/default.access.log)
  --errors       Filter to 4xx/5xx responses only
  --html [PATH]  Generate HTML report (default: ${HTML_PATH})
  -h, --help     Show this help

Examples:
  $(basename "$0") --api                    # API traffic, terminal
  $(basename "$0") --app --html             # Frontend HTML report
  $(basename "$0") --api --errors           # API errors only
  $(basename "$0") --scanners              # Scanner traffic
  $(basename "$0") --api --html /tmp/a.html # Custom output path
EOF
  exit "$status"
}

set_log_selector() {
  local selector="$1"
  if $SELECTOR_SET; then
    echo "Only one log source may be selected (--api, --app, or --scanners)" >&2
    usage 2
  fi
  SELECTOR_SET=true
  case "$selector" in
    api|app) DOMAIN_FILTER="$selector" ;;
    scanners) LOG_FILE="$LOG_DIR/default.access.log" ;;
  esac
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api)
      set_log_selector api
      shift
      ;;
    --app)
      set_log_selector app
      shift
      ;;
    --scanners)
      set_log_selector scanners
      shift
      ;;
    --errors)
      ERRORS_ONLY=true
      shift
      ;;
    --html)
      HTML_MODE=true
      # Treat any dash-prefixed token as an option, including the short -h alias.
      # Use ./-name when an output filename starts with a dash.
      if [[ ${2:-} && ! ${2:-} == -* ]]; then
        HTML_PATH="$2"
        shift
      fi
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage 2
      ;;
  esac
done

# Resolve log file from domain filter
if [[ -z "$LOG_FILE" && -n "$DOMAIN_FILTER" ]]; then
  # Find the matching log file (e.g., api.wrzdj.com.access.log)
  MATCHES=()
  for f in "$LOG_DIR"/"${DOMAIN_FILTER}".*.access.log; do
    [[ -f "$f" ]] && MATCHES+=("$f")
  done

  if [[ ${#MATCHES[@]} -eq 0 ]]; then
    echo "No log files found matching ${LOG_DIR}/${DOMAIN_FILTER}.*.access.log" >&2
    echo "Available logs:" >&2
    ls "$LOG_DIR"/*.access.log 2>/dev/null || echo "  (none)" >&2
    exit 1
  elif [[ ${#MATCHES[@]} -eq 1 ]]; then
    LOG_FILE="${MATCHES[0]}"
  else
    echo "Multiple matches — pick one:" >&2
    select f in "${MATCHES[@]}"; do
      LOG_FILE="$f"
      break
    done
  fi
fi

# Interactive mode if no log file selected
if [[ -z "$LOG_FILE" ]]; then
  echo "Available log files:"
  LOGS=()
  for f in "$LOG_DIR"/*.access.log; do
    [[ -f "$f" ]] && LOGS+=("$f")
  done

  if [[ ${#LOGS[@]} -eq 0 ]]; then
    echo "  No .access.log files found in $LOG_DIR" >&2
    exit 1
  fi

  select f in "${LOGS[@]}"; do
    LOG_FILE="$f"
    break
  done
fi

# Validate
if [[ ! -f "$LOG_FILE" ]]; then
  echo "Log file not found: $LOG_FILE" >&2
  exit 1
fi

if ! command -v goaccess &>/dev/null; then
  echo "GoAccess is not installed. Install with: sudo apt install goaccess" >&2
  exit 1
fi

if [[ ! -f "$GOACCESS_CONF" ]]; then
  echo "GoAccess config not found: $GOACCESS_CONF" >&2
  echo "Expected at: deploy/nginx/goaccess.conf" >&2
  exit 1
fi

echo "Log file: $LOG_FILE"
echo "Lines:    $(wc -l < "$LOG_FILE")"

# Build goaccess command
GOACCESS_ARGS=(
  "--config-file=$GOACCESS_CONF"
)

if $HTML_MODE; then
  GOACCESS_ARGS+=("--output=$HTML_PATH")
fi

# Run with optional error filtering
if $ERRORS_ONLY; then
  echo "Filter:   4xx/5xx only"
  # Pre-filter: grep for status codes 4xx/5xx in JSON (status is unquoted number).
  # Anchored to line start to avoid false positives from URI content.
  grep -E '^\{.*"status":[45][0-9]{2},' "$LOG_FILE" | goaccess "${GOACCESS_ARGS[@]}" -
else
  goaccess "$LOG_FILE" "${GOACCESS_ARGS[@]}"
fi

if $HTML_MODE; then
  echo ""
  echo "HTML report: $HTML_PATH"
  echo "View with:   xdg-open $HTML_PATH  (or scp to local machine)"
fi
