#!/usr/bin/env bash
set -euo pipefail

# WRZDJ_COMPOSE_OVERRIDE (#844): a second Compose file from deploy/.env is
# layered onto every Compose invocation, including the volume preflight; a
# missing override aborts before Docker is touched; no override = one file.
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

mkdir -p "$scratch/deploy/scripts" "$scratch/bin"
cp "$source_root/deploy/deploy-ghcr.sh" "$scratch/deploy/deploy-ghcr.sh"
printf 'services: {}\n' > "$scratch/deploy/docker-compose.ghcr.yml"
printf 'services: {}\n' > "$scratch/deploy/docker-compose.testing.yml"
cat > "$scratch/deploy/scripts/upgrade-postgres-volume.sh" <<'UPGRADE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WRZDJ_FAKE_UPGRADE_LOG"
UPGRADE
# The other helpers deploy-ghcr.sh delegates to are out of scope here.
for helper in cleanup-deploy-ports.sh wait-for-api-health.sh; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$scratch/deploy/scripts/$helper"
  chmod +x "$scratch/deploy/scripts/$helper"
done
# chown: the script hands its log directory to the container user, which a
# CI runner (not uid 1000, not root) is not allowed to do.
for tool in docker ss chown; do
  cat > "$scratch/bin/$tool" <<'FAKE'
#!/usr/bin/env bash
printf '%s %s\n' "$(basename "$0")" "$*" >> "$WRZDJ_FAKE_TOOL_LOG"
FAKE
  chmod +x "$scratch/bin/$tool"
done
cat > "$scratch/bin/curl" <<'CURL'
#!/usr/bin/env bash
exit 0
CURL
chmod +x "$scratch/bin/curl" "$scratch/deploy/scripts/upgrade-postgres-volume.sh" "$scratch/deploy/deploy-ghcr.sh"
export PATH="$scratch/bin:$PATH"
export WRZDJ_FAKE_TOOL_LOG="$scratch/tools.log"
export WRZDJ_FAKE_UPGRADE_LOG="$scratch/upgrade.log"
ghcr_file="$scratch/deploy/docker-compose.ghcr.yml"
override_file="$scratch/deploy/docker-compose.testing.yml"

run_deploy() {
  rm -f "$WRZDJ_FAKE_TOOL_LOG" "$WRZDJ_FAKE_UPGRADE_LOG"
  bash "$scratch/deploy/deploy-ghcr.sh" testing-sha-abc1234 > "$scratch/run.log" 2>&1
}

printf 'PORT_API=8001\nPORT_FRONTEND=3001\nWRZDJ_COMPOSE_OVERRIDE=docker-compose.testing.yml\n' \
  > "$scratch/deploy/.env"
run_deploy
for action in 'pull api web' 'down --remove-orphans' 'up -d' 'ps'; do
  grep -Fxq "docker compose -f $ghcr_file -f $override_file $action" "$WRZDJ_FAKE_TOOL_LOG" || {
    echo "compose '$action' did not receive both files:" >&2
    cat "$WRZDJ_FAKE_TOOL_LOG" >&2
    exit 1
  }
done
test "$(cat "$WRZDJ_FAKE_UPGRADE_LOG")" = "$ghcr_file $override_file"

printf 'PORT_API=8001\nPORT_FRONTEND=3001\nWRZDJ_COMPOSE_OVERRIDE=%s\n' "$override_file" \
  > "$scratch/deploy/.env"
run_deploy
grep -Fxq "docker compose -f $ghcr_file -f $override_file up -d" "$WRZDJ_FAKE_TOOL_LOG"

printf 'PORT_API=8001\nPORT_FRONTEND=3001\nWRZDJ_COMPOSE_OVERRIDE=does-not-exist.yml\n' \
  > "$scratch/deploy/.env"
if run_deploy; then
  echo 'a missing override file was ignored' >&2
  exit 1
fi
grep -Fq 'WRZDJ_COMPOSE_OVERRIDE points at a missing file' "$scratch/run.log"
test ! -e "$WRZDJ_FAKE_TOOL_LOG"
test ! -e "$WRZDJ_FAKE_UPGRADE_LOG"

printf 'PORT_API=8000\nPORT_FRONTEND=3000\n' > "$scratch/deploy/.env"
run_deploy
grep -Fxq "docker compose -f $ghcr_file up -d" "$WRZDJ_FAKE_TOOL_LOG"
test "$(cat "$WRZDJ_FAKE_UPGRADE_LOG")" = "$ghcr_file"
echo 'deploy-ghcr layers WRZDJ_COMPOSE_OVERRIDE onto every Compose call and refuses a missing one.'
