#!/usr/bin/env bash
set -euo pipefail

# WrzDJ Dedicated Deploy User Setup
# Creates a 'wrzdj' user with minimal privileges for running the application.
#
# Usage (as root, first-time VPS setup):
#   ./deploy/setup-user.sh
#
# Usage (as wrzdj, validation mode):
#   ./deploy/setup-user.sh
#
# Idempotent — safe to run multiple times.

USERNAME="wrzdj"
DEPLOY_DIR="/opt/wrzdj"
SUDOERS_FILE="/etc/sudoers.d/$USERNAME"

# ---------- Validation mode (non-root) ----------

if [ "$(id -u)" -ne 0 ]; then
  echo "==> Running as $(whoami) — validation mode"
  ERRORS=0

  # Check user exists
  if id "$USERNAME" &>/dev/null; then
    echo "    [OK] User '$USERNAME' exists"
  else
    echo "    [FAIL] User '$USERNAME' does not exist"
    ERRORS=$((ERRORS + 1))
  fi

  # Check docker group
  if groups "$USERNAME" 2>/dev/null | grep -qw docker; then
    echo "    [OK] User '$USERNAME' is in docker group"
  else
    echo "    [FAIL] User '$USERNAME' is NOT in docker group"
    ERRORS=$((ERRORS + 1))
  fi

  # Check docker works
  if docker ps &>/dev/null; then
    echo "    [OK] docker ps works without sudo"
  else
    echo "    [FAIL] docker ps failed (re-login may be needed for group change)"
    ERRORS=$((ERRORS + 1))
  fi

  # Check sudoers
  if [ -f "$SUDOERS_FILE" ]; then
    echo "    [OK] Sudoers file exists at $SUDOERS_FILE"
  else
    echo "    [FAIL] Sudoers file missing at $SUDOERS_FILE"
    ERRORS=$((ERRORS + 1))
  fi

  # Check deploy directory
  if [ -d "$DEPLOY_DIR" ]; then
    OWNER=$(stat -c '%U' "$DEPLOY_DIR")
    if [ "$OWNER" = "$USERNAME" ]; then
      echo "    [OK] $DEPLOY_DIR owned by $USERNAME"
    else
      echo "    [FAIL] $DEPLOY_DIR owned by $OWNER (expected $USERNAME)"
      ERRORS=$((ERRORS + 1))
    fi
  else
    echo "    [FAIL] $DEPLOY_DIR does not exist"
    ERRORS=$((ERRORS + 1))
  fi

  # Check SSH keys
  if [ -f "/home/$USERNAME/.ssh/authorized_keys" ]; then
    echo "    [OK] SSH authorized_keys present"
  else
    echo "    [WARN] No SSH authorized_keys found at /home/$USERNAME/.ssh/"
  fi

  if [ $ERRORS -eq 0 ]; then
    echo ""
    echo "==> All checks passed"
    exit 0
  else
    echo ""
    echo "==> $ERRORS check(s) failed — run this script as root to fix"
    exit 1
  fi
fi

# ---------- Setup mode (root) ----------

echo "==> WrzDJ deploy user setup (running as root)"

# 1. Create user
if id "$USERNAME" &>/dev/null; then
  echo "    User '$USERNAME' already exists"
else
  useradd -m -s /bin/bash "$USERNAME"
  echo "    Created user '$USERNAME'"
fi

# 2. Add to docker group
if getent group docker &>/dev/null; then
  if groups "$USERNAME" | grep -qw docker; then
    echo "    User already in docker group"
  else
    usermod -aG docker "$USERNAME"
    echo "    Added '$USERNAME' to docker group"
  fi
else
  echo "    WARNING: docker group does not exist — install Docker first"
fi

# 3. Install wrapper scripts (prevents wildcard privilege escalation)
echo "    Installing wrapper scripts to /usr/local/bin/"

cat > /usr/local/bin/wrzdj-nginx-install << 'WRAPPER'
#!/bin/bash
set -euo pipefail
# Install an nginx config file safely (no path traversal, no arbitrary source)
ALLOWED_DIR="/opt/wrzdj/deploy/nginx"

src="$(realpath "$1")"
name="$(basename "$1" .conf)"

# Validate source is under the allowed directory
if [[ "$src" != "$ALLOWED_DIR"/* ]]; then
  echo "ERROR: Source file must be under $ALLOWED_DIR (got: $src)" >&2
  exit 1
fi

# Validate destination name (no slashes, dots-only, etc.)
if [[ ! "$name" =~ ^[a-zA-Z0-9.-]+$ ]]; then
  echo "ERROR: Invalid config name: $name" >&2
  exit 1
fi

cp -- "$src" "/etc/nginx/sites-available/$name"
ln -sf "/etc/nginx/sites-available/$name" "/etc/nginx/sites-enabled/$name"
echo "Installed: /etc/nginx/sites-available/$name"
WRAPPER
chmod 750 /usr/local/bin/wrzdj-nginx-install
chown root:wrzdj /usr/local/bin/wrzdj-nginx-install

cat > /usr/local/bin/wrzdj-certbot << 'WRAPPER'
#!/bin/bash
set -euo pipefail
# Run certbot with restricted operations (no hooks allowed)
case "${1:-}" in
  --nginx)
    shift
    domains=()
    domain_values=()
    certbot_args=()
    cert_name=""
    while [ $# -gt 0 ]; do
      if [ "$1" = "-d" ] && [ $# -gt 1 ]; then
        domain="$2"
        if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
          echo "ERROR: Invalid domain: $domain" >&2
          exit 1
        fi
        domains+=("-d" "$domain")
        domain_values+=("$domain")
        shift 2
      elif [ "$1" = "--cert-name" ] && [ $# -gt 1 ]; then
        cert_name="$2"
        if [[ ! "$cert_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]; then
          echo "ERROR: Invalid certificate name: $cert_name" >&2
          exit 1
        fi
        certbot_args+=("--cert-name" "$cert_name")
        shift 2
      elif [ "$1" = "--agree-tos" ]; then
        certbot_args+=("--agree-tos")
        shift
      elif [ "$1" = "--email" ] && [ $# -gt 1 ]; then
        email="$2"
        if [[ ! "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]]; then
          echo "ERROR: Invalid email address: $email" >&2
          exit 1
        fi
        certbot_args+=("--email" "$email")
        shift 2
      elif [ "$1" = "--register-unsafely-without-email" ]; then
        certbot_args+=("--register-unsafely-without-email")
        shift
      elif [ "$1" = "--key-type" ] && [ $# -gt 1 ]; then
        key_type="$2"
        if [ "$key_type" != "ecdsa" ] && [ "$key_type" != "rsa" ]; then
          echo "ERROR: Invalid key type: $key_type" >&2
          exit 1
        fi
        certbot_args+=("--key-type" "$key_type")
        shift 2
      else
        echo "ERROR: Unexpected argument: $1" >&2
        exit 1
      fi
    done
    if [ ${#domains[@]} -eq 0 ]; then
      echo "Usage: wrzdj-certbot --nginx -d domain1 [-d domain2 ...]" >&2
      exit 1
    fi
    if [ -n "$cert_name" ]; then
      for domain in "${domain_values[@]}"; do
        if [ "$cert_name" != "$domain" ] && [ "$cert_name" != "$domain-rsa" ]; then
          echo "ERROR: Certificate name must match its domain or domain-rsa: $cert_name" >&2
          exit 1
        fi
      done
    fi
    exec /usr/bin/certbot --nginx --non-interactive "${certbot_args[@]}" "${domains[@]}"
    ;;
  renew)
    if [ "${2:-}" = "--dry-run" ]; then
      exec /usr/bin/certbot renew --dry-run
    fi
    exec /usr/bin/certbot renew
    ;;
  *)
    echo "Usage: wrzdj-certbot {--nginx -d domain [...] | renew [--dry-run]}" >&2
    exit 1
    ;;
esac
WRAPPER
chmod 750 /usr/local/bin/wrzdj-certbot
chown root:wrzdj /usr/local/bin/wrzdj-certbot

cat > /usr/local/bin/wrzdj-certificates-ready << 'WRAPPER'
#!/bin/bash
set -euo pipefail
domain="${1:-}"
if [ $# -ne 1 ] || [[ ! "$domain" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]; then
  echo "Usage: wrzdj-certificates-ready domain" >&2
  exit 1
fi
live_dir="/etc/letsencrypt/live/$domain"
if [ ! -d "$live_dir" ]; then
  exit 1
fi
if [ ! -r "$live_dir" ]; then
  exit 2
fi
for filename in fullchain.pem privkey.pem; do
  path="$live_dir/$filename"
  if [ -L "$path" ] && [ ! -e "$path" ]; then
    exit 2
  fi
  if [ ! -e "$path" ]; then
    exit 1
  fi
  if [ ! -r "$path" ] || [ ! -s "$path" ]; then
    exit 2
  fi
done
WRAPPER
chmod 750 /usr/local/bin/wrzdj-certificates-ready
chown root:wrzdj /usr/local/bin/wrzdj-certificates-ready

cat > /usr/local/bin/wrzdj-nginx-confd-install << 'WRAPPER'
#!/bin/bash
set -euo pipefail
# Install an nginx config file to conf.d/ safely (http-level configs like log formats)
ALLOWED_DIR="/opt/wrzdj/deploy/nginx"

src="$(realpath "$1")"
name="$(basename "$1")"

# Validate source is under the allowed directory
if [[ "$src" != "$ALLOWED_DIR"/* ]]; then
  echo "ERROR: Source file must be under $ALLOWED_DIR (got: $src)" >&2
  exit 1
fi

# Validate filename (no slashes, dots-only, etc.)
if [[ ! "$name" =~ ^[a-zA-Z0-9._-]+\.conf$ ]]; then
  echo "ERROR: Invalid config name: $name (must end in .conf)" >&2
  exit 1
fi

cp -- "$src" "/etc/nginx/conf.d/wrzdj-$name"
echo "Installed: /etc/nginx/conf.d/wrzdj-$name"
WRAPPER
chmod 750 /usr/local/bin/wrzdj-nginx-confd-install
chown root:wrzdj /usr/local/bin/wrzdj-nginx-confd-install

echo "    Installed nginx, certificate, and certbot wrapper scripts"

# 4. Install limited sudoers
echo "    Installing sudoers to $SUDOERS_FILE"
cat > "$SUDOERS_FILE" << 'SUDOERS'
# WrzDJ deploy user — limited sudo privileges
# Managed by deploy/setup-user.sh — do not edit manually

# nginx config management (via wrappers — no wildcards)
wrzdj ALL=(root) NOPASSWD: /usr/local/bin/wrzdj-nginx-install
wrzdj ALL=(root) NOPASSWD: /usr/local/bin/wrzdj-nginx-confd-install
wrzdj ALL=(root) NOPASSWD: /usr/sbin/nginx -t

# nginx service management
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl status nginx

# wrzdj systemd service management
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl enable wrzdj
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl start wrzdj
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl stop wrzdj
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl restart wrzdj
wrzdj ALL=(root) NOPASSWD: /usr/bin/systemctl status wrzdj

# SSL certificate management (via wrapper — no hooks allowed)
wrzdj ALL=(root) NOPASSWD: /usr/local/bin/wrzdj-certbot
wrzdj ALL=(root) NOPASSWD: /usr/local/bin/wrzdj-certificates-ready
SUDOERS
chmod 0440 "$SUDOERS_FILE"

# Validate sudoers syntax
if visudo -cf "$SUDOERS_FILE" &>/dev/null; then
  echo "    Sudoers syntax OK"
else
  echo "    ERROR: Invalid sudoers syntax — removing file"
  rm -f "$SUDOERS_FILE"
  exit 1
fi

# 5. Copy SSH keys from root
if [ -f /root/.ssh/authorized_keys ]; then
  SSH_DIR="/home/$USERNAME/.ssh"
  mkdir -p "$SSH_DIR"

  if [ -f "$SSH_DIR/authorized_keys" ]; then
    echo "    SSH authorized_keys already exists — not overwriting"
  else
    cp /root/.ssh/authorized_keys "$SSH_DIR/authorized_keys"
    echo "    Copied SSH keys from root"
  fi

  chown -R "$USERNAME:$USERNAME" "$SSH_DIR"
  chmod 700 "$SSH_DIR"
  chmod 600 "$SSH_DIR/authorized_keys"
else
  echo "    No /root/.ssh/authorized_keys found — skipping SSH key copy"
  echo "    You'll need to set up SSH keys for '$USERNAME' manually"
fi

# 6. Create deploy directory
if [ -d "$DEPLOY_DIR" ]; then
  echo "    $DEPLOY_DIR already exists"
else
  mkdir -p "$DEPLOY_DIR"
  echo "    Created $DEPLOY_DIR"
fi
chown -R "$USERNAME:$USERNAME" "$DEPLOY_DIR"
echo "    Set ownership of $DEPLOY_DIR to $USERNAME:$USERNAME"

echo ""
echo "==> Setup complete"
echo ""
echo "Next steps:"
echo "  1. Switch to wrzdj user:  su - $USERNAME"
echo "  2. Clone the repo:        git clone <repo-url> $DEPLOY_DIR"
echo "  3. Or rsync existing:     rsync -av /opt/WrzDJ/ $DEPLOY_DIR/"
echo "  4. Continue with DEPLOYMENT.md steps"
echo ""
echo "Optional — disable root SSH login:"
echo "  sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config"
echo "  systemctl restart sshd"
