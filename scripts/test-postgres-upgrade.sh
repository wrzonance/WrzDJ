#!/usr/bin/env bash
# Regression for #734: the PostgreSQL 18 image moved PGDATA to
# /var/lib/postgresql/18/docker, so a tag-only bump silently abandons (or fails
# on) an existing PostgreSQL 16 volume. Proves, with owned ephemeral resources:
#   1. Compose volume names stay correct for default/custom projects + override.
#   2. Legacy PostgreSQL 16 data is rejected before teardown and left untouched.
#   3. PostgreSQL 16 can still read that volume afterwards (rollback path).
#   4. A failed automatic upgrade puts the PostgreSQL 16 files back.
#   5. An upgrade killed mid-way is recovered by the next run.
#   6. The automatic upgrade the deploy scripts run preserves the whole cluster
#      (databases, roles, ownership), keeps the old files in a backup volume,
#      and the API starts on the result.
# shellcheck disable=SC2016 # snippets below are expanded inside containers
set -euo pipefail

image=${1:?Usage: test-postgres-upgrade.sh API_IMAGE}
root=$(cd "$(dirname "$0")/.." && pwd)
legacy_image=postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea
compose_file="$root/deploy/docker-compose.yml"
check="$root/deploy/scripts/check-postgres-volume.sh"
upgrade="$root/deploy/scripts/upgrade-postgres-volume.sh"

scratch=$(mktemp -d)
project="wrzdj-pgup-$(basename "$scratch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')"
legacy_volume="${project}_postgres_data"
backup_volume="${legacy_volume}_pg16_backup"
probe_volume="${project}_probe"
legacy_network="${project}-legacy"
legacy_db="${project}-legacy-db"
legacy_api="${project}-legacy-api"
restored_api="${project}-restored-api"

# Dummy values for every required variable in the production Compose files.
export COMPOSE_PROJECT_NAME="$project"
export POSTGRES_USER=wrzdj POSTGRES_PASSWORD=wrzdj POSTGRES_DB=wrzdj
export JWT_SECRET=test-secret-key TOKEN_ENCRYPTION_KEY=unused HUMAN_COOKIE_SECRET=unused
export CORS_ORIGINS=http://localhost:3000 PUBLIC_URL=http://localhost:3000
export NEXT_PUBLIC_API_URL=http://localhost:8000
unset POSTGRES_VOLUME_NAME

compose() { docker compose -f "$compose_file" "$@"; }

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    for id in "$legacy_api" "$restored_api" "$legacy_db"; do
      docker logs --tail 40 "$id" >&2 2>/dev/null || true
    done
    compose logs --tail 40 db >&2 2>/dev/null || true
  fi
  docker rm --force "$legacy_api" "$restored_api" "$legacy_db" >/dev/null 2>&1 || true
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  POSTGRES_VOLUME_NAME="$probe_volume" compose down --remove-orphans >/dev/null 2>&1 || true
  docker rm --force "${legacy_volume}-pg16-upgrade-old" "${legacy_volume}-pg16-upgrade-new" >/dev/null 2>&1 || true
  docker volume ls --quiet --filter "name=${legacy_volume}_interrupted_" | xargs -r docker volume rm >/dev/null 2>&1 || true
  docker volume rm "$legacy_volume" "$backup_volume" "$probe_volume" >/dev/null 2>&1 || true
  docker network rm "$legacy_network" >/dev/null 2>&1 || true
  rm -rf "$scratch"
  exit "$status"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# --- 1. Compose volume naming and mount target --------------------------------
volume_name() { # FILE [compose args...]
  local file=$1
  shift
  docker compose -f "$file" "$@" config --format json | jq -r '.volumes.postgres_data.name'
}
for file in "$root/docker-compose.yml" "$compose_file" "$root/deploy/docker-compose.ghcr.yml"; do
  target=$(docker compose -f "$file" config --format json |
    jq -r '.services.db.volumes[] | select(.source == "postgres_data") | .target')
  [ "$target" = /var/lib/postgresql ] || fail "$file mounts postgres_data at '$target'"

  [ "$(volume_name "$file")" = "$legacy_volume" ] ||
    fail "$file: COMPOSE_PROJECT_NAME volume name is $(volume_name "$file")"
  [ "$(volume_name "$file" -p custom-project)" = custom-project_postgres_data ] ||
    fail "$file: -p custom-project volume name is $(volume_name "$file" -p custom-project)"
  # No project name at all: Compose derives it from the directory, and the
  # volume must keep the historical "<project>_postgres_data" name.
  default_project=$(env -u COMPOSE_PROJECT_NAME docker compose -f "$file" config --format json | jq -r .name)
  default_volume=$(env -u COMPOSE_PROJECT_NAME docker compose -f "$file" config --format json |
    jq -r '.volumes.postgres_data.name')
  [ "$default_volume" = "${default_project}_postgres_data" ] ||
    fail "$file: default volume name is $default_volume"
  [ "$(POSTGRES_VOLUME_NAME=explicit-volume volume_name "$file")" = explicit-volume ] ||
    fail "$file: POSTGRES_VOLUME_NAME override was ignored"
done
echo 'Compose volume names and mount targets are correct.'

# Both deploy scripts must run the volume check/upgrade before their first Compose command
# (pull/down), or an incompatible volume would be discovered after teardown.
for script in "$root/deploy/deploy.sh" "$root/deploy/deploy-ghcr.sh"; do
  first=$(grep -v '^[[:space:]]*#' "$script" | grep -m1 -E 'upgrade-postgres-volume\.sh|docker compose')
  grep -q 'upgrade-postgres-volume\.sh' <<<"$first" ||
    fail "$script touches the stack before the volume upgrade: $first"
done

# --- helpers ------------------------------------------------------------------
wait_ready() { # CONTAINER
  for ((attempt = 0; attempt < 60; attempt++)); do
    # TCP, not the socket: the entrypoint's temporary init server is socket-only.
    if docker exec "$1" pg_isready --quiet --host 127.0.0.1 --username wrzdj; then return 0; fi
    sleep 1
  done
  fail "$1 did not accept connections"
}

wait_api() { # CONTAINER
  for ((attempt = 0; attempt < 90; attempt++)); do
    if docker exec "$1" curl --fail --silent --max-time 2 http://127.0.0.1:8000/health >/dev/null; then
      return 0
    fi
    [ "$(docker inspect --format '{{.State.Running}}' "$1")" = true ] || break
    sleep 1
  done
  fail "$1 did not become healthy"
}

fingerprint_sql="SELECT 'rev', version_num FROM alembic_version
  UNION ALL SELECT 'tables', count(*)::text FROM information_schema.tables WHERE table_schema = 'public'
  UNION ALL SELECT 'user', username || ':' || password_hash FROM users
  ORDER BY 1, 2"

start_legacy_db() { # [VOLUME]
  docker run --detach --name "$legacy_db" --network "$legacy_network" --network-alias legacy-db \
    --env POSTGRES_USER=wrzdj --env POSTGRES_PASSWORD=wrzdj --env POSTGRES_DB=wrzdj \
    --volume "${1:-$legacy_volume}:/var/lib/postgresql/data" "$legacy_image" >/dev/null
  wait_ready "$legacy_db"
}

legacy_volume_holds() { # SHELL_TEST DESCRIPTION
  docker run --rm --network none --volume "$legacy_volume:/v:ro" --entrypoint sh "$legacy_image" \
    -c "$1" || fail "$2"
}

# --- 1b. The preflight fails closed on anything it cannot vouch for -------------
preflight_status() { # SETUP_SNIPPET -> the preflight's exit status on a scratch volume
  local status=0
  docker volume rm "$probe_volume" >/dev/null 2>&1 || true
  docker volume create "$probe_volume" >/dev/null
  docker run --rm --network none --volume "$probe_volume:/v" --entrypoint sh "$legacy_image" -c "$1"
  POSTGRES_VOLUME_NAME="$probe_volume" bash "$check" "$compose_file" >/dev/null 2>&1 || status=$?
  echo "$status"
}
expect_preflight() { # EXPECTED_STATUS SETUP_SNIPPET DESCRIPTION
  local status
  status=$(preflight_status "$2")
  [ "$status" = "$1" ] || fail "the preflight returned $status, not $1, for $3"
}
expect_preflight 0 'mkdir -p /v/18/docker' 'a volume holding only an empty 18/docker directory'
expect_preflight 1 'mkdir -p /v/18/docker && echo 16 > /v/18/docker/PG_VERSION' \
  'PostgreSQL 16 data placed under 18/docker'
expect_preflight 1 'mkdir -p /v/base && echo data > /v/base/1' \
  'a non-empty volume with no PG_VERSION marker'
expect_preflight 1 'mkdir -p /v/18/docker/base && echo data > /v/18/docker/base/1' \
  'a half-initialised PostgreSQL 18 directory'
expect_preflight 1 'echo 16 > /v/PG_VERSION && mkdir -p /v/17/docker && echo 17 > /v/17/docker/PG_VERSION' \
  'two clusters in one volume'
# Regression: an upgrade killed after it emptied the volume left a state the
# preflight accepted (empty, or a partially restored PostgreSQL 18 cluster).
expect_preflight 4 'echo 16 > /v/.wrzdj-postgres-upgrade' 'an interrupted upgrade (emptied volume)'
expect_preflight 4 'echo 16 > /v/.wrzdj-postgres-upgrade && mkdir -p /v/18/docker && echo 18 > /v/18/docker/PG_VERSION' \
  'an interrupted upgrade (partially restored cluster)'
docker volume rm "$probe_volume" >/dev/null
echo 'The preflight fails closed on unrecognised volume contents.'

# --- 2. Build a real PostgreSQL 16 deployment volume --------------------------
docker network create --internal "$legacy_network" >/dev/null
docker volume create "$legacy_volume" >/dev/null
start_legacy_db
docker run --detach --name "$legacy_api" --network "$legacy_network" \
  --env DATABASE_URL=postgresql+psycopg://wrzdj:wrzdj@legacy-db:5432/wrzdj \
  --env JWT_SECRET=test-secret-key --env ENV=development \
  --env BOOTSTRAP_ADMIN_USERNAME=upgradeadmin --env BOOTSTRAP_ADMIN_PASSWORD=Upgrade-Test-Passw0rd \
  "$image" >/dev/null
wait_api "$legacy_api"
docker rm --force "$legacy_api" >/dev/null
# A second database: real clusters hold more than the application database, and
# the upgrade must carry every one of them (regression: it stopped after one).
docker exec "$legacy_db" createdb -U wrzdj side_database
docker exec "$legacy_db" psql -U wrzdj -d side_database -q -c \
  "CREATE TABLE notes (body text); INSERT INTO notes VALUES ('kept')"
# Regression for 931affae: the restore dropped every dump line equal to
# "CREATE ROLE <user>;", including table data that happened to contain it.
docker exec "$legacy_db" psql -U wrzdj -d side_database -q -c \
  "CREATE TABLE tricky (body text); INSERT INTO tricky VALUES ('CREATE ROLE wrzdj;'), (E'first\nCREATE ROLE wrzdj;\nlast')"
tricky_before=$(docker exec "$legacy_db" psql -U wrzdj -d side_database -At -c \
  "SELECT md5(string_agg(body, '|' ORDER BY body)) FROM tricky")
# Cluster-level state a per-database dump would lose: a second role that owns
# a database and a table (regression: roles, ownership and grants were dropped).
docker exec "$legacy_db" psql -U wrzdj -d postgres -q -c \
  "CREATE ROLE reporter LOGIN PASSWORD 'reporter-secret'" -c "CREATE DATABASE reports OWNER reporter"
docker exec "$legacy_db" psql -U wrzdj -d reports -q -c \
  "SET ROLE reporter; CREATE TABLE figures (n int); INSERT INTO figures VALUES (42)"
# Data in the default database must come along too.
docker exec "$legacy_db" psql -U wrzdj -d postgres -q -c \
  "CREATE TABLE in_default_db (n int); INSERT INTO in_default_db VALUES (7)"
before=$(docker exec "$legacy_db" psql -U wrzdj -d wrzdj -At -c "$fingerprint_sql")
grep -q '^user|upgradeadmin:' <<<"$before" || fail 'no application data was seeded'

# --- 3. Legacy data is rejected before teardown, and left untouched -----------
# The old database is still running here, exactly as it is when a deploy starts.
status=0
output=$(bash "$check" "$compose_file" 2>&1) || status=$?
[ "$status" = 3 ] || fail "the preflight returned $status, not 3 (upgradeable), for PostgreSQL 16: $output"
grep -q 'PostgreSQL 16' <<<"$output" || fail "the preflight did not name the old version: $output"
[ "$(docker inspect --format '{{.State.Running}}' "$legacy_db")" = true ] ||
  fail 'the preflight stopped the running database'
docker stop "$legacy_db" >/dev/null
docker rm "$legacy_db" >/dev/null
legacy_volume_holds '[ "$(cat /v/PG_VERSION)" = 16 ] && [ ! -e /v/18 ]' \
  'the preflight modified the legacy volume'

# Without the deploy scripts (plain `docker compose up`), the image itself must
# refuse rather than initialise an empty PostgreSQL 18 cluster beside the data.
if output=$(timeout 120 docker compose -f "$compose_file" run --rm --no-deps -T db 2>&1); then
  fail 'PostgreSQL 18 started on a PostgreSQL 16 volume'
fi
grep -q 'in 18+' <<<"$output" || fail "unexpected PostgreSQL 18 refusal: $output"
# The image creates its (empty) 18/docker directory before refusing; it must
# never initialise a cluster there or touch the PostgreSQL 16 files.
legacy_volume_holds '[ "$(cat /v/PG_VERSION)" = 16 ] && [ -z "$(ls -A /v/18/docker 2>/dev/null)" ]' \
  'PostgreSQL 18 wrote into the legacy volume'
echo 'Legacy PostgreSQL 16 data is rejected and left untouched.'

# --- 4. A failed upgrade restores the PostgreSQL 16 files ----------------------
export POSTGRES_UPGRADE_BACKUP_DIR="$scratch/backups"
cat >"$scratch/broken-db.yml" <<'YAML'
services:
  db:
    entrypoint: ["false"]
YAML
if bash "$upgrade" "$compose_file" "$scratch/broken-db.yml" >"$scratch/failed-upgrade.log" 2>&1; then
  fail 'the upgrade reported success although the new database could not start'
fi
grep -q 'Restored' "$scratch/failed-upgrade.log" ||
  fail "the failed upgrade did not roll back: $(cat "$scratch/failed-upgrade.log")"
if docker volume inspect "$backup_volume" >/dev/null 2>&1; then
  fail 'a rolled-back upgrade left its backup volume behind'
fi
compose rm --stop --force db >/dev/null 2>&1 || true
start_legacy_db
[ "$(docker exec "$legacy_db" psql -U wrzdj -d wrzdj -At -c "$fingerprint_sql")" = "$before" ] ||
  fail 'PostgreSQL 16 no longer reads the volume identically after a rolled-back upgrade'
docker stop "$legacy_db" >/dev/null
docker rm "$legacy_db" >/dev/null
echo 'A failed upgrade restores the PostgreSQL 16 data files.'

# --- 5. An upgrade killed mid-way is recovered by the next run -----------------
# Reproduce the state a kill leaves behind: old files copied to the backup
# volume, marker written, data volume emptied, a stray new cluster started.
docker volume create "$backup_volume" >/dev/null
docker run --rm --network none --volume "$legacy_volume:/from" --volume "$backup_volume:/to" \
  --entrypoint sh "$legacy_image" -c 'cp -a /from/. /to/ && echo 16 > /from/.wrzdj-postgres-upgrade &&
    find /from -mindepth 1 ! -name .wrzdj-postgres-upgrade -delete &&
    mkdir -p /from/18/docker && echo 18 > /from/18/docker/PG_VERSION &&
    echo written-after-the-interruption > /from/18/docker/stray-data'

# --- 6. The automatic upgrade preserves the whole cluster ----------------------
bash "$upgrade" "$compose_file" >"$scratch/upgrade.log" 2>&1 ||
  fail "the automatic upgrade failed: $(cat "$scratch/upgrade.log")"
grep -q 'Recovering from an interrupted' "$scratch/upgrade.log" ||
  fail 'the upgrade did not recover the interrupted state first'
# Regression for 931affae: recovery deleted whatever it found in the volume.
# Anything written after the interruption must be set aside, not destroyed.
interrupted_volume=$(docker volume ls --quiet --filter "name=${legacy_volume}_interrupted_" | head -n 1)
[ -n "$interrupted_volume" ] || fail 'recovery did not keep the interrupted volume contents'
docker run --rm --network none --volume "$interrupted_volume:/v:ro" --entrypoint sh "$legacy_image" \
  -c '[ "$(cat /v/18/docker/stray-data)" = written-after-the-interruption ]' ||
  fail 'recovery lost data written after the interruption'
compose up --detach --wait db >/dev/null 2>&1 || fail 'PostgreSQL 18 did not start on the upgraded volume'
query() { compose exec -T db psql -U wrzdj -d "$1" -At -c "$2"; } # DATABASE SQL
after=$(query wrzdj "$fingerprint_sql")
[ "$after" = "$before" ] || fail "upgraded data differs:
--- PostgreSQL 16
$before
--- PostgreSQL 18
$after"
[ "$(query wrzdj 'SHOW server_version_num' | cut -c1-2)" = 18 ] || fail 'the upgraded database is not PostgreSQL 18'
[ "$(query side_database 'SELECT body FROM notes')" = kept ] ||
  fail 'the upgrade lost a database other than the application database'
[ "$(query side_database "SELECT md5(string_agg(body, '|' ORDER BY body)) FROM tricky")" = "$tricky_before" ] ||
  fail 'the upgrade altered table data that looks like a CREATE ROLE statement'
[ "$(query postgres 'SELECT n FROM in_default_db')" = 7 ] || fail 'the upgrade lost data in the default database'
[ "$(query reports "SELECT tableowner || ':' || (SELECT n FROM figures) FROM pg_tables WHERE tablename = 'figures'")" = reporter:42 ] ||
  fail 'the upgrade lost table ownership'
[ "$(query postgres "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'reports'")" = reporter ] ||
  fail 'the upgrade lost database ownership'
[ "$(query postgres "SELECT rolcanlogin AND rolpassword IS NOT NULL FROM pg_authid WHERE rolname = 'reporter'")" = t ] ||
  fail 'the upgrade lost a role or its password'
dump=$(find "$scratch/backups" -name 'postgres16-*-cluster.sql' | sort | tail -n 1)
[ -s "$dump" ] || fail 'the upgrade did not keep a dump of the cluster'
# Regression for d20a6403: dumps (password hashes, guest data) were world-readable.
[ -z "$(find "$scratch/backups" -perm /077)" ] ||
  fail "upgrade dumps are readable by other users: $(find "$scratch/backups" -perm /077 | head -n 3)"

docker run --detach --name "$restored_api" --network "${project}_default" \
  --env DATABASE_URL=postgresql+psycopg://wrzdj:wrzdj@db:5432/wrzdj \
  --env JWT_SECRET=test-secret-key --env ENV=development "$image" >/dev/null
wait_api "$restored_api"
[ "$(query wrzdj "$fingerprint_sql")" = "$before" ] || fail 'API startup changed the upgraded data'

# Redeploys are a no-op (with the database running, as in a real deploy), and
# the kept backup is a working PostgreSQL 16 cluster.
bash "$upgrade" "$compose_file" >/dev/null 2>&1 || fail 'a second run on the upgraded volume failed'
[ "$(query wrzdj "$fingerprint_sql")" = "$before" ] || fail 'a second run changed the upgraded data'
start_legacy_db "$backup_volume"
[ "$(docker exec "$legacy_db" psql -U wrzdj -d wrzdj -At -c "$fingerprint_sql")" = "$before" ] ||
  fail 'the backup volume is not a readable copy of the PostgreSQL 16 data'
echo 'The automatic upgrade recovers an interrupted run, preserves the cluster and keeps a working backup.'
