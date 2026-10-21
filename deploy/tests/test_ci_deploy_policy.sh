#!/usr/bin/env bash
set -euo pipefail

source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

git init --bare "$scratch/origin.git" >/dev/null
git clone "$scratch/origin.git" "$scratch/repo" >/dev/null 2>&1
git -C "$scratch/repo" config user.name 'Deploy test'
git -C "$scratch/repo" config user.email deploy-test@example.invalid
git -C "$scratch/repo" checkout -b main >/dev/null 2>&1
mkdir -p "$scratch/repo/deploy"
cp "$source_root/deploy/ci-deploy.sh" "$scratch/repo/deploy/ci-deploy.sh"
cat > "$scratch/repo/deploy/deploy-ghcr.sh" <<'DEPLOY'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_FAKE_DEPLOY_LOG"
[ "${WRZDJ_FAKE_DEPLOY_FAIL:-0}" != 1 ]
DEPLOY
cat > "$scratch/repo/deploy/setup-nginx.sh" <<'NGINX'
#!/usr/bin/env bash
printf 'APP_DOMAIN=%s API_DOMAIN=%s PORT_API=%s PORT_FRONTEND=%s SSE_CONN_LIMIT=%s\n' \
  "${APP_DOMAIN:-}" "${API_DOMAIN:-}" "${PORT_API:-}" \
  "${PORT_FRONTEND:-}" "${SSE_CONN_LIMIT:-}" >> "$WRZDJ_FAKE_NGINX_LOG"
[ "${WRZDJ_FAKE_NGINX_FAIL:-0}" != 1 ]
NGINX
chmod +x "$scratch/repo/deploy/deploy-ghcr.sh" "$scratch/repo/deploy/setup-nginx.sh"
printf 'base\n' > "$scratch/repo/app.txt"
cat > "$scratch/repo/deploy/.env" <<'ENV'
PUBLIC_URL=https://app.example.test
NEXT_PUBLIC_API_URL=https://api.example.test
PORT_API=8100
PORT_FRONTEND=3100
SSE_CONN_LIMIT=900
ENV
git -C "$scratch/repo" add .
git -C "$scratch/repo" commit -m base >/dev/null
git -C "$scratch/repo" push -u origin main >/dev/null 2>&1
printf 'release\n' >> "$scratch/repo/app.txt"
git -C "$scratch/repo" commit -am release >/dev/null
git -C "$scratch/repo" tag v2026.10.19
git -C "$scratch/repo" push origin main v2026.10.19 >/dev/null 2>&1
release_sha="$(git -C "$scratch/repo" rev-parse HEAD)"

git -C "$scratch/repo" checkout -b feature >/dev/null 2>&1
printf 'unreleased\n' > "$scratch/repo/feature.txt"
git -C "$scratch/repo" add feature.txt
git -C "$scratch/repo" commit -m feature >/dev/null
git -C "$scratch/repo" tag v2026.10.20
git -C "$scratch/repo" push origin v2026.10.20 >/dev/null 2>&1
git -C "$scratch/repo" checkout main >/dev/null 2>&1

mkdir "$scratch/bin"
cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WRZDJ_FAKE_DOCKER_LOG"
if [ "${WRZDJ_FAKE_PRUNE_FAIL:-0}" = 1 ]; then
  exit 1
fi
[ "$*" = 'image prune -f' ]
DOCKER
chmod +x "$scratch/bin/docker"
export PATH="$scratch/bin:$PATH"
export WRZDJ_REPO_DIR="$scratch/repo"
export WRZDJ_DEPLOY_LOCK="$scratch/deploy.lock"
export WRZDJ_FAKE_DEPLOY_LOG="$scratch/deploy.log"
export WRZDJ_FAKE_NGINX_LOG="$scratch/nginx.log"
export WRZDJ_FAKE_DOCKER_LOG="$scratch/docker.log"
deploy="$source_root/deploy/ci-deploy.sh"

expect_rejected() {
  local description="$1"
  shift
  if bash "$deploy" "$@" >"$scratch/rejected.log" 2>&1; then
    echo "$description was accepted" >&2
    cat "$scratch/rejected.log" >&2
    exit 1
  fi
}

expect_rejected 'malformed tag' release
expect_rejected 'unknown release tag' v2026.10.22
expect_rejected 'tag/image SHA mismatch' v2026.10.19 0000000000000000000000000000000000000000
expect_rejected 'tag outside origin/main' v2026.10.20
expect_rejected 'extra direct argument' v2026.10.19 "$release_sha" ignored
if SSH_ORIGINAL_COMMAND="v2026.10.19 $release_sha ignored" bash "$deploy" \
  >"$scratch/ssh-extra-argument.log" 2>&1; then
  echo 'SSH release command with an extra argument was accepted' >&2
  exit 1
fi
test ! -e "$scratch/repo/deploy/.ci-last-deployed"

if WRZDJ_FAKE_DEPLOY_FAIL=1 bash "$deploy" v2026.10.19 >"$scratch/failed-deploy.log" 2>&1; then
  echo 'failed GHCR deploy was treated as a successful release' >&2
  exit 1
fi
test ! -e "$scratch/repo/deploy/.ci-last-deployed"

bash "$deploy" v2026.10.19 >"$scratch/success.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$release_sha"
test ! -e "$scratch/nginx.log"
grep -Fq 'image prune -f' "$scratch/docker.log"
grep -Fq "sha-${release_sha:0:7}" "$scratch/deploy.log"

git -C "$scratch/repo" checkout main >/dev/null 2>&1
mkdir -p "$scratch/repo/deploy/nginx"
printf 'nginx change\n' > "$scratch/repo/deploy/nginx/app.conf.template"
git -C "$scratch/repo" add deploy/nginx/app.conf.template
git -C "$scratch/repo" commit -m 'nginx release' >/dev/null
git -C "$scratch/repo" tag v2026.10.21
git -C "$scratch/repo" push origin main v2026.10.21 >/dev/null 2>&1
nginx_release_sha="$(git -C "$scratch/repo" rev-parse HEAD)"

if WRZDJ_FAKE_NGINX_FAIL=1 bash "$deploy" v2026.10.21 >"$scratch/nginx-failed.log" 2>&1; then
  echo 'failed nginx refresh was treated as a successful release' >&2
  exit 1
fi
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$release_sha"
grep -Fq 'APP_DOMAIN=app.example.test API_DOMAIN=api.example.test PORT_API=8100 PORT_FRONTEND=3100 SSE_CONN_LIMIT=900' \
  "$scratch/nginx.log"

bash "$deploy" v2026.10.21 >"$scratch/nginx-success.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$nginx_release_sha"
test "$(wc -l < "$scratch/nginx.log")" -eq 2
SSH_ORIGINAL_COMMAND="v2026.10.21 $nginx_release_sha" bash "$deploy" \
  >"$scratch/ssh-success.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$nginx_release_sha"

if ! WRZDJ_FAKE_PRUNE_FAIL=1 bash "$deploy" v2026.10.21 >"$scratch/prune-failed.log" 2>&1; then
  echo 'dangling-image cleanup failure changed a successful deploy into a failure' >&2
  cat "$scratch/prune-failed.log" >&2
  exit 1
fi
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$nginx_release_sha"
grep -Fq 'WARNING: deployment succeeded, but dangling-image cleanup failed' \
  "$scratch/prune-failed.log"

before_rollback_head="$(git -C "$scratch/repo" rev-parse HEAD)"
before_rollback_deploys="$(wc -l < "$scratch/deploy.log")"
if bash "$deploy" v2026.10.19 >"$scratch/unintended-rollback.log" 2>&1; then
  echo 'older release was accepted without the explicit rollback override' >&2
  exit 1
fi
grep -Fq 'refusing to deploy v2026.10.19' "$scratch/unintended-rollback.log"
test "$(git -C "$scratch/repo" rev-parse HEAD)" = "$before_rollback_head"
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$nginx_release_sha"
test "$(wc -l < "$scratch/deploy.log")" -eq "$before_rollback_deploys"

WRZDJ_ALLOW_ROLLBACK=1 bash "$deploy" v2026.10.19 >"$scratch/intentional-rollback.log" 2>&1
test "$(git -C "$scratch/repo" rev-parse HEAD)" = "$release_sha"
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$release_sha"
test "$(wc -l < "$scratch/deploy.log")" -eq "$((before_rollback_deploys + 1))"
grep -Fq "sha-${release_sha:0:7}" "$scratch/deploy.log"
echo 'CI deploy rejects invalid releases, preserves state on failure, and records successful state.'
