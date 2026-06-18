#!/usr/bin/env bash
set -euo pipefail

# WrzDJ Nginx Setup Script
# Generates nginx configs from templates and installs them.
#
# Usage:
#   APP_DOMAIN=app.example.com API_DOMAIN=api.example.com ./deploy/setup-nginx.sh
#
# Optional:
#   PORT_API=8000         (default: 8000)
#   PORT_FRONTEND=3000    (default: 3000)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/nginx"

# Use sudo only when not running as root
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

# Required variables
: "${APP_DOMAIN:?APP_DOMAIN is required (e.g. app.example.com)}"
: "${API_DOMAIN:?API_DOMAIN is required (e.g. api.example.com)}"

# Validate domain names (prevent path traversal and config injection)
validate_domain() {
  local domain="$1"
  if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
    echo "ERROR: Invalid domain name: $domain" >&2
    exit 1
  fi
}
validate_domain "$APP_DOMAIN"
validate_domain "$API_DOMAIN"

# Optional with defaults
export PORT_API="${PORT_API:-8000}"
export PORT_FRONTEND="${PORT_FRONTEND:-3000}"
export APP_DOMAIN
export API_DOMAIN

# Validate port numbers
validate_port() {
  local port="$1" name="$2"
  if [[ ! "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "ERROR: Invalid port for $name: $port (must be 1-65535)" >&2
    exit 1
  fi
}
validate_port "$PORT_API" "PORT_API"
validate_port "$PORT_FRONTEND" "PORT_FRONTEND"

echo "==> Generating nginx configs"
echo "    APP_DOMAIN:    $APP_DOMAIN"
echo "    API_DOMAIN:    $API_DOMAIN"
echo "    PORT_API:      $PORT_API"
echo "    PORT_FRONTEND: $PORT_FRONTEND"

# envsubst only replaces the variables we specify, leaving nginx $vars untouched
# shellcheck disable=SC2016
VARS='${APP_DOMAIN} ${API_DOMAIN} ${PORT_API} ${PORT_FRONTEND}'

# Generate API config
envsubst "$VARS" < "$TEMPLATE_DIR/api.conf.template" \
  > "$TEMPLATE_DIR/$API_DOMAIN.conf"
echo "    Generated: $TEMPLATE_DIR/$API_DOMAIN.conf"

# Generate frontend config
envsubst "$VARS" < "$TEMPLATE_DIR/app.conf.template" \
  > "$TEMPLATE_DIR/$APP_DOMAIN.conf"
echo "    Generated: $TEMPLATE_DIR/$APP_DOMAIN.conf"

# Generate default catch-all server block
envsubst "$VARS" < "$TEMPLATE_DIR/default.conf.template" \
  > "$TEMPLATE_DIR/default.conf"
echo "    Generated: $TEMPLATE_DIR/default.conf"

# Install to nginx if running as root / with sudo
if [ -d /etc/nginx/sites-available ]; then
  echo ""
  echo "==> Installing http-level nginx configs to conf.d"

  install_confd_config() {
    local src="$1"
    local dest_name="$2"

    # http-level configs go to conf.d (not a vhost)
    if [ -n "$SUDO" ] && [ -x /usr/local/bin/wrzdj-nginx-confd-install ]; then
      $SUDO /usr/local/bin/wrzdj-nginx-confd-install "$src"
    else
      cp "$src" "/etc/nginx/conf.d/$dest_name"
    fi
    echo "    Installed: /etc/nginx/conf.d/$dest_name"
  }

  install_confd_config "$TEMPLATE_DIR/logging.conf" "wrzdj-logging.conf"
  install_confd_config "$TEMPLATE_DIR/tuning.conf" "wrzdj-tuning.conf"

  echo ""
  echo "==> Installing vhost configs to sites-available"

  if [ -n "$SUDO" ] && [ -x /usr/local/bin/wrzdj-nginx-install ]; then
    # Use wrapper script (validates names, does cp + ln together)
    $SUDO /usr/local/bin/wrzdj-nginx-install "$TEMPLATE_DIR/$API_DOMAIN.conf"
    $SUDO /usr/local/bin/wrzdj-nginx-install "$TEMPLATE_DIR/$APP_DOMAIN.conf"
    $SUDO /usr/local/bin/wrzdj-nginx-install "$TEMPLATE_DIR/default.conf"
  else
    # Running as root — direct cp/ln
    cp "$TEMPLATE_DIR/$API_DOMAIN.conf" "/etc/nginx/sites-available/$API_DOMAIN"
    cp "$TEMPLATE_DIR/$APP_DOMAIN.conf" "/etc/nginx/sites-available/$APP_DOMAIN"
    cp "$TEMPLATE_DIR/default.conf" "/etc/nginx/sites-available/default"
    ln -sf "/etc/nginx/sites-available/$API_DOMAIN" "/etc/nginx/sites-enabled/$API_DOMAIN"
    ln -sf "/etc/nginx/sites-available/$APP_DOMAIN" "/etc/nginx/sites-enabled/$APP_DOMAIN"
    ln -sf "/etc/nginx/sites-available/default" "/etc/nginx/sites-enabled/default"
  fi

  echo "    Installed: /etc/nginx/sites-available/$API_DOMAIN"
  echo "    Installed: /etc/nginx/sites-available/$APP_DOMAIN"
  echo "    Installed: /etc/nginx/sites-available/default (catch-all)"

  echo ""
  echo "==> Testing nginx config"
  if $SUDO nginx -t; then
    echo ""
    echo "==> Reloading nginx"
    $SUDO systemctl reload nginx
    echo "    Done!"
  else
    echo ""
    echo "ERROR: nginx config test failed. Fix the errors above before reloading."
    exit 1
  fi
else
  echo ""
  echo "==> /etc/nginx/sites-available not found — configs generated but not installed."
  echo "    Copy them manually:"
  echo "      sudo cp $TEMPLATE_DIR/logging.conf /etc/nginx/conf.d/wrzdj-logging.conf"
  echo "      sudo cp $TEMPLATE_DIR/tuning.conf /etc/nginx/conf.d/wrzdj-tuning.conf"
  echo "      sudo cp $TEMPLATE_DIR/$API_DOMAIN.conf /etc/nginx/sites-available/$API_DOMAIN"
  echo "      sudo cp $TEMPLATE_DIR/$APP_DOMAIN.conf /etc/nginx/sites-available/$APP_DOMAIN"
  echo "      sudo cp $TEMPLATE_DIR/default.conf /etc/nginx/sites-available/default"
fi

# --- Migration: ensure overlay location block exists for existing deployments ---
# The app.conf.template now includes a dedicated nginx location block for
# /e/*/overlay that sets CSP frame-ancestors * (allows OBS/streaming embeds).
# Existing deployments that re-run setup-nginx.sh get this automatically via
# the template re-generation above. This section just confirms it.
if [ -d /etc/nginx/sites-available ]; then
  INSTALLED_APP="/etc/nginx/sites-available/$APP_DOMAIN"
  if [ -f "$INSTALLED_APP" ] && ! grep -q "frame-ancestors" "$INSTALLED_APP"; then
    echo ""
    echo "==> Migration note:"
    echo "    The installed nginx config for $APP_DOMAIN is missing the overlay"
    echo "    location block (CSP frame-ancestors for OBS embeds)."
    echo "    It was updated above — nginx will pick it up after reload."
  fi
fi

echo ""
echo "==> Next steps:"
echo "    1. Set up SSL: sudo wrzdj-certbot --nginx -d $API_DOMAIN -d $APP_DOMAIN"
echo "    2. Verify: curl -I https://$API_DOMAIN/health"
echo "    3. Verify JSON logs: tail -1 /var/log/nginx/$API_DOMAIN.access.log | python3 -m json.tool"
echo "    4. Analytics: ./deploy/scripts/analytics.sh --api"
