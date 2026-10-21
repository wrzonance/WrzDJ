#!/usr/bin/env bash
set -euo pipefail

# Deploy policy for the testing environment (#844): only a commit that has
# reached origin/testing may deploy, moving backwards is allowed (the branch is
# resynced from main), and nginx is refreshed in vhosts-only mode.
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

git init --bare "$scratch/origin.git" >/dev/null
git clone "$scratch/origin.git" "$scratch/repo" >/dev/null 2>&1
git -C "$scratch/repo" config user.name 'Deploy test'
git -C "$scratch/repo" config user.email deploy-test@example.invalid
git -C "$scratch/repo" checkout -b main >/dev/null 2>&1
mkdir -p "$scratch/repo/deploy"
cat > "$scratch/repo/deploy/deploy-ghcr.sh" <<'DEPLOY'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_FAKE_DEPLOY_LOG"
[ "${WRZDJ_FAKE_DEPLOY_FAIL:-0}" != 1 ]
DEPLOY
cat > "$scratch/repo/deploy/setup-nginx.sh" <<'NGINX'
#!/usr/bin/env bash
printf 'APP_DOMAIN=%s API_DOMAIN=%s PORT_API=%s PORT_FRONTEND=%s VHOSTS_ONLY=%s\n' \
  "${APP_DOMAIN:-}" "${API_DOMAIN:-}" "${PORT_API:-}" \
  "${PORT_FRONTEND:-}" "${WRZDJ_NGINX_VHOSTS_ONLY:-}" >> "$WRZDJ_FAKE_NGINX_LOG"
[ "${WRZDJ_FAKE_NGINX_FAIL:-0}" != 1 ]
NGINX
chmod +x "$scratch/repo/deploy/deploy-ghcr.sh" "$scratch/repo/deploy/setup-nginx.sh"
printf 'base\n' > "$scratch/repo/app.txt"
cat > "$scratch/repo/deploy/.env" <<'ENV'
PUBLIC_URL=https://testing.example.test
NEXT_PUBLIC_API_URL=https://api-testing.example.test
PORT_API=8001
PORT_FRONTEND=3001
ENV
git -C "$scratch/repo" add .
git -C "$scratch/repo" commit -m base >/dev/null
git -C "$scratch/repo" push -u origin main >/dev/null 2>&1
base_sha="$(git -C "$scratch/repo" rev-parse HEAD)"

# testing = main + one merged change; main moves on independently.
git -C "$scratch/repo" checkout -b testing >/dev/null 2>&1
printf 'under test\n' >> "$scratch/repo/app.txt"
git -C "$scratch/repo" commit -am 'merge candidate' >/dev/null
git -C "$scratch/repo" push -u origin testing >/dev/null 2>&1
testing_sha="$(git -C "$scratch/repo" rev-parse HEAD)"

git -C "$scratch/repo" checkout main >/dev/null 2>&1
printf 'released\n' > "$scratch/repo/release.txt"
git -C "$scratch/repo" add release.txt
git -C "$scratch/repo" commit -m 'main only' >/dev/null
git -C "$scratch/repo" push origin main >/dev/null 2>&1
main_only_sha="$(git -C "$scratch/repo" rev-parse HEAD)"

git -C "$scratch/repo" checkout -b feature testing >/dev/null 2>&1
printf 'unmerged\n' > "$scratch/repo/feature.txt"
git -C "$scratch/repo" add feature.txt
git -C "$scratch/repo" commit -m feature >/dev/null
git -C "$scratch/repo" push origin feature >/dev/null 2>&1
feature_sha="$(git -C "$scratch/repo" rev-parse HEAD)"
git -C "$scratch/repo" checkout testing >/dev/null 2>&1

mkdir "$scratch/bin"
cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WRZDJ_FAKE_DOCKER_LOG"
[ "$*" = 'image prune -f' ]
DOCKER
chmod +x "$scratch/bin/docker"
export PATH="$scratch/bin:$PATH"
export WRZDJ_REPO_DIR="$scratch/repo"
export WRZDJ_DEPLOY_LOCK="$scratch/deploy.lock"
export WRZDJ_FAKE_DEPLOY_LOG="$scratch/deploy.log"
export WRZDJ_FAKE_NGINX_LOG="$scratch/nginx.log"
export WRZDJ_FAKE_DOCKER_LOG="$scratch/docker.log"
deploy="$source_root/deploy/ci-deploy-testing.sh"

expect_rejected() {
  local description="$1"
  shift
  if bash "$deploy" "$@" >"$scratch/rejected.log" 2>&1; then
    echo "$description was accepted" >&2
    cat "$scratch/rejected.log" >&2
    exit 1
  fi
}

expect_rejected 'branch name instead of a sha' testing
expect_rejected 'abbreviated sha' "${testing_sha:0:7}"
expect_rejected 'unknown sha' 0000000000000000000000000000000000000000
expect_rejected 'commit only on main' "$main_only_sha"
expect_rejected 'commit on an unmerged feature branch' "$feature_sha"
expect_rejected 'extra direct argument' "$testing_sha" ignored
if SSH_ORIGINAL_COMMAND="$testing_sha ignored" bash "$deploy" >"$scratch/ssh-extra.log" 2>&1; then
  echo 'SSH command with an extra argument was accepted' >&2
  exit 1
fi
if SSH_ORIGINAL_COMMAND="$testing_sha"$'\n'"id" bash "$deploy" >"$scratch/ssh-newline.log" 2>&1; then
  echo 'SSH command with a newline was accepted' >&2
  exit 1
fi
test ! -e "$scratch/deploy.log"
test ! -e "$scratch/repo/deploy/.ci-last-deployed"

if WRZDJ_FAKE_DEPLOY_FAIL=1 bash "$deploy" "$testing_sha" >"$scratch/failed-deploy.log" 2>&1; then
  echo 'failed GHCR deploy was treated as a successful testing deploy' >&2
  exit 1
fi
test ! -e "$scratch/repo/deploy/.ci-last-deployed"

bash "$deploy" "$testing_sha" >"$scratch/success.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$testing_sha"
test "$(git -C "$scratch/repo" rev-parse HEAD)" = "$testing_sha"
grep -Fq "sha-${testing_sha:0:7}" "$scratch/deploy.log"
test ! -e "$scratch/nginx.log"
grep -Fq 'image prune -f' "$scratch/docker.log"

# An nginx template change on testing refreshes only the testing vhosts, with
# the testing checkout's own ports and domains.
git -C "$scratch/repo" checkout testing >/dev/null 2>&1
mkdir -p "$scratch/repo/deploy/nginx"
printf 'nginx change\n' > "$scratch/repo/deploy/nginx/app.conf.template"
git -C "$scratch/repo" add deploy/nginx/app.conf.template
git -C "$scratch/repo" commit -m 'nginx change' >/dev/null
git -C "$scratch/repo" push origin testing >/dev/null 2>&1
nginx_sha="$(git -C "$scratch/repo" rev-parse HEAD)"

if WRZDJ_FAKE_NGINX_FAIL=1 bash "$deploy" "$nginx_sha" >"$scratch/nginx-failed.log" 2>&1; then
  echo 'failed nginx refresh was treated as a successful testing deploy' >&2
  exit 1
fi
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$testing_sha"
grep -Fq 'APP_DOMAIN=testing.example.test API_DOMAIN=api-testing.example.test PORT_API=8001 PORT_FRONTEND=3001 VHOSTS_ONLY=1' \
  "$scratch/nginx.log"

SSH_ORIGINAL_COMMAND="$nginx_sha" bash "$deploy" >"$scratch/ssh-success.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$nginx_sha"
test "$(wc -l < "$scratch/nginx.log")" -eq 2

# Resyncing testing from main legitimately moves it to an older or unrelated
# commit, so an earlier commit that is still on origin/testing deploys without
# any override.
bash "$deploy" "$base_sha" >"$scratch/older.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$base_sha"
grep -Fq "sha-${base_sha:0:7}" "$scratch/deploy.log"

# A commit that was on testing but has since been rewritten away is refused:
# the branch is the only trust anchor.
git -C "$scratch/repo" push -f origin "$main_only_sha:refs/heads/testing" >/dev/null 2>&1
expect_rejected 'commit no longer on origin/testing' "$testing_sha"
bash "$deploy" "$main_only_sha" >"$scratch/resync.log" 2>&1
test "$(<"$scratch/repo/deploy/.ci-last-deployed")" = "$main_only_sha"
echo 'Testing deploy accepts only commits on origin/testing, allows resync, and preserves state on failure.'
