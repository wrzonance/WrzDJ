#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "Usage: $0" >&2
  exit 2
fi

# WrzDJ Nginx Setup Script
# Generates nginx configs from templates and installs them.
#
# Usage:
#   APP_DOMAIN=app.example.com API_DOMAIN=api.example.com ./deploy/setup-nginx.sh
#
# Optional:
#   PORT_API=8000         (default: 8000)
#   PORT_FRONTEND=3000    (default: 3000)
#   SSE_CONN_LIMIT=500    (default: 500) concurrent SSE streams per client address
#   WRZDJ_NGINX_VHOSTS_ONLY=1
#       Install only the two vhosts for APP_DOMAIN / API_DOMAIN. For a second
#       stack on a host that already runs WrzDJ (the testing environment): the
#       http-context includes in conf.d and the default catch-all belong to the
#       primary deploy and are left untouched.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/nginx"
# Override this path only for isolated validation; production uses /etc/nginx.
NGINX_ETC_DIR="${NGINX_ETC_DIR:-/etc/nginx}"
NGINX_SITES_AVAILABLE="$NGINX_ETC_DIR/sites-available"
NGINX_SITES_ENABLED="$NGINX_ETC_DIR/sites-enabled"
NGINX_CONF_D="$NGINX_ETC_DIR/conf.d"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-/etc/letsencrypt}"
CERTIFICATE_CHECKER="${CERTIFICATE_CHECKER:-/usr/local/bin/wrzdj-certificates-ready}"
NGINX_INSTALLER="${NGINX_INSTALLER:-/usr/local/bin/wrzdj-nginx-install}"
NGINX_CONFD_INSTALLER="${NGINX_CONFD_INSTALLER:-/usr/local/bin/wrzdj-nginx-confd-install}"

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
VHOSTS_ONLY="${WRZDJ_NGINX_VHOSTS_ONLY:-0}"
if [[ "$VHOSTS_ONLY" != 0 && "$VHOSTS_ONLY" != 1 ]]; then
  echo "ERROR: WRZDJ_NGINX_VHOSTS_ONLY must be 0 or 1 (got '$VHOSTS_ONLY')" >&2
  exit 1
fi
export PORT_API="${PORT_API:-8000}"
export PORT_FRONTEND="${PORT_FRONTEND:-3000}"
export SSE_CONN_LIMIT="${SSE_CONN_LIMIT:-500}"
export APP_DOMAIN
export API_DOMAIN

certificates_ready() {
  local domain="$1"
  if [ -n "$SUDO" ] && [ -x "$CERTIFICATE_CHECKER" ]; then
    $SUDO "$CERTIFICATE_CHECKER" "$domain"
    return
  fi
  local live_root="$LETSENCRYPT_DIR/live"
  if [ -e "$live_root" ] && [ ! -r "$live_root" ]; then return 2; fi
  local live_dir="$LETSENCRYPT_DIR/live/$domain"
  if [ ! -d "$live_dir" ]; then return 1; fi
  if [ ! -r "$live_dir" ]; then return 2; fi
  for filename in fullchain.pem privkey.pem; do
    local path="$live_dir/$filename"
    if [ -L "$path" ] && [ ! -e "$path" ]; then return 2; fi
    if [ ! -e "$path" ]; then return 1; fi
    if [ ! -r "$path" ] || [ ! -s "$path" ]; then return 2; fi
  done
  return 0
}

TLS_READY=1
for domain in "$API_DOMAIN" "$APP_DOMAIN" "$API_DOMAIN-rsa" "$APP_DOMAIN-rsa"; do
  probe_status=0
  certificates_ready "$domain" || probe_status=$?
  case "$probe_status" in
    0) ;;
    1) TLS_READY=0; break ;;
    *)
      echo "ERROR: Cannot inspect TLS certificates for $domain." >&2
      echo "       Install deploy/setup-user.sh or run setup-nginx.sh as root." >&2
      exit 1
      ;;
  esac
done

# The catch-all is only this invocation's to judge when it will be rewritten;
# in vhosts-only mode it belongs to the primary deploy and may already be TLS
# while the new hostnames still need their HTTP bootstrap.
has_installed_tls_config() {
  local config
  local -a configs=("$NGINX_SITES_AVAILABLE/$API_DOMAIN" "$NGINX_SITES_AVAILABLE/$APP_DOMAIN")
  [ "$VHOSTS_ONLY" -eq 0 ] && configs+=("$NGINX_SITES_AVAILABLE/default")
  for config in "${configs[@]}"; do
    if [ -f "$config" ] && grep -Eq '^[[:space:]]*ssl_certificate[[:space:]]' "$config"; then
      return 0
    fi
  done
  return 1
}

if [ "$TLS_READY" -eq 0 ] && has_installed_tls_config; then
  echo "ERROR: Existing HTTPS configuration found but its certificate lineages are unavailable." >&2
  echo "       Refusing to replace live TLS with the HTTP bootstrap." >&2
  exit 1
fi

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

if [[ ! "$SSE_CONN_LIMIT" =~ ^[0-9]+$ ]] || [ "$SSE_CONN_LIMIT" -lt 1 ]; then
  echo "ERROR: Invalid SSE_CONN_LIMIT: $SSE_CONN_LIMIT (must be a positive integer)" >&2
  exit 1
fi

if [ -n "$SUDO" ] && [ -d "$NGINX_SITES_AVAILABLE" ] &&
  { [ ! -x "$NGINX_INSTALLER" ] || [ ! -x "$NGINX_CONFD_INSTALLER" ]; }; then
  echo "ERROR: Required nginx install wrappers are missing or not executable." >&2
  echo "       Run deploy/setup-user.sh as root before using setup-nginx.sh." >&2
  exit 1
fi

# nginx 1.25.1 introduced the standalone `http2 on` directive and deprecated
# the older `listen ... http2` parameter. Probe the installed server only when
# this invocation will install configs. Generation-only setup can run before
# nginx is installed, so use the older syntax supported by the declared nginx
# minimum (Ubuntu 22.04's 1.18) in that mode.
nginx_version="not installed"
export HTTP2_LISTEN_OPTION=" http2"
export HTTP2_DIRECTIVE=""
if [ -d "$NGINX_SITES_AVAILABLE" ]; then
  if ! nginx_version_output="$(nginx -v 2>&1)"; then
    echo "ERROR: Could not determine nginx version using 'nginx -v'." >&2
    if [ -n "$nginx_version_output" ]; then
      printf '       nginx reported: %s\n' "$nginx_version_output" >&2
    fi
    exit 1
  fi
  nginx_version="$(sed -nE \
    's/^nginx version: nginx\/([0-9]+\.[0-9]+\.[0-9]+)([^0-9].*)?$/\1/p' \
    <<< "$nginx_version_output")"
  if [ -z "$nginx_version" ]; then
    echo "ERROR: Could not parse nginx version from 'nginx -v'." >&2
    printf '       nginx reported: %s\n' "$nginx_version_output" >&2
    exit 1
  fi
  IFS=. read -r nginx_major nginx_minor nginx_patch <<< "$nginx_version"
  if (( 10#$nginx_major > 1 ||
    (10#$nginx_major == 1 && 10#$nginx_minor > 25) ||
    (10#$nginx_major == 1 && 10#$nginx_minor == 25 && 10#$nginx_patch >= 1) )); then
    export HTTP2_LISTEN_OPTION=""
    export HTTP2_DIRECTIVE="http2 on;"
  fi
else
  echo "    nginx is not installed; using compatibility syntax for generated configs"
fi

echo "==> Generating nginx configs"
echo "    APP_DOMAIN:    $APP_DOMAIN"
echo "    API_DOMAIN:    $API_DOMAIN"
echo "    PORT_API:      $PORT_API"
echo "    PORT_FRONTEND: $PORT_FRONTEND"
echo "    SSE_CONN_LIMIT: $SSE_CONN_LIMIT"
echo "    nginx version: $nginx_version"
[ "$VHOSTS_ONLY" -eq 1 ] && echo "    mode:          vhosts only (shared conf.d and catch-all untouched)"

# envsubst only replaces the variables we specify, leaving nginx $vars untouched
# shellcheck disable=SC2016
VARS='${APP_DOMAIN} ${API_DOMAIN} ${PORT_API} ${PORT_FRONTEND} ${SSE_CONN_LIMIT} ${BOOTSTRAP_DOMAIN} ${BOOTSTRAP_LISTEN_OPTIONS} ${HTTP2_LISTEN_OPTION} ${HTTP2_DIRECTIVE}'

# Render one server block using its TLS-specific template or the shared
# HTTP-only bootstrap template while certificates are being issued.
render_vhost_config() {
  local destination="$1" tls_template="$2" bootstrap_domain="$3" bootstrap_listen_options="$4"
  local template="$TEMPLATE_DIR/$tls_template"

  if [ "$TLS_READY" -eq 0 ]; then
    template="$TEMPLATE_DIR/bootstrap.conf.template"
    export BOOTSTRAP_DOMAIN="$bootstrap_domain"
    export BOOTSTRAP_LISTEN_OPTIONS="$bootstrap_listen_options"
  else
    export BOOTSTRAP_DOMAIN=""
    export BOOTSTRAP_LISTEN_OPTIONS=""
  fi

  envsubst "$VARS" < "$template" > "$TEMPLATE_DIR/$destination"
  echo "    Generated: $TEMPLATE_DIR/$destination"
}

# A fresh host uses the HTTP-only template until all four certificate lineages
# exist, which lets certbot validate through HTTP.
render_vhost_config "$API_DOMAIN.conf" api.conf.template "$API_DOMAIN" ""
render_vhost_config "$APP_DOMAIN.conf" app.conf.template "$APP_DOMAIN" ""
if [ "$VHOSTS_ONLY" -eq 0 ]; then
  render_vhost_config default.conf default.conf.template "_" " default_server"
fi

install_shared_configs() {
  echo ""
  echo "==> Installing http-level nginx configs to conf.d"

  install_confd_config() {
    local src="$1"
    local dest_name="$2"

    # http-level configs go to conf.d (not a vhost)
    if [ -n "$SUDO" ]; then
      $SUDO "$NGINX_CONFD_INSTALLER" "$src"
    else
      $SUDO cp "$src" "$NGINX_CONF_D/$dest_name"
    fi
    echo "    Installed: $NGINX_CONF_D/$dest_name"
  }

  install_confd_config "$TEMPLATE_DIR/logging.conf" "wrzdj-logging.conf"
  install_confd_config "$TEMPLATE_DIR/tuning.conf" "wrzdj-tuning.conf"
}

# Snapshot of every vhost this run replaces, so a config that fails `nginx -t`
# can be rolled back instead of staying installed: nginx keeps serving the old
# config after a failed test, but the next reload, certificate renewal or
# reboot would load the broken file and take every vhost on the host down.
ROLLBACK_DIR=""
ROLLBACK_SITES=()

# install_vhost_config FILE SITE_NAME: copy one rendered vhost and enable it.
install_vhost_config() {
  local src="$1" site_name="$2"
  if [ -f "$NGINX_SITES_AVAILABLE/$site_name" ]; then
    cp -p "$NGINX_SITES_AVAILABLE/$site_name" "$ROLLBACK_DIR/$site_name"
  fi
  ROLLBACK_SITES+=("$site_name")
  if [ -n "$SUDO" ]; then
    # Use wrapper script (validates names, does cp + ln together)
    $SUDO "$NGINX_INSTALLER" "$src"
  else
    # Running as root — direct cp/ln
    cp "$src" "$NGINX_SITES_AVAILABLE/$site_name"
    ln -sf "$NGINX_SITES_AVAILABLE/$site_name" "$NGINX_SITES_ENABLED/$site_name"
  fi
  echo "    Installed: $NGINX_SITES_AVAILABLE/$site_name"
}

# Install to nginx if running as root / with sudo
# Put back what this run replaced (or remove what it newly added) after a
# failed `nginx -t`, then re-test so the restored tree is known good.
rollback_vhosts() {
  local site_name
  echo "==> Restoring the previously installed vhosts"
  for site_name in "${ROLLBACK_SITES[@]}"; do
    if [ -f "$ROLLBACK_DIR/$site_name" ]; then
      install_restored_vhost "$ROLLBACK_DIR/$site_name" "$site_name"
      echo "    Restored: $NGINX_SITES_AVAILABLE/$site_name"
    else
      remove_vhost "$site_name"
    fi
  done
  if $SUDO nginx -t >/dev/null 2>&1; then
    echo "    Restored configuration passes nginx -t"
  else
    echo "ERROR: the restored configuration still fails nginx -t; inspect $NGINX_SITES_AVAILABLE by hand" >&2
  fi
}

install_restored_vhost() {
  local saved="$1" site_name="$2"
  if [ -n "$SUDO" ]; then
    # The install wrapper names the site after the file, so stage it as such.
    cp "$saved" "$TEMPLATE_DIR/$site_name.conf"
    $SUDO "$NGINX_INSTALLER" "$TEMPLATE_DIR/$site_name.conf"
  else
    cp "$saved" "$NGINX_SITES_AVAILABLE/$site_name"
  fi
}

remove_vhost() {
  local site_name="$1"
  if [ -n "$SUDO" ]; then
    echo "    Cannot remove the new vhost $site_name without root; remove it by hand:" >&2
    echo "      sudo rm $NGINX_SITES_ENABLED/$site_name $NGINX_SITES_AVAILABLE/$site_name" >&2
    return
  fi
  rm -f "$NGINX_SITES_ENABLED/$site_name" "$NGINX_SITES_AVAILABLE/$site_name"
  echo "    Removed: $NGINX_SITES_AVAILABLE/$site_name (new this run)"
}

if [ -d "$NGINX_SITES_AVAILABLE" ]; then
  # Created only when installing: generation-only runs (no nginx on the box)
  # need nothing but envsubst.
  ROLLBACK_DIR="$(mktemp -d)"
  trap 'rm -rf "$ROLLBACK_DIR"' EXIT
  [ "$VHOSTS_ONLY" -eq 0 ] && install_shared_configs

  echo ""
  echo "==> Installing vhost configs to sites-available"
  install_vhost_config "$TEMPLATE_DIR/$API_DOMAIN.conf" "$API_DOMAIN"
  install_vhost_config "$TEMPLATE_DIR/$APP_DOMAIN.conf" "$APP_DOMAIN"
  [ "$VHOSTS_ONLY" -eq 0 ] && install_vhost_config "$TEMPLATE_DIR/default.conf" default

  echo ""
  echo "==> Testing nginx config"
  if $SUDO nginx -t; then
    if systemctl is-active --quiet nginx; then
      echo ""
      echo "==> Reloading nginx"
      $SUDO systemctl reload nginx
      echo "    Done!"
    else
      systemctl_status=$?
      if [ "$systemctl_status" -eq 3 ]; then
        echo "    nginx is not active; start it after reviewing the generated config."
      else
        echo "ERROR: Cannot determine whether nginx is active (systemctl exit $systemctl_status)." >&2
        exit 1
      fi
    fi
  else
    echo ""
    echo "ERROR: nginx config test failed. Fix the errors above before reloading."
    rollback_vhosts
    exit 1
  fi
else
  echo ""
  echo "==> /etc/nginx/sites-available not found — configs generated but not installed."
  echo "    Copy them manually:"
  if [ "$VHOSTS_ONLY" -eq 0 ]; then
    echo "      sudo cp $TEMPLATE_DIR/logging.conf /etc/nginx/conf.d/wrzdj-logging.conf"
    echo "      sudo cp $TEMPLATE_DIR/tuning.conf /etc/nginx/conf.d/wrzdj-tuning.conf"
  fi
  echo "      sudo cp $TEMPLATE_DIR/$API_DOMAIN.conf /etc/nginx/sites-available/$API_DOMAIN"
  echo "      sudo cp $TEMPLATE_DIR/$APP_DOMAIN.conf /etc/nginx/sites-available/$APP_DOMAIN"
  [ "$VHOSTS_ONLY" -eq 0 ] && echo "      sudo cp $TEMPLATE_DIR/default.conf /etc/nginx/sites-available/default"
fi

echo ""
echo "==> Next steps:"
if [ "$TLS_READY" -eq 0 ]; then
  echo "    TLS certificates are not complete; HTTP bootstrap remains active."
  echo "    Replace admin@yourdomain.com with the ACME account address for this host."
  echo "    1. Obtain ECDSA certificates with the HTTP bootstrap:"
  echo "       sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name $API_DOMAIN --key-type ecdsa -d $API_DOMAIN"
  echo "       sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name $APP_DOMAIN --key-type ecdsa -d $APP_DOMAIN"
  echo "    2. Obtain RSA compatibility certificates:"
  echo "       sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name $API_DOMAIN-rsa --key-type rsa -d $API_DOMAIN"
  echo "       sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name $APP_DOMAIN-rsa --key-type rsa -d $APP_DOMAIN"
  echo "    3. Re-run setup-nginx.sh to install HTTPS vhosts."
else
  echo "    1. Verify: curl -I https://$API_DOMAIN/health"
  echo "    2. Verify JSON logs: tail -1 /var/log/nginx/$API_DOMAIN.access.log | python3 -m json.tool"
  echo "    3. Analytics: ./deploy/scripts/analytics.sh --api"
fi
