# WrzDJ Runbook

Operational procedures for deploying, monitoring, and troubleshooting WrzDJ.

## Deployment

### Local Development (docker-compose.yml at repo root)

```bash
docker compose up -d db                        # Database only
uvicorn app.main:app --reload --host 0.0.0.0   # Backend (from server/)
NEXT_PUBLIC_API_URL="http://LAN_IP:8000" npm run dev  # Frontend (from dashboard/)
```

### Production (deploy/docker-compose.yml)

Full guide: [deploy/DEPLOYMENT.md](../deploy/DEPLOYMENT.md)

```bash
# Build and start all services
docker compose -f deploy/docker-compose.yml up -d --build

# Create admin user
docker compose -f deploy/docker-compose.yml exec api \
  python -m app.scripts.create_user --username admin --password <password>

# Apply database migrations
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head
```

### Render (PaaS)

- Auto-deploys from `main` via `render.yaml`
- Set env vars in Render dashboard (Environment tab)
- Subdomain model: `api.yourdomain.com` + `app.yourdomain.com`

## Monitoring

### Health Checks

| Endpoint | Expected |
|----------|----------|
| `GET /health` | `200` — root health |
| `GET /api/health` | `200` — API health |
| `GET /docs` | Swagger UI loads |

### Logs

```bash
# All services
docker compose -f deploy/docker-compose.yml logs -f

# Single service
docker compose -f deploy/docker-compose.yml logs -f api
docker compose -f deploy/docker-compose.yml logs -f web
docker compose -f deploy/docker-compose.yml logs -f db
```

### Key Metrics to Watch

- API response times (uvicorn access logs)
- Rate limit 429 responses (slowapi)
- Database connection pool exhaustion
- Spotify API quota (search endpoint)

## Common Issues and Fixes

### API returns 502 Bad Gateway

**Cause:** Container not running or nginx misconfigured.

```bash
# Check containers
docker compose -f deploy/docker-compose.yml ps

# Restart API
docker compose -f deploy/docker-compose.yml restart api

# Check nginx config
sudo nginx -t
sudo systemctl reload nginx
```

### CORS Errors in Browser

**Cause:** `CORS_ORIGINS` doesn't match the frontend origin.

```bash
# Verify .env setting matches frontend domain exactly
grep CORS_ORIGINS deploy/.env
# Should be: CORS_ORIGINS=https://app.yourdomain.com
```

### Database Connection Refused

**Cause:** PostgreSQL container not healthy or not started.

```bash
docker compose -f deploy/docker-compose.yml ps db
docker compose -f deploy/docker-compose.yml logs db
docker compose -f deploy/docker-compose.yml restart db
```

### Rate Limiting (429 Too Many Requests)

Rate limits are auto-enabled in production. Current limits:

| Endpoint | Limit |
|----------|-------|
| Login | 5/min per IP |
| Search | 30/min per IP |
| Song request | 10/min per IP |
| Guest request list | 60/min per IP |
| Has-requested check | 30/min per IP |
| Accept all | 10/min per IP |

Override in `.env`:
```
LOGIN_RATE_LIMIT_PER_MINUTE=5
SEARCH_RATE_LIMIT_PER_MINUTE=30
REQUEST_RATE_LIMIT_PER_MINUTE=10
```

### Spotify Search Not Working

**Cause:** Missing or expired credentials.

```bash
# Check if credentials are set
grep SPOTIFY deploy/.env

# Watch API logs for Spotify errors
docker compose -f deploy/docker-compose.yml logs -f api | grep -i spotify
```

### StageLinQ Bridge Not Detecting Equipment

- Bridge must be on same LAN as DJ equipment
- Equipment must be connected via Ethernet (not WiFi)
- Verify `BRIDGE_API_KEY` matches in backend and bridge `.env`
- Check bridge logs: `docker logs wrzdj-bridge`

### Next.js Dev Server Lock File

If the frontend won't start locally:

```bash
rm -f dashboard/.next/dev/lock
# Kill any orphaned processes on port 3000
lsof -ti:3000 | xargs kill -9 2>/dev/null
npm run dev
```

## Database Operations

### Backup

```bash
docker compose -f deploy/docker-compose.yml exec db \
  pg_dump -U wrzdj wrzdj > backup-$(date +%Y%m%d).sql
```

### Restore

```bash
cat backup.sql | docker compose -f deploy/docker-compose.yml exec -T db \
  psql -U wrzdj wrzdj
```

### PostgreSQL Major-Version Upgrade

The deploy scripts upgrade an older PostgreSQL data volume automatically
(`deploy/scripts/upgrade-postgres-volume.sh`: dump, backup volume, restore, rollback
on failure). Details and manual rollback: "Upgrading PostgreSQL (16 -> 18)" in
`deploy/DEPLOYMENT.md`.

### Run Migrations

```bash
# Production
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head

# Local dev
cd server && alembic upgrade head
```

### Create New Migration

```bash
cd server
alembic revision --autogenerate -m "description of change"
```

## Rollback Procedures

### Code Rollback

```bash
# Identify the last good commit
git log --oneline -10

# Revert to previous commit (creates new commit, safe)
git revert HEAD

# Or deploy a specific tag/commit
git checkout <commit-hash>
docker compose -f deploy/docker-compose.yml up -d --build
```

### Database Rollback

```bash
# Downgrade one migration
docker compose -f deploy/docker-compose.yml exec api alembic downgrade -1

# Downgrade to specific revision
docker compose -f deploy/docker-compose.yml exec api alembic downgrade <revision>

# Or restore from backup
cat backup.sql | docker compose -f deploy/docker-compose.yml exec -T db \
  psql -U wrzdj wrzdj
```

### Full Service Restart

```bash
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml up -d --build
```

## SSL Certificates

Certbot auto-renews via systemd timer. Manual renewal:

```bash
sudo certbot renew
sudo systemctl reload nginx

# Check expiry
sudo certbot certificates
```

## Security Checklist

See [deploy/DEPLOYMENT.md](../deploy/DEPLOYMENT.md#security-checklist) for the full checklist.

Quick verification:
```bash
# Check security headers
curl -sI https://api.yourdomain.com/health | grep -iE 'strict|x-frame|x-content|x-xss|referrer'

# Verify database not exposed
ss -tlnp | grep 5432  # Should show 127.0.0.1 only
```
