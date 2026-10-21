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
if [ "${WRZDJ_TEST_LEGACY_CHECKIP:-0}" = 1 ] && [[ " $* " == *" -checkip "* ]]; then
  /usr/bin/openssl "$@"
  openssl_status=$?
  # Legacy OpenSSL printed a mismatch but returned success for -checkip.
  [ "$openssl_status" -ne 0 ] && exit 0
  exit "$openssl_status"
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
/usr/bin/openssl verify -trusted "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -partial_chain -verify_ip 192.168.55.7 "$scratch/deploy/dev-proxy/certs/cert.pem" >/dev/null
for host in app.local api.local; do
  /usr/bin/openssl verify -trusted "$scratch/deploy/dev-proxy/certs/cert.pem" \
    -partial_chain -verify_hostname "$host" \
    "$scratch/deploy/dev-proxy/certs/cert.pem" >/dev/null
done
test "$(stat -c '%a' "$scratch/deploy/dev-proxy/certs/key.pem")" = 600
test "$(cat "$WRZDJ_HOSTS_INPUT")" = '127.0.0.1 app.local api.local  # wrzdj dev proxy'
grep -Fxq 'tee -a /etc/hosts' "$WRZDJ_SUDO_CALLS"
grep -Fxq 'compose -f '"$scratch/deploy/dev-proxy/docker-compose.yml"' up -d --build' "$WRZDJ_DOCKER_CALLS"

bash "$setup" > "$scratch/reuse.log"
grep -Fq 'Existing certificate matches the LAN IP, skipping' "$scratch/reuse.log"
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 1

# mkcert supplies a CA-signed leaf (CA:FALSE), which must remain reusable.
/usr/bin/openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$scratch/mkcert-ca-key.pem" -out "$scratch/mkcert-ca.pem" \
  -subj '/CN=mkcert test CA' \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' >/dev/null 2>&1
/usr/bin/openssl req -new -nodes -newkey rsa:2048 \
  -keyout "$scratch/mkcert-key.pem" -out "$scratch/mkcert.csr" \
  -subj '/CN=wrzdj-dev' >/dev/null 2>&1
printf '%s\n' \
  'subjectAltName=DNS:app.local,DNS:api.local,IP:192.168.55.7' \
  'basicConstraints=critical,CA:FALSE' \
  'extendedKeyUsage=serverAuth' > "$scratch/mkcert.ext"
/usr/bin/openssl x509 -req -in "$scratch/mkcert.csr" \
  -CA "$scratch/mkcert-ca.pem" -CAkey "$scratch/mkcert-ca-key.pem" \
  -CAcreateserial -days 365 -out "$scratch/mkcert-cert.pem" \
  -extfile "$scratch/mkcert.ext" >/dev/null 2>&1
cp "$scratch/mkcert-key.pem" "$scratch/deploy/dev-proxy/certs/key.pem"
cp "$scratch/mkcert-cert.pem" "$scratch/deploy/dev-proxy/certs/cert.pem"
bash "$setup" > "$scratch/mkcert-reuse.log"
grep -Fq 'Existing certificate matches the LAN IP, skipping' \
  "$scratch/mkcert-reuse.log"
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 1

# Regression for baseline 5dac045f: a longer IP SAN shares the shorter address
# as a substring and must not be mistaken for an exact certificate match.
/usr/bin/openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$scratch/collision-key.pem" -out "$scratch/collision-cert.pem" \
  -subj '/CN=wrzdj-dev' \
  -addext 'subjectAltName=DNS:app.local,DNS:api.local,IP:192.168.55.100' \
  >/dev/null 2>&1
cp "$scratch/collision-key.pem" "$scratch/deploy/dev-proxy/certs/key.pem"
cp "$scratch/collision-cert.pem" "$scratch/deploy/dev-proxy/certs/cert.pem"
if /usr/bin/openssl verify -trusted "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -partial_chain -verify_ip 192.168.55.10 \
  "$scratch/deploy/dev-proxy/certs/cert.pem" >/dev/null 2>&1; then
  echo 'longer-IP fixture unexpectedly verifies for the shorter LAN IP' >&2
  exit 1
fi
if WRZDJ_TEST_LEGACY_CHECKIP=1 openssl x509 \
  -in "$scratch/deploy/dev-proxy/certs/cert.pem" -noout -checkip 192.168.55.10 \
  > "$scratch/legacy-checkip.log" 2>&1; then
  grep -Fq 'does NOT match certificate' "$scratch/legacy-checkip.log"
else
  echo 'legacy x509 -checkip simulation did not return success' >&2
  exit 1
fi
WRZDJ_TEST_LEGACY_CHECKIP=1 WRZDJ_TEST_LAN_IP=192.168.55.10 \
  bash "$setup" > "$scratch/prefix-mismatch.log"
grep -Fq 'LAN IP changed — regenerating certs to include 192.168.55.10' \
  "$scratch/prefix-mismatch.log"
/usr/bin/openssl verify -trusted "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -partial_chain -verify_ip 192.168.55.10 "$scratch/deploy/dev-proxy/certs/cert.pem" >/dev/null
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 2

WRZDJ_TEST_LAN_IP=192.168.55.8 bash "$setup" > "$scratch/changed-ip.log"
grep -Fq 'LAN IP changed — regenerating certs' "$scratch/changed-ip.log"
/usr/bin/openssl verify -trusted "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -partial_chain -verify_ip 192.168.55.8 "$scratch/deploy/dev-proxy/certs/cert.pem" >/dev/null
test "$(wc -l < "$WRZDJ_OPENSSL_CALLS")" -eq 3

WRZDJ_TEST_NO_LAN_IP=1 bash "$setup" > "$scratch/fallback.log"
grep -Fq 'falling back to 127.0.0.1' "$scratch/fallback.log"
grep -Fq 'Detected LAN IP: 127.0.0.1' "$scratch/fallback.log"
/usr/bin/openssl verify -trusted "$scratch/deploy/dev-proxy/certs/cert.pem" \
  -partial_chain -verify_ip 127.0.0.1 "$scratch/deploy/dev-proxy/certs/cert.pem" >/dev/null

bash "$stop" > "$scratch/stop.log"
grep -Fq "compose -f $scratch/deploy/dev-proxy/docker-compose.yml down" "$WRZDJ_DOCKER_CALLS"
grep -Fq 'Stopped. /etc/hosts entries left in place' "$scratch/stop.log"

echo 'Dev proxy setup and stop use temporary files, request host updates through a stub, and call only stubbed Docker.'
