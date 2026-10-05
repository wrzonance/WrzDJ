#!/usr/bin/env bash
# Sets up the local dev reverse proxy (nginx in Docker).
#
# What this does:
#   1. Detects your LAN IP address
#   2. Generates nginx configs from templates (with LAN IP baked in)
#   3. Generates self-signed TLS certs for app.local / api.local / LAN IP
#   4. Adds /etc/hosts entries (requires sudo)
#   5. Starts the nginx proxy container
#
# After running this, start your services with:
#   Backend:  CORS_ORIGINS="https://app.local,https://<LAN_IP>" uvicorn ...
#   Frontend: NEXT_PUBLIC_API_URL="https://<LAN_IP>:8443" npm run dev
#   Browse:   https://app.local  or  https://<LAN_IP> (from other devices)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="$SCRIPT_DIR/certs"
NGINX_DIR="$SCRIPT_DIR/nginx"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

# ── 1. Detect LAN IP ──────────────────────────────────────────────────────────

LAN_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)192\.168\.\d+\.\d+' | head -1)

if [ -z "$LAN_IP" ]; then
    echo "[warn] Could not detect a 192.168.x.x LAN IP, falling back to 127.0.0.1"
    echo "[warn] LAN access from other devices will not work"
    LAN_IP="127.0.0.1"
fi

echo "[net] Detected LAN IP: $LAN_IP"
export LAN_IP

# ── 2. Generate nginx configs from templates ───────────────────────────────────

echo "[nginx] Generating configs from templates..."
for tmpl in "$NGINX_DIR"/*.conf.template; do
    conf="${tmpl%.template}"
    # Only substitute $LAN_IP — preserve nginx variables like $server_name, $host, etc.
    envsubst "\${LAN_IP}" < "$tmpl" > "$conf"
    echo "  $(basename "$conf")"
done

# ── 3. Generate self-signed certs ─────────────────────────────────────────────

# Regenerate if LAN IP changed (cert must include current IP in SANs)
REGEN_CERTS=false
if [ ! -f "$CERTS_DIR/cert.pem" ] || [ ! -f "$CERTS_DIR/key.pem" ]; then
    REGEN_CERTS=true
elif ! openssl x509 -in "$CERTS_DIR/cert.pem" -noout -ext subjectAltName 2>/dev/null | grep -q "$LAN_IP"; then
    echo "[certs] LAN IP changed — regenerating certs to include $LAN_IP"
    REGEN_CERTS=true
fi

if [ "$REGEN_CERTS" = true ]; then
    echo "[certs] Generating self-signed TLS certificate for app.local + api.local + $LAN_IP..."
    mkdir -p "$CERTS_DIR"
    openssl req -x509 -nodes -days 365 \
        -newkey rsa:2048 \
        -keyout "$CERTS_DIR/key.pem" \
        -out "$CERTS_DIR/cert.pem" \
        -subj "/CN=wrzdj-dev" \
        -addext "subjectAltName=DNS:app.local,DNS:api.local,IP:$LAN_IP" \
        2>/dev/null
    echo "[certs] Created $CERTS_DIR/cert.pem and $CERTS_DIR/key.pem"
else
    echo "[certs] Self-signed certs already exist with correct SANs, skipping"
fi

# ── 4. /etc/hosts entries ─────────────────────────────────────────────────────

HOSTS_NEEDED=false
for domain in app.local api.local; do
    if ! grep -q "^127\.0\.0\.1.*$domain" /etc/hosts 2>/dev/null; then
        HOSTS_NEEDED=true
        break
    fi
done

if [ "$HOSTS_NEEDED" = true ]; then
    echo "[hosts] Adding app.local and api.local to /etc/hosts (requires sudo)..."
    echo '127.0.0.1 app.local api.local  # wrzdj dev proxy' | sudo tee -a /etc/hosts >/dev/null
    echo "[hosts] Done"
else
    echo "[hosts] /etc/hosts entries already present"
fi

# ── 5. Start the proxy ───────────────────────────────────────────────────────

echo "[proxy] Starting nginx reverse proxy..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "=========================================="
echo "  Dev proxy is running"
echo "=========================================="
echo ""
echo "  Local machine:"
echo "    Frontend:  https://app.local"
echo "    Backend:   https://api.local:8443"
echo ""
echo "  LAN devices (phones, other computers):"
echo "    Frontend:  https://$LAN_IP"
echo "    Backend:   https://$LAN_IP:8443"
echo ""
echo "  Start your services with:"
echo "    cd server && CORS_ORIGINS=\"https://app.local,https://$LAN_IP\" \\"
echo "      uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo "    cd dashboard && NEXT_PUBLIC_API_URL=\"https://$LAN_IP:8443\" npm run dev"
echo ""
echo "  Your browser will warn about the self-signed cert —"
echo "  click through it once for each domain/IP."
echo ""
echo "  Tip: install mkcert for locally-trusted certs:"
echo "    mkcert -install && mkcert -cert-file $CERTS_DIR/cert.pem \\"
echo "      -key-file $CERTS_DIR/key.pem app.local api.local $LAN_IP"
echo ""
echo "  Stop with: ./deploy/dev-proxy/stop.sh"
echo "=========================================="
