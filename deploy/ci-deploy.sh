#!/usr/bin/env bash
# WrzDJ CI deploy entrypoint — runs ON the production host, not in Actions.
#
# Install it OUTSIDE the checkout and lock the deploy key to that copy:
#
#   install -m 0755 deploy/ci-deploy.sh /usr/local/bin/wrzdj-ci-deploy
#   # ~/.ssh/authorized_keys:
#   restrict,command="WRZDJ_REPO_DIR=/root/WrzDJ /usr/local/bin/wrzdj-ci-deploy" ssh-ed25519 AAAA... wrzdj-ci-deploy
#
# The checks below are deploy policy, so a deploy must never be able to change
# them: running from the repo would let any release tag (including an older one)
# replace this file with its own copy. Re-run `install` when this file changes.
#
# The GitHub Actions `deploy-production` job (docker-publish.yml) SSHes in with
# that key; sshd exposes what the client asked to run as SSH_ORIGINAL_COMMAND.
# The job sends "<tag> <commit sha>"; those two words are the only input this
# script trusts, and both are re-verified against origin before anything moves.
#
# Manual use on the host:
#   wrzdj-ci-deploy v2026.10.16                          # same or newer release
#   WRZDJ_ALLOW_ROLLBACK=1 wrzdj-ci-deploy v2026.10.05   # go back to an older one
#
# Steps: take the host-wide deploy lock -> validate the tag (and sha, if given)
# -> fetch; require the tag to point at that sha and the sha to be on origin/main
# -> refuse a commit older than the last successful deploy unless rolling back
# on purpose -> check the repo out at the sha -> pull and start the
# `sha-<commit>` GHCR images built from exactly that commit (deploy-ghcr.sh)
# -> regenerate nginx only when the templates changed since the last successful
# deploy -> record the deploy -> drop dangling images.
set -euo pipefail

REPO_DIR="${WRZDJ_REPO_DIR:-/root/WrzDJ}"
LOCK_FILE="${WRZDJ_DEPLOY_LOCK:-/run/lock/wrzdj-deploy.lock}"
# Last commit that fully deployed (stack up, nginx applied). Untracked and
# gitignored, so `git checkout -f` leaves it alone; a failed attempt never
# advances it, so the next try still diffs nginx against what is really live.
STATE_FILE="$REPO_DIR/deploy/.ci-last-deployed"
TAG_PATTERN='^v[0-9]{4}\.[0-9]{2}\.[0-9]{2}(\.[0-9]+)?$'
SHA_PATTERN='^[0-9a-f]{40}$'

main() {
  local tag="${1:-}" expected_sha="${2:-}"
  if [ -z "$tag" ] && [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
    read -r tag expected_sha _ <<<"$SSH_ORIGINAL_COMMAND"
  fi

  if [[ ! "$tag" =~ $TAG_PATTERN ]]; then
    echo "ERROR: refusing to deploy '$tag': expected a release tag v<YYYY>.<MM>.<DD>[.<R>]" >&2
    exit 1
  fi
  if [ -n "$expected_sha" ] && [[ ! "$expected_sha" =~ $SHA_PATTERN ]]; then
    echo "ERROR: refusing to deploy $tag: '$expected_sha' is not a full commit sha" >&2
    exit 1
  fi
  if [ ! -x "$REPO_DIR/deploy/deploy-ghcr.sh" ] || ! git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    echo "ERROR: $REPO_DIR is not a WrzDJ checkout (set WRZDJ_REPO_DIR)" >&2
    exit 1
  fi

  acquire_lock
  cd "$REPO_DIR"

  local previous sha
  previous="$(last_deployed_commit)"
  git fetch -q --tags origin main
  sha="$(resolve_release_commit "$tag" "$expected_sha")"
  refuse_unintended_rollback "$tag" "$sha" "$previous"

  echo "==> Checking out $tag at ${sha:0:12} (last successful deploy: ${previous:0:12})..."
  # -f: the checkout may legitimately overwrite modified or older tracked files.
  git checkout -q -f --detach "$sha"

  echo "==> Deploying GHCR images sha-${sha:0:7} (built from $tag)..."
  "$REPO_DIR/deploy/deploy-ghcr.sh" "sha-${sha:0:7}"

  refresh_nginx_if_changed "$previous" "$sha"

  printf '%s\n' "$sha" > "$STATE_FILE"
  echo "==> Removing dangling images..."
  docker image prune -f >/dev/null
  echo "==> $tag (${sha:0:12}) is live"
}

# One deploy at a time on this host: CI, a manual rollback and a retry must not
# interleave their checkout, `down` and `up`. Held until the script exits.
acquire_lock() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "ERROR: another deploy holds $LOCK_FILE; try again when it finishes" >&2
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

# resolve_release_commit TAG [EXPECTED_SHA]  ->  the tag's commit sha, or exit 1
resolve_release_commit() {
  local tag="$1" expected_sha="$2" sha
  if ! sha="$(git rev-parse -q --verify "refs/tags/$tag^{commit}")"; then
    echo "ERROR: tag $tag does not exist on origin" >&2
    exit 1
  fi
  if [ -n "$expected_sha" ] && [ "$sha" != "$expected_sha" ]; then
    echo "ERROR: refusing to deploy $tag: it points at $sha, but the images were built from $expected_sha (tag moved?)" >&2
    exit 1
  fi
  # Only released trunk reaches production: a tag pushed onto a feature branch
  # (or by anyone who can create tags but not merge) is refused here, on the host.
  if ! git merge-base --is-ancestor "$sha" origin/main; then
    echo "ERROR: refusing to deploy $tag: commit ${sha:0:12} is not on origin/main" >&2
    exit 1
  fi
  echo "$sha"
}

# Two releases built out of order must not roll production backwards by
# accident. Redeploying the live commit is fine; going older needs the operator
# to say so (the SSH forced command cannot set this variable).
refuse_unintended_rollback() {
  local tag="$1" sha="$2" previous="$3"
  [ "$sha" = "$previous" ] && return
  if git merge-base --is-ancestor "$sha" "$previous" && [ "${WRZDJ_ALLOW_ROLLBACK:-0}" != "1" ]; then
    echo "ERROR: refusing to deploy $tag (${sha:0:12}): it is older than the live deploy ${previous:0:12}." >&2
    echo "       To roll back on purpose: WRZDJ_ALLOW_ROLLBACK=1 wrzdj-ci-deploy $tag" >&2
    exit 1
  fi
}

refresh_nginx_if_changed() {
  local previous="$1" current="$2"
  if git diff --quiet "$previous" "$current" -- deploy/nginx deploy/setup-nginx.sh; then
    echo "==> nginx templates unchanged since ${previous:0:12}; leaving nginx alone"
    return
  fi
  echo "==> nginx templates changed; regenerating..."
  # Same environment the stack was started with (deploy-ghcr.sh sources the same
  # file), so PORT_API / PORT_FRONTEND / SSE_CONN_LIMIT overrides reach nginx too.
  (
    set -a
    # shellcheck source=/dev/null
    source "$REPO_DIR/deploy/.env"
    set +a
    APP_DOMAIN="$(host_of "${PUBLIC_URL:-}" PUBLIC_URL)" \
    API_DOMAIN="$(host_of "${NEXT_PUBLIC_API_URL:-}" NEXT_PUBLIC_API_URL)" \
      "$REPO_DIR/deploy/setup-nginx.sh"
  )
}

# host_of https://app.example.com/ PUBLIC_URL  ->  app.example.com
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
