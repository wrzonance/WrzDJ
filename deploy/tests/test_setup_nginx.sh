#!/usr/bin/env bash
set -euo pipefail

# Regression coverage for #798, fixed by f95bd209.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
nginx_image="nginx:1.31-alpine@sha256:72aeb3308ef6cb3118242fb16389518923916dfa206e32d1a8377acc328b9870"
shell_image="ubuntu:24.04@sha256:c4a8d5503dfb2a3eb8ab5f807da5bc69a85730fb49b5cfca2330194ebcc41c7b"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

nginx_root="$tmp_dir/nginx"
bin_dir="$tmp_dir/bin"
mkdir -p "$nginx_root"/{sites-available,sites-enabled,conf.d} "$bin_dir"
mkdir -p "$tmp_dir/letsencrypt"

cat > "$bin_dir/id" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = "-u" ]; then
  printf '1000\n'
else
  /usr/bin/id "$@"
fi
SH
chmod +x "$bin_dir/id"

cat > "$bin_dir/sudo" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SUDO_LOG:?}"
exec "$@"
SH
chmod +x "$bin_dir/sudo"

cat > "$bin_dir/nginx" <<'SH'
#!/usr/bin/env bash
[ "${1:-}" = "-t" ]
SH
chmod +x "$bin_dir/nginx"

cat > "$bin_dir/systemctl" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = "is-active" ]; then
  case "${SYSTEMCTL_MODE:-active}" in
    active) exit 0 ;;
    inactive) exit 3 ;;
    *) exit 1 ;;
  esac
fi
if [ "${1:-}" = "reload" ] && [ "${2:-}" = "nginx" ]; then
  touch "${RELOAD_MARKER:?}"
  exit 0
fi
exit 1
SH
chmod +x "$bin_dir/systemctl"

nginx_installer="$tmp_dir/nginx-installer"
cat > "$nginx_installer" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
name="$(basename "$1" .conf)"
cp "$1" "$NGINX_ETC_DIR/sites-available/$name"
ln -sfn "$NGINX_ETC_DIR/sites-available/$name" "$NGINX_ETC_DIR/sites-enabled/$name"
SH
chmod +x "$nginx_installer"
confd_installer="$tmp_dir/confd-installer"
cat > "$confd_installer" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cp "$1" "$NGINX_ETC_DIR/conf.d/wrzdj-$(basename "$1")"
SH
chmod +x "$confd_installer"

certificate_checker="$bin_dir/certificates-ready"
cat > "$certificate_checker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
domain="$1"
test -s "$LETSENCRYPT_DIR/live/$domain/fullchain.pem"
test -s "$LETSENCRYPT_DIR/live/$domain/privkey.pem"
SH
chmod +x "$certificate_checker"

export SUDO_LOG="$tmp_dir/sudo.log"
export RELOAD_MARKER="$tmp_dir/reloaded"
run_setup() {
  PATH="$bin_dir:$PATH" \
  NGINX_ETC_DIR="$nginx_root" \
  LETSENCRYPT_DIR="$tmp_dir/letsencrypt" \
  CERTIFICATE_CHECKER="$certificate_checker" \
  NGINX_INSTALLER="$nginx_installer" \
  NGINX_CONFD_INSTALLER="$confd_installer" \
  APP_DOMAIN=app.example.test \
  API_DOMAIN=api.example.test \
    bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/setup.log" || {
    cat "$tmp_dir/setup.log"
    exit 1
  }
}

write_nginx_test_config() {
  cat > "$nginx_root/nginx.conf" <<'NGINX'
events {}
http {
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
NGINX
}

assert_nginx_config() {
  for name in api.example.test app.example.test default "$@"; do
    rm -f "$nginx_root/sites-enabled/$name"
    cp "$nginx_root/sites-available/$name" "$nginx_root/sites-enabled/$name"
  done
  write_nginx_test_config
  docker run --rm \
    -v "$nginx_root:/etc/nginx:ro" \
    -v "$tmp_dir/letsencrypt:/etc/letsencrypt:ro" \
    "$nginx_image" nginx -t -c /etc/nginx/nginx.conf
}

run_setup

for path in \
  "$nginx_root/conf.d/wrzdj-logging.conf" \
  "$nginx_root/conf.d/wrzdj-tuning.conf" \
  "$nginx_root/sites-available/api.example.test" \
  "$nginx_root/sites-available/app.example.test" \
  "$nginx_root/sites-available/default"; do
  test -f "$path"
done

test -L "$nginx_root/sites-enabled/api.example.test"
test -L "$nginx_root/sites-enabled/app.example.test"
test -L "$nginx_root/sites-enabled/default"
assert_nginx_config
test -f "$RELOAD_MARKER"

if grep -Fq 'ssl_certificate' "$nginx_root/sites-available/api.example.test"; then
  echo "bootstrap unexpectedly contains TLS certificate directives" >&2
  exit 1
fi
grep -Fq "$confd_installer" "$SUDO_LOG"
grep -Fq "$nginx_installer" "$SUDO_LOG"
if grep -Eq '(^| )cp ' "$SUDO_LOG" || grep -Eq '(^| )ln ' "$SUDO_LOG"; then
  echo "non-root setup used unprivileged copy fallback" >&2
  exit 1
fi
grep -Fq 'server_tokens off;' "$nginx_root/sites-available/api.example.test"

grep -Fq -- '--nginx --agree-tos --email admin@yourdomain.com --cert-name api.yourdomain.com --key-type ecdsa -d api.yourdomain.com' \
  "$repo_root/deploy/DEPLOYMENT.md"
grep -Fq -- '--nginx --agree-tos --email admin@yourdomain.com --cert-name api.yourdomain.com-rsa --key-type rsa -d api.yourdomain.com' \
  "$repo_root/deploy/DEPLOYMENT.md"
grep -Fq "certbot_args+=(\"--cert-name\" \"\$cert_name\")" \
  "$repo_root/deploy/setup-user.sh"
grep -Fq "certbot_args+=(\"--key-type\" \"\$key_type\")" \
  "$repo_root/deploy/setup-user.sh"
grep -Fq 'wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name api.example.test-rsa --key-type rsa -d api.example.test' \
  "$tmp_dir/setup.log"

wrapper="$tmp_dir/wrzdj-certbot"
sed -n '/^cat > \/usr\/local\/bin\/wrzdj-certbot/,/^WRAPPER$/p' \
  "$repo_root/deploy/setup-user.sh" | sed '1d;$d' > "$wrapper"
chmod +x "$wrapper"
fake_certbot="$tmp_dir/certbot"
cat > "$fake_certbot" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" > "${CERTBOT_LOG:?}"
SH
chmod +x "$fake_certbot"
sed -i "s|/usr/bin/certbot|$fake_certbot|g" "$wrapper"
if "$wrapper" --nginx --key-type dsa -d api.example.test; then
  echo "wrapper accepted an unsupported key type" >&2
  exit 1
fi
if "$wrapper" --nginx --cert-name '../../etc' -d api.example.test; then
  echo "wrapper accepted a path traversal certificate name" >&2
  exit 1
fi
if "$wrapper" --nginx --cert-name other.example.test -d api.example.test; then
  echo "wrapper accepted a certificate name for another domain" >&2
  exit 1
fi
CERTBOT_LOG="$tmp_dir/certbot.log" "$wrapper" --nginx --agree-tos --email admin@example.test \
  --cert-name api.example.test-rsa --key-type rsa -d api.example.test
grep -Fq -- '--nginx --non-interactive --agree-tos --email admin@example.test --cert-name api.example.test-rsa --key-type rsa -d api.example.test' \
  "$tmp_dir/certbot.log"

checker_wrapper="$tmp_dir/wrzdj-certificates-ready"
sed -n '/^cat > \/usr\/local\/bin\/wrzdj-certificates-ready/,/^WRAPPER$/p' \
  "$repo_root/deploy/setup-user.sh" | sed '1d;$d' > "$checker_wrapper"
chmod +x "$checker_wrapper"
checker_root="$tmp_dir/checker-letsencrypt"
mkdir -p "$checker_root/live/api.example.test"
printf cert > "$checker_root/live/api.example.test/fullchain.pem"
printf key > "$checker_root/live/api.example.test/privkey.pem"
sed -i "s|/etc/letsencrypt|$checker_root|g" "$checker_wrapper"
"$checker_wrapper" api.example.test
rm "$checker_root/live/api.example.test/privkey.pem"
if "$checker_wrapper" api.example.test; then
  echo "certificate checker accepted an incomplete lineage" >&2
  exit 1
fi
mkdir -p "$checker_root/live/api.example.test"
ln -s "$checker_root/archive/missing.pem" "$checker_root/live/api.example.test/privkey.pem"
checker_status=0
"$checker_wrapper" api.example.test || checker_status=$?
if [ "$checker_status" -ne 2 ]; then
  echo "certificate checker accepted an unreadable lineage" >&2
  exit 1
fi
if "$checker_wrapper" '../../etc'; then
  echo "certificate checker accepted a path traversal domain" >&2
  exit 1
fi

permission_root="$tmp_dir/permission-check"
mkdir -p "$permission_root"
cp -a "$repo_root/deploy" "$permission_root/deploy"
chmod -R a+rwX "$permission_root/deploy/nginx"
mkdir -p "$permission_root/nginx"/{sites-available,sites-enabled,conf.d} "$permission_root/letsencrypt/live"
chmod 755 "$tmp_dir" "$permission_root" "$permission_root/letsencrypt"
chmod 700 "$permission_root/letsencrypt/live"
if docker run --rm --user 65534:65534 \
  -v "$permission_root:/workspace:ro" \
  "$shell_image" bash -c \
  "NGINX_ETC_DIR=/workspace/nginx LETSENCRYPT_DIR=/workspace/letsencrypt CERTIFICATE_CHECKER=/workspace/missing-checker APP_DOMAIN=app.example.test API_DOMAIN=api.example.test bash /workspace/deploy/setup-nginx.sh" \
  > "$tmp_dir/permission.log" 2>&1; then
  echo "non-root setup bypassed unreadable certificate storage" >&2
  exit 1
fi
grep -Fq 'Cannot inspect' "$tmp_dir/permission.log" || {
  cat "$tmp_dir/permission.log"
  exit 1
}

missing_wrapper_root="$tmp_dir/missing-wrapper"
mkdir -p "$missing_wrapper_root"/{sites-available,sites-enabled,conf.d}
if PATH="$bin_dir:$PATH" NGINX_ETC_DIR="$missing_wrapper_root" \
  LETSENCRYPT_DIR="$tmp_dir/letsencrypt" CERTIFICATE_CHECKER="$certificate_checker" \
  NGINX_INSTALLER="$tmp_dir/missing-nginx-installer" \
  NGINX_CONFD_INSTALLER="$tmp_dir/missing-confd-installer" \
  APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/missing-wrapper.log" 2>&1; then
  echo "setup bypassed missing non-root install wrappers" >&2
  exit 1
fi
grep -Fq 'Required nginx install wrappers are missing' "$tmp_dir/missing-wrapper.log"

mkdir -p "$tmp_dir/letsencrypt/live"
for domain in api.example.test app.example.test api.example.test-rsa app.example.test-rsa; do
  mkdir -p "$tmp_dir/letsencrypt/live/$domain"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj "/CN=$domain" \
    -keyout "$tmp_dir/letsencrypt/live/$domain/privkey.pem" \
    -out "$tmp_dir/letsencrypt/live/$domain/fullchain.pem" >/dev/null 2>&1
done
mkdir -p "$tmp_dir/letsencrypt"
cat > "$tmp_dir/letsencrypt/options-ssl-nginx.conf" <<'SSL'
ssl_protocols TLSv1.2 TLSv1.3;
SSL
openssl dhparam -dsaparam -out "$tmp_dir/letsencrypt/ssl-dhparams.pem" 2048 >/dev/null 2>&1

run_setup
assert_nginx_config
grep -Fq '/etc/letsencrypt/live/api.example.test/fullchain.pem' \
  "$nginx_root/sites-available/api.example.test"
grep -Fq 'ssl_certificate /etc/letsencrypt/live/api.example.test-rsa/fullchain.pem;' \
  "$nginx_root/sites-available/api.example.test"
grep -Fq '/etc/letsencrypt/live/app.example.test-rsa/fullchain.pem' \
  "$nginx_root/sites-available/app.example.test"
grep -Fq 'HTTP bootstrap first' "$repo_root/deploy/nginx/api.conf.template"
grep -Fq 'HTTP bootstrap first' "$repo_root/deploy/nginx/app.conf.template"

mv "$tmp_dir/letsencrypt/live/api.example.test/fullchain.pem" \
  "$tmp_dir/letsencrypt/live/api.example.test/fullchain.pem.saved"
if PATH="$bin_dir:$PATH" NGINX_ETC_DIR="$nginx_root" LETSENCRYPT_DIR="$tmp_dir/letsencrypt" \
  CERTIFICATE_CHECKER="$certificate_checker" NGINX_INSTALLER="$nginx_installer" \
  NGINX_CONFD_INSTALLER="$confd_installer" APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/downgrade.log" 2>&1; then
  echo "setup downgraded an existing TLS vhost" >&2
  exit 1
fi
grep -Fq 'Refusing to replace live TLS' "$tmp_dir/downgrade.log"

mv "$tmp_dir/letsencrypt/live/api.example.test/fullchain.pem.saved" \
  "$tmp_dir/letsencrypt/live/api.example.test/fullchain.pem"

if SYSTEMCTL_MODE=error PATH="$bin_dir:$PATH" NGINX_ETC_DIR="$nginx_root" \
  LETSENCRYPT_DIR="$tmp_dir/letsencrypt" CERTIFICATE_CHECKER="$certificate_checker" \
  NGINX_INSTALLER="$nginx_installer" NGINX_CONFD_INSTALLER="$confd_installer" \
  APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/systemctl-error.log" 2>&1; then
  echo "setup treated systemctl failure as inactive" >&2
  exit 1
fi
grep -Fq 'Cannot determine whether nginx is active' "$tmp_dir/systemctl-error.log"

SYSTEMCTL_MODE=inactive PATH="$bin_dir:$PATH" NGINX_ETC_DIR="$nginx_root" \
  LETSENCRYPT_DIR="$tmp_dir/letsencrypt" CERTIFICATE_CHECKER="$certificate_checker" \
  NGINX_INSTALLER="$nginx_installer" NGINX_CONFD_INSTALLER="$confd_installer" \
  APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/systemctl-inactive.log" 2>&1
grep -Fq 'nginx is not active' "$tmp_dir/systemctl-inactive.log"


# Vhosts-only mode (#844): a second stack on the same host (the testing
# environment) installs only its own two vhosts. The shared http-context
# includes and the default catch-all belong to the primary deploy and must
# not be rewritten, and an existing TLS catch-all must not block the HTTP
# bootstrap of the new hostnames.
shared_manifest() {
  sha256sum "$nginx_root/conf.d/wrzdj-logging.conf" "$nginx_root/conf.d/wrzdj-tuning.conf" \
    "$nginx_root/sites-available/default" "$repo_root/deploy/nginx/default.conf"
}
shared_before="$(shared_manifest)"
run_vhosts_only() {
  WRZDJ_NGINX_VHOSTS_ONLY=1 PATH="$bin_dir:$PATH" NGINX_ETC_DIR="$nginx_root" \
    LETSENCRYPT_DIR="$tmp_dir/letsencrypt" CERTIFICATE_CHECKER="$certificate_checker" \
    NGINX_INSTALLER="$nginx_installer" NGINX_CONFD_INSTALLER="$confd_installer" \
    APP_DOMAIN=testing.example.test API_DOMAIN=api-testing.example.test \
    PORT_API=8001 PORT_FRONTEND=3001 \
    bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/vhosts-only.log" 2>&1 || {
    cat "$tmp_dir/vhosts-only.log" >&2
    exit 1
  }
}
rm -f "$RELOAD_MARKER"
run_vhosts_only
for name in testing.example.test api-testing.example.test; do
  test -f "$nginx_root/sites-available/$name"
  test -L "$nginx_root/sites-enabled/$name"
  if grep -Fq 'ssl_certificate' "$nginx_root/sites-available/$name"; then
    echo "vhosts-only bootstrap for $name unexpectedly contains TLS directives" >&2
    exit 1
  fi
done
test "$(shared_manifest)" = "$shared_before"
test -f "$RELOAD_MARKER"
if grep -Fq 'default.conf' "$tmp_dir/vhosts-only.log"; then
  echo "vhosts-only mode reported touching the default catch-all" >&2
  exit 1
fi

for domain in testing.example.test api-testing.example.test \
  testing.example.test-rsa api-testing.example.test-rsa; do
  mkdir -p "$tmp_dir/letsencrypt/live/$domain"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj "/CN=$domain" \
    -keyout "$tmp_dir/letsencrypt/live/$domain/privkey.pem" \
    -out "$tmp_dir/letsencrypt/live/$domain/fullchain.pem" >/dev/null 2>&1
done
run_vhosts_only
grep -Fq 'proxy_pass http://127.0.0.1:8001;' "$nginx_root/sites-available/api-testing.example.test"
grep -Fq 'proxy_pass http://127.0.0.1:3001;' "$nginx_root/sites-available/testing.example.test"
grep -Fq 'connect-src '"'"'self'"'"' https://api-testing.example.test' \
  "$nginx_root/sites-available/testing.example.test"
test "$(shared_manifest)" = "$shared_before"
assert_nginx_config testing.example.test api-testing.example.test

printf 'setup-nginx provisioning contract passed\n'
