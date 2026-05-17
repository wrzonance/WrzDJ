# WrzDJ VPS Deployment Guide

## Quick Start (Pre-built Images)

Pull and run without building from source — no compiler, no git, no Node.js needed on the server:

```bash
# 1. Get the deploy files (from a release tarball or by cloning)
cp deploy/.env.example deploy/.env

# 2. Fill in required vars: POSTGRES_PASSWORD, JWT_SECRET, TOKEN_ENCRYPTION_KEY,
#    HUMAN_COOKIE_SECRET, CORS_ORIGINS, PUBLIC_URL, NEXT_PUBLIC_API_URL

# 3. Deploy
./deploy/deploy-ghcr.sh              # pulls latest
./deploy/deploy-ghcr.sh v2026.05.16 # or pin a specific release
```

Images are published automatically on every push to `main` and on every `v*` tag:
- [ghcr.io/wrzonance/wrzdj-api](https://github.com/wrzonance/WrzDJ/pkgs/container/wrzdj-api)
- [ghcr.io/wrzonance/wrzdj-web](https://github.com/wrzonance/WrzDJ/pkgs/container/wrzdj-web)

---

## Build-from-Source Deployment

This guide covers deploying WrzDJ on a VPS using Docker Compose with the subdomain model:
- **Frontend**: `https://app.yourdomain.com`
- **Backend**: `https://api.yourdomain.com`

## Prerequisites

- Ubuntu 22.04+ VPS with:
  - **Minimum 1GB RAM** (2GB+ recommended)
  - Docker and Docker Compose
  - nginx (will be installed in step 3)
  - Certbot (will be installed in step 3)
- DNS A records pointing to your server:
  - `app.yourdomain.com` → `<your-server-ip>`
  - `api.yourdomain.com` → `<your-server-ip>`

### Memory Requirements

If your VPS has only 1GB RAM, add swap space to prevent OOM during builds:

```bash
# Create 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verify
free -h
```

## Initial Server Setup

Run these steps once as **root** to create the dedicated `wrzdj` deploy user.

### Install prerequisites (as root)

```bash
# SSH in as root
ssh root@your-server-ip

# Install Docker (if not already installed)
# See https://docs.docker.com/engine/install/ubuntu/

# Install nginx and certbot
apt update
apt install -y nginx certbot python3-certbot-nginx
```

### Create the deploy user

```bash
# Run the user setup script (from repo, or copy it to the server first)
./deploy/setup-user.sh
```

This script:
- Creates a `wrzdj` user with home directory
- Adds `wrzdj` to the `docker` group
- Installs wrapper scripts for safe nginx/certbot operations
- Installs limited sudoers (no wildcards — wrapper scripts only)
- Copies SSH keys from root
- Creates `/opt/wrzdj/` with correct ownership

### Switch to the deploy user

All subsequent steps should be run as `wrzdj`:

```bash
su - wrzdj

# Or SSH directly (after setup-user.sh copies keys)
ssh wrzdj@your-server-ip
```

### Optional: disable root SSH login

Once you've verified SSH access as `wrzdj`:

```bash
# As root, before logging out
sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd
```

## Deployment Steps

### 1. Clone the repository

```bash
cd /opt/wrzdj
git clone https://github.com/yourusername/WrzDJ.git .
```

### 2. Configure environment

```bash
cp deploy/.env.example deploy/.env
nano deploy/.env
```

Generate a secure JWT secret:
```bash
openssl rand -hex 32
```

Fill in all required values in `deploy/.env`:
- `POSTGRES_PASSWORD` - secure database password
- `JWT_SECRET` - generated secret above
- `TOKEN_ENCRYPTION_KEY` - `openssl rand -hex 32` (Fernet key for OAuth tokens at rest)
- `HUMAN_COOKIE_SECRET` - `openssl rand -base64 32` (signs `wrzdj_human` verification cookie)
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` - Spotify Developer Dashboard
- `TIDAL_CLIENT_ID` / `TIDAL_CLIENT_SECRET` - Tidal Developer Portal (playlist sync)
- `BEATPORT_CLIENT_ID` / `BEATPORT_CLIENT_SECRET` - Beatport API (electronic music search/sync)
- `BRIDGE_API_KEY` - shared secret for the bridge → API auth
- `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` - Cloudflare Turnstile (human verification + DJ self-reg CAPTCHA)
- `RESEND_API_KEY` - Resend transactional email (guest email verification + cross-device merge)
- `EMAIL_FROM_ADDRESS` - verified send-from address (e.g. `noreply@send.yourdomain.com`)
- `ANTHROPIC_API_KEY` - optional, enables AI Assist recommendations
- `SOUNDCHARTS_APP_ID` / `SOUNDCHARTS_API_KEY` - optional, third candidate source for recommendations

### 3. Configure nginx

nginx and certbot should already be installed from the root setup step above.

```bash
# Generate and install nginx configs from templates
# Replace yourdomain.com with your actual domain
APP_DOMAIN=app.yourdomain.com API_DOMAIN=api.yourdomain.com ./deploy/setup-nginx.sh

# The setup script will:
# - Generate configs from deploy/nginx/*.conf.template
# - Install them to /etc/nginx/sites-available/
# - Symlink to sites-enabled/
# - Test and reload nginx
#
# Optional: customize ports (default 8000/3000)
# APP_DOMAIN=app.yourdomain.com API_DOMAIN=api.yourdomain.com \
#   PORT_API=9000 PORT_FRONTEND=4000 ./deploy/setup-nginx.sh

# Remove default site (optional)
sudo rm -f /etc/nginx/sites-enabled/default

# Hide nginx version (security hardening)
sudo sed -i 's/# server_tokens off;/server_tokens off;/' /etc/nginx/nginx.conf

# Start nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

### 4. Set up SSL certificates with Let's Encrypt

**Important:** DNS must be pointing to your server before running certbot.

```bash
# Get certificates (uses wrzdj-certbot wrapper for safe execution)
sudo wrzdj-certbot --nginx -d api.yourdomain.com
sudo wrzdj-certbot --nginx -d app.yourdomain.com

# Verify auto-renewal is enabled
sudo systemctl status certbot.timer

# Test renewal (dry run)
sudo wrzdj-certbot renew --dry-run
```

Certificates auto-renew via systemd timer. Manual renewal if needed:
```bash
sudo wrzdj-certbot renew
sudo systemctl reload nginx
```

### 5. Build and start services

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

### 6. Create admin user

```bash
docker compose -f deploy/docker-compose.yml exec api \
  python -m app.scripts.create_user --username admin --password your-secure-password
```

### 7. Verify deployment

- Frontend: https://app.yourdomain.com
- API health: https://api.yourdomain.com/health
- API docs: https://api.yourdomain.com/docs
- Login with admin credentials

### 8. (Optional) Enable auto-start on boot

Install the systemd service so the Docker Compose stack starts automatically after reboots:

```bash
# Copy the service file
sudo cp deploy/wrzdj.service /etc/systemd/system/wrzdj.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable wrzdj
sudo systemctl start wrzdj

# Verify
sudo systemctl status wrzdj
```

The service runs `docker compose up -d` as the `wrzdj` user. It depends on `docker.service` and waits for the network to be online.

To manage the service:
```bash
sudo systemctl stop wrzdj      # Stop all containers
sudo systemctl restart wrzdj   # Restart all containers
sudo systemctl status wrzdj    # Check status
```

## Maintenance

### View logs

```bash
# All services
docker compose -f deploy/docker-compose.yml logs -f

# Specific service
docker compose -f deploy/docker-compose.yml logs -f api
docker compose -f deploy/docker-compose.yml logs -f web
docker compose -f deploy/docker-compose.yml logs -f db
```

### Restart services

```bash
docker compose -f deploy/docker-compose.yml restart
```

### Update deployment

```bash
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

### Database backup

```bash
# Create backup
docker compose -f deploy/docker-compose.yml exec db \
  pg_dump -U wrzdj wrzdj > backup-$(date +%Y%m%d).sql

# Restore backup
cat backup.sql | docker compose -f deploy/docker-compose.yml exec -T db \
  psql -U wrzdj wrzdj
```

### SSL certificate renewal

Certbot auto-renews certificates. To manually renew:
```bash
sudo wrzdj-certbot renew
sudo systemctl reload nginx
```

## Troubleshooting

### Container won't start

Check logs:
```bash
docker compose -f deploy/docker-compose.yml logs api
```

Common issues:
- Database not ready: container restarts until DB is healthy
- Missing env vars: check `deploy/.env` has all required values

### CORS errors

Verify `CORS_ORIGINS` in `deploy/.env` matches your frontend domain exactly:
```
CORS_ORIGINS=https://app.yourdomain.com
```

### 502 Bad Gateway

Check if containers are running:
```bash
docker compose -f deploy/docker-compose.yml ps
```

Ensure nginx is proxying to correct ports (defaults: api on 8000, web on 3000).
If you changed `PORT_API` or `PORT_FRONTEND`, re-run `setup-nginx.sh` with the same values.

## Security Checklist

### Application Security
- [ ] Strong `JWT_SECRET` (use `openssl rand -hex 32`)
- [ ] Strong `POSTGRES_PASSWORD`
- [ ] `CORS_ORIGINS` set to specific domain (not `*`)
- [ ] Database not exposed externally (127.0.0.1 only)
- [ ] Rate limiting enabled (auto-enabled in production)
- [ ] Login lockout enabled (auto-enabled in production)

### Server Security
- [ ] Dedicated `wrzdj` deploy user (not running as root)
- [ ] Root SSH login disabled (`PermitRootLogin no`)
- [ ] HTTPS enabled (certbot)
- [ ] Firewall configured (only 80, 443, 22 open)
- [ ] nginx version hidden (`server_tokens off`)
- [ ] SSH key authentication (disable password auth)
- [ ] Limited sudo via `/etc/sudoers.d/wrzdj` (nginx, certbot, systemd only)

> **Note on Docker group membership:** The `wrzdj` user is added to the `docker` group,
> which is functionally equivalent to root access on the host (any docker group member
> can mount the host filesystem via `docker run -v /:/host`). The sudoers restrictions
> still provide defense-in-depth against accidental misuse and limit the attack surface
> if only the shell is compromised without docker CLI access. For stronger isolation,
> consider rootless Docker or Podman.

### Security Headers (verify in browser dev tools)
- [ ] `Strict-Transport-Security` (HSTS)
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `X-Frame-Options: DENY` or `SAMEORIGIN`
- [ ] `X-XSS-Protection: 1; mode=block`
- [ ] `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] `Content-Security-Policy` (CSP)

Verify headers:
```bash
curl -I https://api.yourdomain.com/health | grep -iE 'strict|x-frame|x-content|x-xss|referrer|security'
```

See `docs/security/manual-checklist.md` for the complete security checklist.
