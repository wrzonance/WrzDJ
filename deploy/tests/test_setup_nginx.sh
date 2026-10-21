#!/usr/bin/env bash
set -euo pipefail

# Regression coverage for #798, fixed by f95bd209.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_root="$repo_root"
nginx_image="nginx:1.31-alpine@sha256:72aeb3308ef6cb3118242fb16389518923916dfa206e32d1a8377acc328b9870"
shell_image="ubuntu:24.04@sha256:c4a8d5503dfb2a3eb8ab5f807da5bc69a85730fb49b5cfca2330194ebcc41c7b"
tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

test_root="$tmp_dir/checkout"
mkdir -p "$test_root"
cp -a "$source_root/deploy" "$test_root/deploy"
repo_root="$test_root"

source_nginx_manifest() {
  find "$source_root/deploy/nginx" -maxdepth 1 -type f -printf '%f\0' |
    sort -z |
    while IFS= read -r -d '' name; do
      printf '%s ' "$name"
      stat -c '%a %y ' "$source_root/deploy/nginx/$name"
      sha256sum "$source_root/deploy/nginx/$name" | cut -d ' ' -f1
    done
}
source_nginx_before="$(source_nginx_manifest)"

nginx_root="$tmp_dir/nginx"
bin_dir="$tmp_dir/bin"
mkdir -p "$nginx_root"/{sites-available,sites-enabled,conf.d} "$bin_dir"
mkdir -p "$tmp_dir/letsencrypt"
rm -f "$repo_root/deploy/nginx/invalid-probe-app.example.test.conf" \
  "$repo_root/deploy/nginx/invalid-probe-api.example.test.conf" \
  "$repo_root/deploy/nginx/invalid-format-app.example.test.conf" \
  "$repo_root/deploy/nginx/invalid-format-api.example.test.conf"

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
case "${1:-}" in
  -v)
    [ "${NGINX_TEST_PROBE_MODE:-ok}" = "ok" ] || exit 1
    printf '%s\n' "${NGINX_TEST_VERSION_OUTPUT:-nginx version: nginx/${NGINX_TEST_VERSION:-1.31.0}}" >&2
    ;;
  -t) exit 0 ;;
  *) exit 2 ;;
esac
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
  NGINX_TEST_VERSION="${NGINX_TEST_VERSION:-1.31.0}" \
  NGINX_TEST_VERSION_OUTPUT="${NGINX_TEST_VERSION_OUTPUT:-}" \
  NGINX_TEST_PROBE_MODE="${NGINX_TEST_PROBE_MODE:-ok}" \
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

expect_version_probe_failure() {
  local expected_error="$1" app_domain="$2" api_domain="$3"
  local probe_status=0
  PATH="$bin_dir:$PATH" \
  NGINX_TEST_VERSION="${NGINX_TEST_VERSION:-1.31.0}" \
  NGINX_TEST_VERSION_OUTPUT="${NGINX_TEST_VERSION_OUTPUT:-}" \
  NGINX_TEST_PROBE_MODE="${NGINX_TEST_PROBE_MODE:-ok}" \
  NGINX_ETC_DIR="$nginx_root" \
  LETSENCRYPT_DIR="$tmp_dir/letsencrypt" \
  CERTIFICATE_CHECKER="$certificate_checker" \
  NGINX_INSTALLER="$nginx_installer" \
  NGINX_CONFD_INSTALLER="$confd_installer" \
  APP_DOMAIN="$app_domain" \
  API_DOMAIN="$api_domain" \
    bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/version-probe.log" 2>&1 || probe_status=$?
  if [ "$probe_status" -eq 0 ]; then
    echo "setup accepted an unavailable or malformed nginx version" >&2
    exit 1
  fi
  grep -Fq "$expected_error" "$tmp_dir/version-probe.log" || {
    cat "$tmp_dir/version-probe.log" >&2
    exit 1
  }
  test ! -e "$repo_root/deploy/nginx/$app_domain.conf"
  test ! -e "$repo_root/deploy/nginx/$api_domain.conf"
  test ! -e "$RELOAD_MARKER"
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
  for name in api.example.test app.example.test default; do
    rm -f "$nginx_root/sites-enabled/$name"
    cp "$nginx_root/sites-available/$name" "$nginx_root/sites-enabled/$name"
  done
  write_nginx_test_config
  local output
  output="$(docker run --rm \
    -v "$nginx_root:/etc/nginx:ro" \
    -v "$tmp_dir/letsencrypt:/etc/letsencrypt:ro" \
    "$nginx_image" nginx -t -c /etc/nginx/nginx.conf 2>&1)" || {
    printf '%s\n' "$output" >&2
    return 1
  }
  if grep -Fq 'deprecated' <<< "$output"; then
    printf '%s\n' "$output" >&2
    echo "nginx -t emitted a deprecation warning" >&2
    return 1
  fi
}

NGINX_TEST_PROBE_MODE=fail expect_version_probe_failure \
  'Could not determine nginx version' invalid-probe-app.example.test invalid-probe-api.example.test
NGINX_TEST_VERSION_OUTPUT='nginx version: nginx/not-a-version' \
  expect_version_probe_failure 'Could not parse nginx version' \
    invalid-format-app.example.test invalid-format-api.example.test

run_setup

for path in \
  "$nginx_root/conf.d/wrzdj-logging.conf" \
  "$nginx_root/conf.d/wrzdj-tuning.conf" \
  "$nginx_root/sites-available/api.example.test" \
  "$nginx_root/sites-available/app.example.test" \
  "$nginx_root/sites-available/default"; do
  test -f "$path"
done
for path in \
  "$repo_root/deploy/nginx/api.example.test.conf" \
  "$repo_root/deploy/nginx/app.example.test.conf" \
  "$repo_root/deploy/nginx/default.conf"; do
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
  "$repo_root/deploy/wrappers/wrzdj-certbot"
grep -Fq "certbot_args+=(\"--key-type\" \"\$key_type\")" \
  "$repo_root/deploy/wrappers/wrzdj-certbot"
grep -Fq 'wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name api.example.test-rsa --key-type rsa -d api.example.test' \
  "$tmp_dir/setup.log"

wrapper_fixtures="$tmp_dir/wrapper-letsencrypt"
wrapper_results="$tmp_dir/wrapper-results"
mkdir -p "$wrapper_fixtures/live/api.example.test" \
  "$wrapper_fixtures/live/incomplete.example.test" \
  "$wrapper_fixtures/live/unreadable.example.test" "$wrapper_fixtures/archive" \
  "$wrapper_results"
printf cert > "$wrapper_fixtures/live/api.example.test/fullchain.pem"
printf key > "$wrapper_fixtures/live/api.example.test/privkey.pem"
printf cert > "$wrapper_fixtures/live/incomplete.example.test/fullchain.pem"
printf cert > "$wrapper_fixtures/live/unreadable.example.test/fullchain.pem"
ln -s "$wrapper_fixtures/archive/missing.pem" \
  "$wrapper_fixtures/live/unreadable.example.test/privkey.pem"

fake_certbot="$tmp_dir/certbot"
cat > "$fake_certbot" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" > "${CERTBOT_LOG:?}"
SH
chmod +x "$fake_certbot"
cat > "$tmp_dir/test-wrappers-in-container.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if /usr/local/bin/wrzdj-certbot --nginx --key-type dsa -d api.example.test >/dev/null 2>&1; then
  echo "wrapper accepted an unsupported key type" >&2
  exit 1
fi
if /usr/local/bin/wrzdj-certbot --nginx --cert-name '../../etc' -d api.example.test >/dev/null 2>&1; then
  echo "wrapper accepted a path traversal certificate name" >&2
  exit 1
fi
if /usr/local/bin/wrzdj-certbot --nginx --cert-name other.example.test \
  -d api.example.test >/dev/null 2>&1; then
  echo "wrapper accepted a certificate name for another domain" >&2
  exit 1
fi
CERTBOT_LOG=/wrapper-results/certbot.log /usr/local/bin/wrzdj-certbot \
  --nginx --agree-tos --email admin@example.test --cert-name api.example.test-rsa \
  --key-type rsa -d api.example.test
grep -Fq -- '--nginx --non-interactive --agree-tos --email admin@example.test --cert-name api.example.test-rsa --key-type rsa -d api.example.test' \
  /wrapper-results/certbot.log

expect_rejected_renew_argument() {
  local description="$1"
  shift
  if CERTBOT_LOG=/wrapper-results/certbot.log \
    /usr/local/bin/wrzdj-certbot renew "$@" >/dev/null 2>&1; then
    echo "certbot wrapper accepted $description" >&2
    exit 1
  fi
  test "$(cat /wrapper-results/certbot.log)" = \
    '--nginx --non-interactive --agree-tos --email admin@example.test --cert-name api.example.test-rsa --key-type rsa -d api.example.test'
}
expect_rejected_renew_argument 'a misspelled dry-run option' --dryrun
expect_rejected_renew_argument 'an extra argument after dry-run' --dry-run extra

CERTBOT_LOG=/wrapper-results/certbot.log /usr/local/bin/wrzdj-certbot renew
test "$(cat /wrapper-results/certbot.log)" = 'renew'
CERTBOT_LOG=/wrapper-results/certbot.log /usr/local/bin/wrzdj-certbot renew --dry-run
test "$(cat /wrapper-results/certbot.log)" = 'renew --dry-run'

/usr/local/bin/wrzdj-certificates-ready api.example.test
if /usr/local/bin/wrzdj-certificates-ready incomplete.example.test; then
  echo "certificate checker accepted an incomplete lineage" >&2
  exit 1
fi
checker_status=0
/usr/local/bin/wrzdj-certificates-ready unreadable.example.test || checker_status=$?
if [ "$checker_status" -ne 2 ]; then
  echo "certificate checker accepted an unreadable lineage" >&2
  exit 1
fi
if /usr/local/bin/wrzdj-certificates-ready '../../etc' >/dev/null 2>&1; then
  echo "certificate checker accepted a path traversal domain" >&2
  exit 1
fi
SH
chmod +x "$tmp_dir/test-wrappers-in-container.sh"
docker run --rm \
  --volume "$repo_root/deploy/wrappers/wrzdj-certbot:/usr/local/bin/wrzdj-certbot:ro" \
  --volume "$repo_root/deploy/wrappers/wrzdj-certificates-ready:/usr/local/bin/wrzdj-certificates-ready:ro" \
  --volume "$fake_certbot:/usr/bin/certbot:ro" \
  --volume "$wrapper_fixtures:/etc/letsencrypt:ro" \
  --volume "$wrapper_results:/wrapper-results" \
  --volume "$tmp_dir/test-wrappers-in-container.sh:/test-wrappers.sh:ro" \
  "$shell_image" bash /test-wrappers.sh

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

# Generation-only mode must work before nginx is installed. Restrict PATH to
# the commands needed for rendering so this exercises a genuinely missing nginx.
no_nginx_bin="$tmp_dir/no-nginx-bin"
mkdir -p "$no_nginx_bin"
for command_name in bash dirname envsubst; do
  command_path="$(command -v "$command_name")"
  ln -s "$command_path" "$no_nginx_bin/$command_name"
done
cat > "$no_nginx_bin/id" <<'ID'
#!/usr/bin/env bash
if [ "${1:-}" = -u ]; then
  printf '0\n'
else
  exit 2
fi
ID
chmod +x "$no_nginx_bin/id"
PATH="$no_nginx_bin" NGINX_ETC_DIR="$tmp_dir/generate-only/nginx" \
  LETSENCRYPT_DIR="$tmp_dir/letsencrypt" CERTIFICATE_CHECKER="$certificate_checker" \
  APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  bash "$repo_root/deploy/setup-nginx.sh" > "$tmp_dir/generate-only.log" 2>&1 || {
  cat "$tmp_dir/generate-only.log" >&2
  exit 1
}
for name in api.example.test app.example.test; do
  test -s "$repo_root/deploy/nginx/$name.conf"
  grep -Fq 'listen 443 ssl http2;' "$repo_root/deploy/nginx/$name.conf"
done
test -s "$repo_root/deploy/nginx/default.conf"
grep -Fq 'listen 443 ssl http2 default_server;' "$repo_root/deploy/nginx/default.conf"
grep -Fq 'nginx is not installed; using compatibility syntax for generated configs' \
  "$tmp_dir/generate-only.log"

run_setup
assert_nginx_config
for name in api.example.test app.example.test default; do
  grep -Eq 'listen 443 ssl( default_server)?;' "$nginx_root/sites-available/$name"
  grep -Fq 'http2 on;' "$nginx_root/sites-available/$name"
done
grep -Fq 'location ~ ^/e/[^/]+/overlay' \
  "$nginx_root/sites-available/app.example.test"
grep -Fq 'frame-ancestors *' "$nginx_root/sites-available/app.example.test"
if grep -Fq 'Migration note:' "$tmp_dir/setup.log"; then
  echo "setup reported a migration after generating the TLS overlay config" >&2
  exit 1
fi
grep -Fq '/etc/letsencrypt/live/api.example.test/fullchain.pem' \
  "$nginx_root/sites-available/api.example.test"
grep -Fq 'ssl_certificate /etc/letsencrypt/live/api.example.test-rsa/fullchain.pem;' \
  "$nginx_root/sites-available/api.example.test"
grep -Fq '/etc/letsencrypt/live/app.example.test-rsa/fullchain.pem' \
  "$nginx_root/sites-available/app.example.test"
grep -Fq 'HTTP bootstrap first' "$repo_root/deploy/nginx/api.conf.template"
grep -Fq 'HTTP bootstrap first' "$repo_root/deploy/nginx/app.conf.template"

NGINX_TEST_VERSION=1.18.0 run_setup
for name in api.example.test app.example.test default; do
  grep -Fq 'listen 443 ssl http2' "$nginx_root/sites-available/$name"
  if grep -Fq 'http2 on;' "$nginx_root/sites-available/$name"; then
    echo "legacy nginx output contains the unsupported standalone http2 directive" >&2
    exit 1
  fi
done
run_setup
assert_nginx_config

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

if [ "$(source_nginx_manifest)" != "$source_nginx_before" ]; then
  echo 'setup-nginx test modified the source deploy/nginx directory' >&2
  exit 1
fi

printf 'setup-nginx provisioning contract passed\n'
