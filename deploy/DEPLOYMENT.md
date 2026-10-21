# WrzDJ VPS Deployment Guide

## Quick Start (Pre-built Images)

Pull and run without building from source — no compiler, no git, no Node.js needed on the server.

### Prerequisites

- **Docker Engine 24+** and **`docker compose` v2** (`docker compose version` should print `v2.x`)
- **~2 GB RAM**, ~5 GB disk for images + Postgres data volume
- Outbound HTTPS access to `ghcr.io` for image pulls
- Ports `8000` (API) and `3000` (web) free, or override via `PORT_API` / `PORT_FRONTEND` in `.env`

### Steps

```bash
# 1a. Option A — Clone the repo (always latest)
git clone https://github.com/wrzonance/WrzDJ.git
cd WrzDJ

# 1b. Option B — Or grab the deploy bundle from a release (no source code)
#     curl -L -o wrzdj-deploy.tar.gz \
#       https://github.com/wrzonance/WrzDJ/releases/latest/download/wrzdj-deploy-scripts.tar.gz
#     mkdir wrzdj && tar -xzf wrzdj-deploy.tar.gz -C wrzdj && cd wrzdj

# 2. Copy the env template and fill in REQUIRED values
cp deploy/.env.example deploy/.env
# Edit deploy/.env — required:
#   POSTGRES_PASSWORD, JWT_SECRET, TOKEN_ENCRYPTION_KEY, HUMAN_COOKIE_SECRET,
#   CORS_ORIGINS, PUBLIC_URL, NEXT_PUBLIC_API_URL
# Optional integrations (leave blank if unused):
#   SPOTIFY_*, TIDAL_*, BEATPORT_*, TURNSTILE_*, RESEND_*, BRIDGE_API_KEY

# 3. Deploy
./deploy/deploy-ghcr.sh              # pulls stable (newest release), restarts stack, waits for /health
./deploy/deploy-ghcr.sh v2026.05.16  # or pin a specific release
./deploy/deploy-ghcr.sh latest       # or run HEAD of main (unreleased)
```

### Verify the deploy

```bash
curl -sf http://127.0.0.1:8000/health   # expect: {"status":"ok"}
docker compose -f deploy/docker-compose.ghcr.yml ps  # all "Up (healthy)"
```

Images are published automatically on every push to `main` and on every `v*` tag.
`vYYYY.MM.DD` is built on a release tag and `stable` is promoted to it once both the
api and web images exist, so `stable` is always a matching pair; `latest` / `main`
follow HEAD of main. To seed `stable` for the first time or roll it back to an
earlier release, run the *Promote Stable* workflow from the Actions tab with the tag:
- [ghcr.io/wrzonance/wrzdj-api](https://github.com/wrzonance/WrzDJ/pkgs/container/wrzdj-api)
- [ghcr.io/wrzonance/wrzdj-web](https://github.com/wrzonance/WrzDJ/pkgs/container/wrzdj-web)

> **Authentication errors on first pull?** New GHCR packages default to **private**, even on a public repo. If `docker pull` returns `401 Unauthorized`, the package owner needs to toggle visibility to public (one-time, in the package settings on the link above). If the package is public and you still see 401, open an issue.

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
- `TOKEN_ENCRYPTION_KEY` - Fernet key for OAuth tokens at rest. Generate with:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  (a 44-char url-safe-base64 key — **not** `openssl rand -hex 32`, which is rejected at startup)
- `HUMAN_COOKIE_SECRET` - `openssl rand -base64 32` (signs `wrzdj_human` verification cookie)
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` - Spotify Developer Dashboard
- `TIDAL_CLIENT_ID` / `TIDAL_CLIENT_SECRET` - Tidal Developer Portal (playlist sync)
- `BEATPORT_CLIENT_ID` / `BEATPORT_CLIENT_SECRET` - Beatport API (electronic music search/sync)
- `BRIDGE_API_KEY` - shared secret for the bridge → API auth
- `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` - Cloudflare Turnstile (human verification + DJ self-reg CAPTCHA)
- `RESEND_API_KEY` - Resend transactional email (guest email verification + cross-device merge)
- `EMAIL_FROM_ADDRESS` - verified send-from address (e.g. `noreply@send.yourdomain.com`)
- `SOUNDCHARTS_APP_ID` / `SOUNDCHARTS_API_KEY` - optional, third candidate source for recommendations

> **Note:** `ANTHROPIC_API_KEY` no longer enables AI Assist. The env-var credential
> path was removed in #343; LLM credentials now flow through the LLM Gateway connector
> system (configured in-app, see `ARCHITECTURE.md`). Setting `ANTHROPIC_API_KEY` has no effect.

### 3. Configure nginx

nginx and certbot should already be installed from the root setup step above.

```bash
# Generate and install nginx configs from templates
# Replace yourdomain.com with your actual domain
APP_DOMAIN=app.yourdomain.com API_DOMAIN=api.yourdomain.com ./deploy/setup-nginx.sh

# The setup script will:
# - Generate configs from deploy/nginx/*.conf.template
# - Install deploy/nginx/logging.conf and tuning.conf to /etc/nginx/conf.d/
# - Install vhost configs to /etc/nginx/sites-available/
# - Symlink to sites-enabled/
# - Test and reload nginx
#
# Optional: customize ports (default 8000/3000)
# APP_DOMAIN=app.yourdomain.com API_DOMAIN=api.yourdomain.com \
#   PORT_API=9000 PORT_FRONTEND=4000 ./deploy/setup-nginx.sh
#
# Optional: concurrent SSE streams allowed per client address (default 500).
# A venue on shared wifi is one address and every open event page holds a
# stream, so size this for your largest room; see SECURITY.md.
# SSE_CONN_LIMIT=1000 APP_DOMAIN=... API_DOMAIN=... ./deploy/setup-nginx.sh

# Remove default site (optional)
sudo rm -f /etc/nginx/sites-enabled/default

# setup-nginx.sh installs the versioned http-context tuning include; do not
# hand-edit /etc/nginx/nginx.conf for WrzDJ gzip/TLS/rate-limit defaults.

# Start nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

### 4. Set up SSL certificates with Let's Encrypt

**Important:** DNS must be pointing to your server before running certbot.

```bash
# On a fresh host setup-nginx.sh leaves an HTTP-only bootstrap for validation.
# Replace admin@yourdomain.com below with an address for the ACME account. The
# first command registers that account noninteractively (--agree-tos is required).
# Get the ECDSA certificates through the restricted nginx wrapper.
sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name api.yourdomain.com --key-type ecdsa -d api.yourdomain.com
sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name app.yourdomain.com --key-type ecdsa -d app.yourdomain.com

# Get the RSA certificates required for corporate proxy compatibility.
# The nginx templates load both lineages for every HTTPS vhost.
sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name api.yourdomain.com-rsa --key-type rsa -d api.yourdomain.com
sudo wrzdj-certbot --nginx --agree-tos --email admin@yourdomain.com --cert-name app.yourdomain.com-rsa --key-type rsa -d app.yourdomain.com

# Install the HTTPS vhosts after all four lineages exist.
APP_DOMAIN=app.yourdomain.com API_DOMAIN=api.yourdomain.com ./deploy/setup-nginx.sh

# Verify auto-renewal is enabled
sudo systemctl status certbot.timer

# Test renewal (dry run)
sudo wrzdj-certbot renew --dry-run
```

#### Migrating an existing Certbot installation

The four commands above describe a fresh host. Before changing an existing host, inspect its
lineages with `sudo certbot certificates` and review every SAN on any shared lineage. Keep the full
SAN set intact while planning replacement with one lineage per WrzDJ hostname and vhost; do not
blindly reuse or narrow a shared lineage. Complete that migration administratively, then rerun
`setup-nginx.sh` only after all four hostname-specific lineages are available.

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

## Automated production deploy

Pushing a release tag deploys it. `docker-publish.yml` first checks that the tag is
well-formed and that its commit is on `main` (otherwise nothing is built), builds
the `vYYYY.MM.DD` and `sha-<commit>` images, promotes `stable` once both exist, and
then its `deploy-production` job SSHes to the host with `<tag> <commit sha>`. On
the host, `wrzdj-ci-deploy` (the installed copy of `deploy/ci-deploy.sh`) takes a
host-wide lock, re-verifies that the tag still points at that commit and that the
commit is on `origin/main`, refuses a commit older than the last successful deploy
unless told to roll back, checks the repo out at it, runs `deploy-ghcr.sh
sha-<commit>` (so the containers run exactly what the workflow built), regenerates
nginx only if `deploy/nginx/` changed since the last *successful* deploy, records
the commit in `deploy/.ci-last-deployed`, and prunes dangling images. The job then
polls the public `/health` endpoint. Each run appears under the repo's
**production** environment.

Release flow: merge to green `main`, then `git tag v$(date +%Y.%m.%d) && git push
origin --tags`. Same-day re-release: `v2026.10.18.2`.

**Rollback**, on the host (the automated path never deploys backwards):

```bash
WRZDJ_ALLOW_ROLLBACK=1 wrzdj-ci-deploy v2026.10.05
```

To move `stable` back for self-hosters as well, run the *Promote Stable* workflow
with the older tag.

### One-time setup

1. **Install the entrypoint outside the checkout.** It is deploy policy, so a
   deploy must not be able to replace it; an older release checked out by
   `git checkout` would otherwise overwrite or delete it. Re-run this whenever
   `deploy/ci-deploy.sh` changes.

   ```bash
   install -m 0755 deploy/ci-deploy.sh /usr/local/bin/wrzdj-ci-deploy
   ```

2. **Create a key used for nothing else**, on your workstation:

   ```bash
   ssh-keygen -t ed25519 -N '' -C wrzdj-ci-deploy -f ./wrzdj-ci-deploy
   ```

3. **Lock the key to the entrypoint**, on the host. `restrict` turns off port
   forwarding, agent forwarding, X11 and PTY allocation; `command=` means the key
   can run nothing else, and sshd hands the client's requested command (the tag
   and commit) to the script as `SSH_ORIGINAL_COMMAND`:

   ```bash
   echo 'restrict,command="WRZDJ_REPO_DIR=/root/WrzDJ /usr/local/bin/wrzdj-ci-deploy" '"$(cat wrzdj-ci-deploy.pub)" \
     >> ~/.ssh/authorized_keys
   ```

4. **Test the lock before storing the key anywhere**, from your workstation:

   ```bash
   ssh -i wrzdj-ci-deploy -o IdentitiesOnly=yes root@203.0.113.10 bogus
   # expect: refusing to deploy 'bogus'
   ```

5. **Protect the trigger.** Only repository admins may create, move or delete
   `v*` tags, and the `production` environment accepts deployments only from
   `v*` tags. Both are enforced by GitHub, outside the workflow file, so a
   modified workflow on an unreviewed commit cannot reach the environment's
   secrets:

   ```bash
   gh api -X POST repos/OWNER/REPO/rulesets --input - <<'JSON'
   {"name":"Release tags: admins only","target":"tag","enforcement":"active",
    "bypass_actors":[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}],
    "conditions":{"ref_name":{"include":["refs/tags/v*"],"exclude":[]}},
    "rules":[{"type":"creation"},{"type":"update"},{"type":"deletion"},{"type":"non_fast_forward"}]}
   JSON
   gh api -X PUT repos/OWNER/REPO/environments/production \
     -F 'deployment_branch_policy[protected_branches]=false' \
     -F 'deployment_branch_policy[custom_branch_policies]=true'
   gh api -X POST repos/OWNER/REPO/environments/production/deployment-branch-policies \
     -f name='v*' -f type=tag
   ```

   To also require a manual approval click before each deploy, add yourself as a
   required reviewer on the environment in the repo settings.

6. **Store the connection details** on the environment (scoped to it):

   ```bash
   gh secret set PROD_DEPLOY_SSH_KEY     --env production < wrzdj-ci-deploy
   gh secret set PROD_DEPLOY_HOST        --env production --body "203.0.113.10"
   gh secret set PROD_DEPLOY_USER        --env production --body "root"
   gh secret set PROD_DEPLOY_KNOWN_HOSTS --env production --body "$(ssh-keyscan -t ed25519 203.0.113.10 2>/dev/null)"
   gh variable set PROD_API_URL          --env production --body "https://api.yourdomain.com"
   shred -u wrzdj-ci-deploy
   ```

   Compare the `ssh-keyscan` output with the host key you already trust in
   `~/.ssh/known_hosts` before storing it.

## Testing environment (`testing` branch)

A second, fully separate WrzDJ stack runs on the same host behind
`testing.wrzdj.com` / `testing-api.wrzdj.com` (#844). It exists to run an
unproven branch in the wild — real TLS, real QR codes, real Turnstile, a real
bridge connection — before that branch reaches `main`. Nothing is shared with
production except the machine and nginx: the testing stack has its own git
checkout (`/root/WrzDJ-testing`), its own `deploy/.env` with its own secrets,
its own Compose project (`wrzdj-testing`: own database and uploads volumes),
its own host ports (`8001` / `3001`), its own nginx vhosts and certificates,
and its own SSH deploy key that can run nothing but the testing entrypoint.

**Flow.** Open the PR against `testing` (or retarget an existing one:
`gh pr edit N --base testing`) and merge it. `docker-publish.yml` builds the
`testing` and `testing-sha-<commit>` images (amd64 only, their own tag
namespace: a testing build can never overwrite an image production deploys by) and its `deploy-testing` job,
scoped to the `testing` GitHub environment, SSHes to the host with the commit
sha. On the host `wrzdj-ci-deploy-testing` (the installed copy of
`deploy/ci-deploy-testing.sh`) takes its own lock, re-verifies that the commit
is on `origin/testing`, checks the testing clone out at it (refusing a commit that tracks
`deploy/.env`, which must stay the operator's file), runs
`deploy-ghcr.sh testing-sha-<commit>` under the testing `deploy/.env`, regenerates only
the two testing vhosts (`WRZDJ_NGINX_VHOSTS_ONLY=1`) if `deploy/nginx/` changed
since the last successful testing deploy, records the commit and prunes
dangling images. The job then polls `https://testing-api.wrzdj.com/health`.

**Promote.** When the branch holds up, open a PR from `testing` to `main` and
merge it; release as usual with a tag. **Resync** `testing` to `main` whenever
it has drifted or you want to start over (admins bypass the branch ruleset):

```bash
git fetch origin && git push --force origin origin/main:testing
```

The resync itself deploys `main`'s commit to the testing stack; moving the
stack backwards is allowed here on purpose (production refuses it).

**Manual deploy / inspect**, on the host:

```bash
wrzdj-ci-deploy-testing <full commit sha on origin/testing>
docker compose -p wrzdj-testing -f /root/WrzDJ-testing/deploy/docker-compose.ghcr.yml ps
docker compose -p wrzdj-testing -f /root/WrzDJ-testing/deploy/docker-compose.ghcr.yml logs -f api
```

The testing database starts empty; the bootstrap admin comes from the
`BOOTSTRAP_ADMIN_*` values in `/root/WrzDJ-testing/deploy/.env`.

### One-time setup

1. **DNS.** `A` records for `testing.wrzdj.com` and `testing-api.wrzdj.com`
   pointing at the host (DreamHost panel → Websites → Manage Websites →
   wrzdj.com → DNS, for this deployment).

2. **Checkout, env and entrypoint**, on the host as root:

   ```bash
   git clone https://github.com/wrzonance/WrzDJ /root/WrzDJ-testing
   cp /root/WrzDJ-testing/deploy/.env.example /root/WrzDJ-testing/deploy/.env
   chmod 600 /root/WrzDJ-testing/deploy/.env
   # Edit it: fresh JWT_SECRET / TOKEN_ENCRYPTION_KEY / HUMAN_COOKIE_SECRET /
   # POSTGRES_PASSWORD / BRIDGE_API_KEY / BOOTSTRAP_ADMIN_PASSWORD, and:
   #   COMPOSE_PROJECT_NAME=wrzdj-testing
   #   PORT_API=8001
   #   PORT_FRONTEND=3001
   #   PUBLIC_URL=https://testing.wrzdj.com
   #   NEXT_PUBLIC_API_URL=https://testing-api.wrzdj.com
   #   CORS_ORIGINS=https://testing.wrzdj.com
   #   TIDAL_REDIRECT_URI / BEATPORT_REDIRECT_URI on testing-api.wrzdj.com
   install -m 0755 /root/WrzDJ-testing/deploy/ci-deploy-testing.sh /usr/local/bin/wrzdj-ci-deploy-testing
   ```

   `COMPOSE_PROJECT_NAME` is what keeps the two stacks apart: without it both
   checkouts' `deploy/` directories resolve to the same Compose project and the
   testing deploy would replace production's containers. Re-run the `install`
   whenever `deploy/ci-deploy-testing.sh` changes; deploys never update it.

3. **nginx and certificates**, on the host. Vhosts-only mode leaves the shared
   `conf.d` includes and the catch-all (production's) untouched and installs
   HTTP bootstraps for the two new hostnames so certbot can validate:

   ```bash
   cd /root/WrzDJ-testing
   WRZDJ_NGINX_VHOSTS_ONLY=1 PORT_API=8001 PORT_FRONTEND=3001 \
     APP_DOMAIN=testing.wrzdj.com API_DOMAIN=testing-api.wrzdj.com ./deploy/setup-nginx.sh
   for d in testing.wrzdj.com testing-api.wrzdj.com; do
     certbot --nginx --non-interactive --agree-tos --email admin@wrzdj.com --cert-name "$d"     --key-type ecdsa -d "$d"
     certbot --nginx --non-interactive --agree-tos --email admin@wrzdj.com --cert-name "$d-rsa" --key-type rsa   -d "$d"
   done
   WRZDJ_NGINX_VHOSTS_ONLY=1 PORT_API=8001 PORT_FRONTEND=3001 \
     APP_DOMAIN=testing.wrzdj.com API_DOMAIN=testing-api.wrzdj.com ./deploy/setup-nginx.sh
   ```

4. **A deploy key used for nothing else**, on your workstation, and lock it to
   the testing entrypoint on the host (same `restrict,command=` pattern as
   production, different script and checkout):

   ```bash
   ssh-keygen -t ed25519 -N '' -C wrzdj-ci-deploy-testing -f ./wrzdj-ci-deploy-testing
   # on the host:
   echo 'restrict,command="WRZDJ_REPO_DIR=/root/WrzDJ-testing /usr/local/bin/wrzdj-ci-deploy-testing" '"$(cat wrzdj-ci-deploy-testing.pub)" \
     >> ~/.ssh/authorized_keys
   # back on the workstation — test the lock before storing the key anywhere:
   ssh -i wrzdj-ci-deploy-testing -o IdentitiesOnly=yes root@HOST bogus
   # expect: refusing to deploy 'bogus'
   ```

5. **GitHub: branch, ruleset, environment, secrets.** The environment admits
   deployments only from the `testing` branch, so a workflow edited on any other
   branch cannot reach its secrets. The ruleset requires a PR and the same
   checks as `main`, forbids deletion and non-fast-forward pushes, and lets
   repository admins bypass it for the resync above.

   ```bash
   git push origin origin/main:refs/heads/testing          # create the branch from main
   gh api -X PUT repos/OWNER/REPO/environments/testing \
     -F 'deployment_branch_policy[protected_branches]=false' \
     -F 'deployment_branch_policy[custom_branch_policies]=true'
   gh api -X POST repos/OWNER/REPO/environments/testing/deployment-branch-policies \
     -f name=testing -f type=branch
   gh api -X POST repos/OWNER/REPO/rulesets --input - <<'JSON'
   {"name":"Testing branch: PR only","target":"branch","enforcement":"active",
    "bypass_actors":[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}],
    "conditions":{"ref_name":{"include":["refs/heads/testing"],"exclude":[]}},
    "rules":[{"type":"deletion"},{"type":"non_fast_forward"},
             {"type":"pull_request","parameters":{"required_approving_review_count":0,
              "dismiss_stale_reviews_on_push":false,"require_code_owner_review":false,
              "require_last_push_approval":false,"required_review_thread_resolution":false}},
             {"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":false,
              "required_status_checks":[{"context":"Backend Tests"},{"context":"Frontend Tests"},
               {"context":"Bridge Tests"},{"context":"Bridge App Tests"},{"context":"Kiosk WiFi Portal Tests"},
               {"context":"Docker Build Smoke Test"},{"context":"Trivy Gate"}]}}]}
   JSON
   gh secret set TESTING_DEPLOY_SSH_KEY     --env testing < wrzdj-ci-deploy-testing
   gh secret set TESTING_DEPLOY_HOST        --env testing --body "HOST"
   gh secret set TESTING_DEPLOY_USER        --env testing --body "root"
   gh secret set TESTING_DEPLOY_KNOWN_HOSTS --env testing --body "$(ssh-keyscan -t ed25519 HOST 2>/dev/null)"
   gh variable set TESTING_API_URL          --env testing --body "https://testing-api.wrzdj.com"
   shred -u wrzdj-ci-deploy-testing
   ```

   Through the web UI instead: repository **Settings → Environments → testing**;
   **Deployment branches and tags → Selected branches and tags → Add deployment
   branch or tag rule** (Ref type *Branch*, pattern `testing`); then under
   **Environment secrets → Add secret** paste the *private* key file's full
   contents (the `-----BEGIN OPENSSH PRIVATE KEY-----` … `-----END …-----` block,
   newlines included) as `TESTING_DEPLOY_SSH_KEY`, and the other three secrets
   and the `TESTING_API_URL` variable as above. Compare the `ssh-keyscan` output
   with the host key you already trust in `~/.ssh/known_hosts` before storing it.

6. **Hostname-bound third parties.** The testing stack reuses production's
   provider credentials, so each provider must also accept the testing hostnames:

   - **Cloudflare Turnstile** — the site key only works on the hostnames listed
     on its widget. Dashboard → **Turnstile** → select the widget → **Settings**
     → **Hostname Management → Add Hostnames** → enter `testing.wrzdj.com` →
     **Add**. (Adding the parent `wrzdj.com` would cover every subdomain
     instead; free widgets allow 10 hostnames.) The site key does not change.
     Until this is done, guests on testing cannot pass human verification.
   - **Tidal / Beatport** developer apps — add the `TIDAL_REDIRECT_URI` /
     `BEATPORT_REDIRECT_URI` values from the testing `deploy/.env` (on
     `testing-api.wrzdj.com`) as allowed redirect URIs. Until then the DJ
     "connect" flows on testing fail at the provider; everything else works.

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

### Update nginx config on a running deployment

The container rebuild above does **not** touch nginx — nginx is host-level
(systemd), not containerized. Whenever a pull changes anything under
`deploy/nginx/` (the `*.conf.template` vhosts or the `tuning.conf` /
`logging.conf` http-context includes), re-run the setup script to roll those
changes onto the live box:

```bash
# Same APP_DOMAIN / API_DOMAIN you used for the initial setup
APP_DOMAIN=app.yourdomain.com API_DOMAIN=api.yourdomain.com ./deploy/setup-nginx.sh
```

`setup-nginx.sh` is idempotent and **fail-closed**: it regenerates the vhosts,
reinstalls `wrzdj-logging.conf` + `wrzdj-tuning.conf` to `/etc/nginx/conf.d/`,
runs `nginx -t`, and only `systemctl reload nginx` if the test passes — so a bad
config can never take a running site down (the old config keeps serving).

> `tuning.conf` is an **http-context** include: its gzip, timeout, and
> rate-limit-zone settings apply to every vhost on this nginx. It deliberately
> does **not** restate `gzip on`, `server_tokens off`, or `ssl_protocols` —
> those are already declared by the base `/etc/nginx/nginx.conf` and the
> per-vhost certbot include, and repeating them in an http-level include is a
> fatal `"directive is duplicate"` error that fails `nginx -t`.

Verify after reload:

```bash
# gzip on proxied JSON — must be a GET (HEAD has no body to compress) against a
# response larger than gzip_min_length (1024B); /health is far too small to gzip
curl -sH 'Accept-Encoding: gzip' -D - -o /dev/null https://api.yourdomain.com/openapi.json | grep -i content-encoding
# edge rate limit returns 429 past the burst on a non-SSE endpoint
# SSE stream still connects and is NOT throttled (long-lived, exempt from limit_req);
# it is capped per address by limit_conn instead (SSE_CONN_LIMIT, default 500; 429 past it)
# only TLS 1.2/1.3 negotiated; security headers unchanged on all vhosts
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

### Upgrading PostgreSQL (16 -> 18)

The stack runs PostgreSQL 18. PostgreSQL cannot open another major version's data
directory, and the PostgreSQL 18 image stores data under
`/var/lib/postgresql/18/docker` (the volume mounts at `/var/lib/postgresql`).

**The deploy scripts handle this.** `deploy.sh` and `deploy-ghcr.sh` run
`deploy/scripts/upgrade-postgres-volume.sh` before touching the stack:

- A fresh or already-upgraded volume is a no-op.
- A volume still holding PostgreSQL 16 is migrated with a dump/restore: the stack
  is stopped, the whole cluster is dumped with PostgreSQL 16 (`pg_dumpall`, so
  roles, ownership and every database come along), the old data files are copied
  to the Docker volume `<volume>_pg16_backup`, and the dump is restored into
  PostgreSQL 18 on the original volume. Every database's relation and row counts
  and the role list must match before it is declared done. The dump is kept,
  owner-readable only, in `deploy/backups/`. The deploy then continues as usual;
  downtime is the dump + restore time.
- It refuses, with the running stack untouched, if the volume holds anything it
  does not recognise, a backup volume from an earlier upgrade exists, or free
  disk space is too low (twice the database size next to the volume, once in
  `deploy/backups/`).
- If anything fails, the PostgreSQL 16 files are copied back, the volume is
  exactly as it was, and the services that were running are started again.
- If the script is killed mid-upgrade (reboot, lost SSH session), the next deploy
  detects the interrupted state, restores the PostgreSQL 16 files and retries.
  Anything found in the volume at that point is first copied to a
  `<volume>_interrupted_<timestamp>` volume, never deleted.

For a stack started without the deploy scripts (including local development),
run the same script against its Compose file:

```bash
deploy/scripts/upgrade-postgres-volume.sh docker-compose.yml          # local dev
deploy/scripts/upgrade-postgres-volume.sh deploy/docker-compose.yml   # production
```

With plain `docker compose up` and no upgrade, the PostgreSQL 18 container refuses
to start on PostgreSQL 16 data rather than creating an empty database.

**Rollback to the previous release** after a completed upgrade: stop the stack,
copy the backup volume's contents back over the data volume, then deploy the old
release. Anything written to PostgreSQL 18 in the meantime is not carried back.

```bash
docker compose -f deploy/docker-compose.yml down
docker run --rm -v deploy_postgres_data_pg16_backup:/from:ro -v deploy_postgres_data:/to \
  alpine sh -c 'find /to -mindepth 1 -delete && cp -a /from/. /to/'
```

**Cleanup**: once the upgrade has proven itself,
`docker volume rm deploy_postgres_data_pg16_backup`.

To restore into a differently named volume instead, set `POSTGRES_VOLUME_NAME` in
`deploy/.env`. This path is exercised in CI by `scripts/test-postgres-upgrade.sh`.

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
