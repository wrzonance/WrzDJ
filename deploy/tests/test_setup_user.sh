#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
shell_image="ubuntu:24.04@sha256:c4a8d5503dfb2a3eb8ab5f807da5bc69a85730fb49b5cfca2330194ebcc41c7b"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/root/.ssh" "$scratch/bin" "$scratch/logs"
printf 'ssh-ed25519 AAAATEST deploy-test\n' > "$scratch/root/.ssh/authorized_keys"

cat > "$scratch/bin/visudo" <<'VISUDO'
#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = -cf ] && [ -f "${2:-}" ] && [ "${WRZDJ_VISUDO_FAIL:-0}" != 1 ]
VISUDO
chmod +x "$scratch/bin/visudo"

cat > "$scratch/run-in-container.sh" <<'CONTAINER'
#!/usr/bin/env bash
set -euo pipefail

mkdir -p /etc/sudoers.d
groupadd docker
PATH="/test-bin:$PATH" WRZDJ_PROVISION_LOG=/test-logs/provision.log \
  bash /workspace/deploy/setup-user.sh > /test-logs/setup.log

for wrapper in wrzdj-nginx-install wrzdj-certbot wrzdj-certificates-ready wrzdj-nginx-confd-install; do
  test -x "/usr/local/bin/$wrapper"
  cmp "/workspace/deploy/wrappers/$wrapper" "/usr/local/bin/$wrapper"
done

# Exercise the installed production nginx wrappers inside this disposable
# container. Their absolute privileged paths stay inside the container.
mkdir -p /opt/wrzdj/deploy/nginx /etc/nginx/sites-available \
  /etc/nginx/sites-enabled /etc/nginx/conf.d
printf 'server { # accepted site config }\n' > /opt/wrzdj/deploy/nginx/site.conf
printf 'log_format test;\n' > /opt/wrzdj/deploy/nginx/logging.conf
printf 'outside\n' > /tmp/outside.conf
ln -s /tmp/outside.conf /opt/wrzdj/deploy/nginx/escaping.conf
printf 'invalid\n' > '/opt/wrzdj/deploy/nginx/bad name.conf'

/usr/local/bin/wrzdj-nginx-install /opt/wrzdj/deploy/nginx/site.conf
cmp /opt/wrzdj/deploy/nginx/site.conf /etc/nginx/sites-available/site
test "$(readlink /etc/nginx/sites-enabled/site)" = /etc/nginx/sites-available/site
/usr/local/bin/wrzdj-nginx-confd-install /opt/wrzdj/deploy/nginx/logging.conf
cmp /opt/wrzdj/deploy/nginx/logging.conf /etc/nginx/conf.d/wrzdj-logging.conf

expect_wrapper_rejection() {
  local wrapper="$1" source="$2" destination="$3"
  if "/usr/local/bin/$wrapper" "$source" >/tmp/wrapper-output 2>&1; then
    echo "$wrapper accepted rejected source: $source" >&2
    exit 1
  fi
  test ! -e "$destination"
}
expect_wrapper_rejection wrzdj-nginx-install /tmp/outside.conf /etc/nginx/sites-available/outside
expect_wrapper_rejection wrzdj-nginx-install /opt/wrzdj/deploy/nginx/escaping.conf \
  /etc/nginx/sites-available/escaping
expect_wrapper_rejection wrzdj-nginx-install '/opt/wrzdj/deploy/nginx/bad name.conf' \
  '/etc/nginx/sites-available/bad name'
expect_wrapper_rejection wrzdj-nginx-confd-install /tmp/outside.conf \
  /etc/nginx/conf.d/wrzdj-outside.conf
expect_wrapper_rejection wrzdj-nginx-confd-install /opt/wrzdj/deploy/nginx/escaping.conf \
  /etc/nginx/conf.d/wrzdj-escaping.conf
expect_wrapper_rejection wrzdj-nginx-confd-install '/opt/wrzdj/deploy/nginx/bad name.conf' \
  '/etc/nginx/conf.d/wrzdj-bad name.conf'

test "$(stat -c '%a' /usr/local/bin/wrzdj-nginx-install)" = 750
test "$(stat -c '%a' /etc/sudoers.d/wrzdj)" = 440
grep -Fq 'wrzdj ALL=(root) NOPASSWD: /usr/local/bin/wrzdj-certbot' /etc/sudoers.d/wrzdj
test "$(stat -c '%a' /home/wrzdj/.ssh)" = 700
test "$(stat -c '%a' /home/wrzdj/.ssh/authorized_keys)" = 600
cmp /root/.ssh/authorized_keys /home/wrzdj/.ssh/authorized_keys
test "$(stat -c '%U' /opt/wrzdj)" = wrzdj
grep -Fq "Created user 'wrzdj'" /test-logs/setup.log
grep -Fq "Added 'wrzdj' to docker group" /test-logs/setup.log

rm /etc/sudoers.d/wrzdj
if PATH="/test-bin:$PATH" WRZDJ_VISUDO_FAIL=1 \
  WRZDJ_PROVISION_LOG=/test-logs/provision.log \
  bash /workspace/deploy/setup-user.sh > /test-logs/invalid-sudoers.log 2>&1; then
  echo 'setup-user accepted invalid sudoers syntax' >&2
  exit 1
fi
test ! -e /etc/sudoers.d/wrzdj
grep -Fq 'Invalid sudoers syntax' /test-logs/invalid-sudoers.log
CONTAINER
chmod +x "$scratch/run-in-container.sh"

docker run --rm \
  --volume "$repo_root:/workspace:ro" \
  --volume "$scratch/root/.ssh:/root/.ssh:ro" \
  --volume "$scratch/bin:/test-bin:ro" \
  --volume "$scratch/logs:/test-logs" \
  --volume "$scratch/run-in-container.sh:/test-run.sh:ro" \
  "$shell_image" bash /test-run.sh

echo 'User provisioning installs standalone restricted wrappers, permissions, SSH keys, and fails closed on invalid sudoers.'
