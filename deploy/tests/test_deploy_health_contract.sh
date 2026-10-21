#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin"

cat > "$scratch/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WRZDJ_DOCKER_CALLS"
if [ "$1" = compose ]; then
  shift
  command_line="$*"
  case "$command_line" in
    *'run --detach'*'--entrypoint sleep'*) echo fake-db ;;
    *'run --rm'*'--entrypoint sh'*) echo 'PostgreSQL data volume is compatible' ;;
    *) ;;
  esac
  exit 0
fi
case "${1:-}" in
  inspect)
    if [[ "$*" == *'.Mounts'* ]]; then echo test_postgres_data
    else printf '%s\n' 'POSTGRES_USER=wrzdj' 'POSTGRES_DB=wrzdj'; fi
    ;;
  volume) exit 1 ;;
  *) ;;
esac
DOCKER
cat > "$scratch/bin/curl" <<'CURL'
#!/usr/bin/env bash
[ "${WRZDJ_TEST_API_HEALTHY:-0}" = 1 ]
CURL
cat > "$scratch/bin/ss" <<'SS'
#!/usr/bin/env bash
:
SS
cat > "$scratch/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
:
SLEEP
cat > "$scratch/bin/chown" <<'NOOP'
#!/usr/bin/env bash
printf 'chown %s\n' "$*" >> "$WRZDJ_PERMISSION_CALLS"
NOOP
cat > "$scratch/bin/chmod" <<'NOOP'
#!/usr/bin/env bash
printf 'chmod %s\n' "$*" >> "$WRZDJ_PERMISSION_CALLS"
NOOP
cat > "$scratch/bin/mkdir" <<'NOOP'
#!/usr/bin/env bash
:
NOOP
chmod +x "$scratch/bin"/*
export PATH="$scratch/bin:$PATH"
export WRZDJ_DOCKER_CALLS="$scratch/docker.log"
export WRZDJ_PERMISSION_CALLS="$scratch/permissions.log"

for script in deploy.sh deploy-ghcr.sh; do
  if [ "$script" = deploy.sh ]; then
    args=(unexpected)
  else
    args=(stable unexpected)
  fi
  status=0
  WRZDJ_API_HEALTH_TIMEOUT=1 bash "$repo_root/deploy/$script" "${args[@]}" \
    >"$scratch/invalid-args-$script.log" 2>&1 || status=$?
  if [ "$status" -ne 2 ]; then
    echo "$script did not reject extra positional arguments with usage status" >&2
    cat "$scratch/invalid-args-$script.log" >&2
    exit 1
  fi
  grep -Fq 'Usage:' "$scratch/invalid-args-$script.log"
done
test ! -s "$WRZDJ_DOCKER_CALLS"

for script in deploy.sh deploy-ghcr.sh; do
  if WRZDJ_API_HEALTH_TIMEOUT=1 WRZDJ_TEST_API_HEALTHY=0 bash "$repo_root/deploy/$script" >"$scratch/$script.log" 2>&1; then
    echo "$script reported success although the API health check never passed" >&2
    cat "$scratch/$script.log" >&2
    exit 1
  fi
  if grep -Fq 'Deploy complete' "$scratch/$script.log"; then
    echo "$script printed Deploy complete after the API health timeout" >&2
    exit 1
  fi
done

for script in deploy.sh deploy-ghcr.sh; do
  WRZDJ_API_HEALTH_TIMEOUT=1 WRZDJ_TEST_API_HEALTHY=1 bash "$repo_root/deploy/$script" >"$scratch/healthy-$script.log" 2>&1
  grep -Fq 'Deploy complete' "$scratch/healthy-$script.log"
  if grep -Fq 'Verifying uploads directory structure' "$scratch/healthy-$script.log" || \
    grep -Fxq 'volume inspect api_uploads' "$WRZDJ_DOCKER_CALLS"; then
    echo "$script retained the no-op uploads verification stage" >&2
    exit 1
  fi
  grep -Fxq "chown $(id -u):1000 $repo_root/deploy/logs/api" "$WRZDJ_PERMISSION_CALLS"
  grep -Fxq "chmod 775 $repo_root/deploy/logs/api" "$WRZDJ_PERMISSION_CALLS"
  : > "$WRZDJ_PERMISSION_CALLS"
done

echo 'Both deploy entrypoints fail on API health timeout and succeed after health passes.'
