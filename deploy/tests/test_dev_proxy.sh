#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/deploy"
cp -a "$repo_root/deploy/dev-proxy" "$scratch/deploy/dev-proxy"

cat > "$scratch/bin/ip" <<'IP'
#!/usr/bin/env bash
if [ "${WRZDJ_TEST_NO_LAN_IP:-0}" = 1 ]; then
  printf 'lo: inet 127.0.0.1/8\n'
else
  printf 'eth0: inet %s/24\n' "${WRZDJ_TEST_LAN_IP:-192.168.55.7}"
fi
IP
cat > "$scratch/bin/openssl" <<'OPENSSL'
#!/usr/bin/env bash
if [ "${1:-}" = req ]; then
  printf '%s\n' "$*" >> "$WRZDJ_OPENSSL_CALLS"
fi
exec /usr/bin/openssl "$@"
OPENSSL
cat > "$scratch/bin/grep" <<'GREP'
#!/usr/bin/env bash
for argument in "$@"; do
  if [ "$argument" = /etc/hosts ]; then exit 1; fi
done
exec /usr/bin/grep "$@"
GREP
cat > "$scratch/bin/sudo" <<'SUDO'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_SUDO_CALLS"
cat >> "$WRZDJ_HOSTS_INPUT"
SUDO
cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_DOCKER_CALLS"
DOCKER
chmod +x "$scratch/bin"/*

export PATH="$scratch/bin:$PATH"
export WRZDJ_OPENSSL_CALLS="$scratch/openssl.log"
export WRZDJ_SUDO_CALLS="$scratch/sudo.log"
export WRZDJ_HOSTS_INPUT="$scratch/hosts-input"
export WRZDJ_DOCKER_CALLS="$scratch/docker.log"
setup="$scratch/deploy/dev-proxy/setup.sh"
stop="$scratch/deploy/dev-proxy/stop.sh"

bash "$setup" > "$scratch/setup.log"
grep -Fq '[net] Detected LAN IP: 192.168.55.7' "$scratch/setup.log"
grep -Fq '192.168.55.7' "$scratch/deploy/dev-proxy/nginx/api.conf"
grep -Fq 'https://192.168.55.7:8443' "$scratch/setup.log"
/usr/bin/openssl x509 -in "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -noout -checkip 192.168.55.7 >/dev/null
for host in app.local api.local; do
  /usr/bin/openssl x509 -in "$scratch/deploy/dev-proxy/certs/cert.pem" \
    -noout -checkhost "$host" >/dev/null
done
test "$(stat -c '%a' "$scratch/deploy/dev-proxy/certs/key.pem")" = 600
test "$(cat "$WRZDJ_HOSTS_INPUT")" = '127.0.0.1 app.local api.local  # wrzdj dev proxy'
grep -Fxq 'tee -a /etc/hosts' "$WRZDJ_SUDO_CALLS"
grep -Fxq 'compose -f '"$scratch/deploy/dev-proxy/docker-compose.yml"' up -d --build' "$WRZDJ_DOCKER_CALLS"

bash "$setup" > "$scratch/reuse.log"
grep -Fq 'Self-signed certs already exist with correct SANs, skipping' "$scratch/reuse.log"
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 1

# An IP SAN with a longer address shares the shorter LAN IP as a substring.
# It must not be mistaken for an exact certificate match.
/usr/bin/openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$scratch/collision-key.pem" -out "$scratch/collision-cert.pem" \
  -subj '/CN=wrzdj-dev' \
  -addext 'subjectAltName=DNS:app.local,DNS:api.local,IP:192.168.55.100' \
  >/dev/null 2>&1
cp "$scratch/collision-key.pem" "$scratch/deploy/dev-proxy/certs/key.pem"
cp "$scratch/collision-cert.pem" "$scratch/deploy/dev-proxy/certs/cert.pem"
if /usr/bin/openssl x509 -in "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -noout -checkip 192.168.55.10 >/dev/null 2>&1; then
  echo 'test fixture unexpectedly matches the longer IP SAN' >&2
  exit 1
fi
WRZDJ_TEST_LAN_IP=192.168.55.10 bash "$setup" > "$scratch/prefix-mismatch.log"
grep -Fq 'LAN IP changed — regenerating certs to include 192.168.55.10' \
  "$scratch/prefix-mismatch.log"
/usr/bin/openssl x509 -in "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -noout -checkip 192.168.55.10 >/dev/null
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 2

WRZDJ_TEST_LAN_IP=192.168.55.8 bash "$setup" > "$scratch/changed-ip.log"
grep -Fq 'LAN IP changed — regenerating certs' "$scratch/changed-ip.log"
/usr/bin/openssl x509 -in "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -noout -checkip 192.168.55.8 >/dev/null
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 3

WRZDJ_TEST_NO_LAN_IP=1 bash "$setup" > "$scratch/fallback.log"
grep -Fq 'falling back to 127.0.0.1' "$scratch/fallback.log"
grep -Fq 'Detected LAN IP: 127.0.0.1' "$scratch/fallback.log"
/usr/bin/openssl x509 -in "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -noout -checkip 127.0.0.1 >/dev/null

bash "$stop" > "$scratch/stop.log"
grep -Fq "compose -f $scratch/deploy/dev-proxy/docker-compose.yml down" "$WRZDJ_DOCKER_CALLS"
grep -Fq 'Stopped. /etc/hosts entries left in place' "$scratch/stop.log"

echo 'Dev proxy setup and stop use temporary files, request host updates through a stub, and call only stubbed Docker.'
