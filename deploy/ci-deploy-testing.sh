#!/usr/bin/env bash
# WrzDJ testing-environment deploy entrypoint — runs ON the host, next to the
# production entrypoint (deploy/ci-deploy.sh) but for the separate testing stack
# (testing.wrzdj.com / testing-api.wrzdj.com, #844).
#
# Install it OUTSIDE the checkout and lock its own deploy key to that copy:
#
#   install -m 0755 deploy/ci-deploy-testing.sh /usr/local/bin/wrzdj-ci-deploy-testing
#   # ~/.ssh/authorized_keys:
#   restrict,command="WRZDJ_REPO_DIR=/root/WrzDJ-testing /usr/local/bin/wrzdj-ci-deploy-testing" ssh-ed25519 AAAA... wrzdj-ci-deploy-testing
#
# The key is different from production's on purpose: a merge to `testing` must
# never be able to reach the production stack. Re-run `install` when this file
# changes; deploys never update it.
#
# The GitHub Actions `deploy-testing` job (docker-publish.yml) SSHes in with that
# key after a push to the protected `testing` branch, sending the full commit
# sha as SSH_ORIGINAL_COMMAND. That sha is the only input this script trusts.
#
# Manual use on the host:
#   wrzdj-ci-deploy-testing <full commit sha on origin/testing>
#
# Policy differs from production in two deliberate ways: the trust anchor is
# "the commit is on origin/testing" instead of a release tag on main, and moving
# backwards is allowed without an override, because resyncing `testing` from
# `main` legitimately rewrites it. Everything else matches: host lock -> fetch
# -> verify -> checkout -> deploy-ghcr.sh testing-sha-<commit> (the testing
# builds' own tag namespace) under this checkout's own deploy/.env (own compose
# project, ports and volumes; a commit tracking that file is refused) -> refresh ONLY this
# stack's nginx vhosts when the templates changed since the last successful
# deploy -> record the deploy -> drop dangling images.
set -euo pipefail

REPO_DIR="${WRZDJ_REPO_DIR:-/root/WrzDJ-testing}"
BRANCH="${WRZDJ_TESTING_BRANCH:-testing}"
LOCK_FILE="${WRZDJ_DEPLOY_LOCK:-/run/lock/wrzdj-testing-deploy.lock}"
STATE_FILE="$REPO_DIR/deploy/.ci-last-deployed"
SHA_PATTERN='^[0-9a-f]{40}$'

main() {
  local sha
  sha="$(requested_commit "$@")"

  if [ ! -x "$REPO_DIR/deploy/deploy-ghcr.sh" ] || ! git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    echo "ERROR: $REPO_DIR is not a WrzDJ checkout (set WRZDJ_REPO_DIR)" >&2
    exit 1
  fi

  acquire_lock
  cd "$REPO_DIR"

  local previous
  previous="$(last_deployed_commit)"
  git fetch -q origin "$BRANCH"
  require_on_branch "$sha"
  require_untracked_env "$sha"

  echo "==> Checking out ${sha:0:12} from $BRANCH (last successful deploy: ${previous:0:12})..."
  # -f: the checkout may legitimately overwrite modified or older tracked files.
  git checkout -q -f --detach "$sha"

  echo "==> Deploying GHCR images testing-sha-${sha:0:7} (built from $BRANCH)..."
  "$REPO_DIR/deploy/deploy-ghcr.sh" "testing-sha-${sha:0:7}"

  refresh_nginx_if_changed "$previous" "$sha"

  printf '%s\n' "$sha" > "$STATE_FILE"
  echo "==> Removing dangling images..."
  if ! docker image prune -f >/dev/null; then
    echo "WARNING: deployment succeeded, but dangling-image cleanup failed" >&2
  fi
  echo "==> $BRANCH at ${sha:0:12} is live on the testing stack"
}

# requested_commit [SHA]  ->  the full sha from the argument or the SSH command
requested_commit() {
  if [ "$#" -gt 1 ]; then
    echo "ERROR: expected exactly one full commit sha" >&2
    exit 2
  fi
  local sha="${1:-}"
  if [ "$#" -eq 0 ] && [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
    local -a ssh_args=()
    if [[ "$SSH_ORIGINAL_COMMAND" == *$'\n'* || "$SSH_ORIGINAL_COMMAND" == *$'\r'* ]]; then
      echo "ERROR: expected exactly one full commit sha" >&2
      exit 2
    fi
    read -r -a ssh_args <<<"$SSH_ORIGINAL_COMMAND"
    if [ "${#ssh_args[@]}" -ne 1 ]; then
      echo "ERROR: expected exactly one full commit sha" >&2
      exit 2
    fi
    sha="${ssh_args[0]}"
  fi
  if [[ ! "$sha" =~ $SHA_PATTERN ]]; then
    echo "ERROR: refusing to deploy '$sha': expected a full 40-character commit sha" >&2
    exit 1
  fi
  echo "$sha"
}

# One testing deploy at a time; separate from the production lock so a testing
# push never makes a release deploy fail with "another deploy holds the lock".
acquire_lock() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "ERROR: another testing deploy holds $LOCK_FILE; try again when it finishes" >&2
    exit 1
  fi
}

# The commit that last fully deployed, falling back to HEAD on first use.
last_deployed_commit() {
  local recorded=""
  [ -f "$STATE_FILE" ] && recorded="$(tr -d '[:space:]' < "$STATE_FILE")"
  if [[ "$recorded" =~ $SHA_PATTERN ]] && git cat-file -e "$recorded^{commit}" 2>/dev/null; then
    echo "$recorded"
  else
    git rev-parse HEAD
  fi
}

# Only commits that reached the protected branch run on the testing stack: a
# sha from an unmerged PR, from main, or rewritten out of the branch is refused
# here, on the host, whatever the workflow asked for.
require_on_branch() {
  local sha="$1"
  if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    echo "ERROR: refusing to deploy ${sha:0:12}: unknown commit" >&2
    exit 1
  fi
  if ! git merge-base --is-ancestor "$sha" "origin/$BRANCH"; then
    echo "ERROR: refusing to deploy ${sha:0:12}: commit is not on origin/$BRANCH" >&2
    exit 1
  fi
}

# deploy/.env holds this stack's secrets and is gitignored. `git checkout -f`
# would replace it with a tracked copy if a commit ever carried one, so such a
# commit never deploys: the file stays the operator's, not the branch's.
require_untracked_env() {
  local sha="$1"
  if git ls-tree -r --name-only "$sha" -- deploy/.env | grep -qx 'deploy/.env'; then
    echo "ERROR: refusing to deploy ${sha:0:12}: it tracks deploy/.env, which must stay untracked" >&2
    exit 1
  fi
}

refresh_nginx_if_changed() {
  local previous="$1" current="$2"
  if git diff --quiet "$previous" "$current" -- deploy/nginx deploy/setup-nginx.sh; then
    echo "==> nginx templates unchanged since ${previous:0:12}; leaving nginx alone"
    return
  fi
  echo "==> nginx templates changed; regenerating the testing vhosts..."
  # Same environment the stack was started with (deploy-ghcr.sh sources the same
  # file). Vhosts-only: the shared conf.d includes and catch-all are production's.
  (
    set -a
    # shellcheck source=/dev/null
    source "$REPO_DIR/deploy/.env"
    set +a
    WRZDJ_NGINX_VHOSTS_ONLY=1 \
    APP_DOMAIN="$(host_of "${PUBLIC_URL:-}" PUBLIC_URL)" \
    API_DOMAIN="$(host_of "${NEXT_PUBLIC_API_URL:-}" NEXT_PUBLIC_API_URL)" \
      "$REPO_DIR/deploy/setup-nginx.sh"
  )
}

# host_of https://testing.example.com/ PUBLIC_URL  ->  testing.example.com
host_of() {
  local url="$1" name="$2" host
  host="${url#*://}"
  host="${host%%/*}"
  if [ -z "$host" ]; then
    echo "ERROR: $name missing from deploy/.env; cannot derive the nginx domain" >&2
    exit 1
  fi
  echo "$host"
}

main "$@"
