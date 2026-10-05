#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

# Automatic PostgreSQL major-version upgrade for the Compose data volume (#734).
# Usage: upgrade-postgres-volume.sh COMPOSE_FILE [COMPOSE_FILE...]
#
# Called by the deploy scripts before they stop anything. A compatible or empty
# volume is a no-op. A volume holding an older major version is migrated in
# place with the documented dump/restore method (pg_dumpall, so roles, grants,
# ownership and per-database settings come along):
#
#   1. Read-only checks while the current stack still serves.
#   2. Stop the stack; dump the whole cluster with the OLD server; copy the old
#      data files to the volume "<volume>_pg<major>_backup".
#   3. Write an in-progress marker, empty the volume, start the NEW server in a
#      throwaway container, restore, and compare every database's relation and
#      row counts and the role list with the old cluster. Only then is the
#      marker removed.
#
# Any failure before step 3 leaves the volume untouched; any failure in step 3
# copies the old files back. Either way the services that were running are
# started again. If the script is killed outright, the marker makes the next
# run (and check-postgres-volume.sh) see an interrupted upgrade and restore the
# old files before trying again. The backup volume and dump are never deleted
# on success.
#
# Environment: POSTGRES_UPGRADE_BACKUP_DIR (default deploy/backups),
#   POSTGRES_LEGACY_IMAGE (default postgres:<old major>-alpine).

: "${1:?Usage: upgrade-postgres-volume.sh COMPOSE_FILE [COMPOSE_FILE...]}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILES=("$@")
COMPOSE_ARGS=()
for file in "$@"; do COMPOSE_ARGS+=(-f "$file"); done

BACKUP_DIR="${POSTGRES_UPGRADE_BACKUP_DIR:-$SCRIPT_DIR/../backups}"
MARKER=.wrzdj-postgres-upgrade # keep in sync with check-postgres-volume.sh
# The digest-pinned image every earlier release shipped for PostgreSQL 16.
PG16_IMAGE=postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea

compose() { docker compose "${COMPOSE_ARGS[@]}" "$@"; }
die() {
  echo "ERROR: $*" >&2
  exit 1
}

# Runs a shell snippet in a throwaway container with volumes mounted by name.
on_volumes() { # SNIPPET MOUNT...
  local snippet=$1 mounts=()
  shift
  for mount in "$@"; do mounts+=(--volume "$mount"); done
  docker run --rm --network none "${mounts[@]}" --entrypoint sh "$LEGACY_IMAGE" -c "$snippet"
}

# Reads the volume name and credentials from a container created from the db
# service itself, so they are exactly what Compose resolves (project name,
# POSTGRES_VOLUME_NAME, deploy/.env), never a second guess from this shell.
read_service() {
  local id environment
  id=$(compose run --detach --no-deps --entrypoint sleep db 60)
  VOLUME=$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Name}}{{end}}{{end}}' "$id")
  environment=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$id")
  docker rm --force "$id" >/dev/null
  DB_USER=$(sed -n 's/^POSTGRES_USER=//p' <<<"$environment")
  DB_USER=${DB_USER:-postgres}
  DB_NAME=$(sed -n 's/^POSTGRES_DB=//p' <<<"$environment")
  DB_NAME=${DB_NAME:-$DB_USER}
  # An old Compose that cannot interpolate COMPOSE_PROJECT_NAME would yield
  # "_postgres_data": a brand-new empty volume instead of the real data.
  case "$VOLUME" in
    "" | _*) die "could not resolve the PostgreSQL data volume name (got '$VOLUME'); update Docker Compose" ;;
  esac
}

wait_for_server() { # CONTAINER
  local attempt
  for ((attempt = 0; attempt < 120; attempt++)); do
    # TCP, not the socket: the entrypoint's temporary init server is socket-only.
    if docker exec "$1" pg_isready --quiet --host 127.0.0.1 --username "$DB_USER"; then return 0; fi
    [ "$(docker inspect --format '{{.State.Running}}' "$1")" = true ] || break
    sleep 1
  done
  docker logs --tail 20 "$1" >&2 || true
  return 1
}

# Relation count and exact total row count of the connected database.
SUMMARY_SQL="SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_toast'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S'))
  || ' relations, ' ||
  (SELECT coalesce(sum((xpath('/row/c/text()', query_to_xml(
      format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint), 0)
    FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema'))
  || ' rows'"

# Prints what must survive the upgrade: every database with its owner, encoding
# and contents summary, and every role. Compared before and after.
cluster_state() { # CONTAINER
  local databases database summary
  databases=$(docker exec "$1" psql -U "$DB_USER" -d postgres -At -c \
    "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1")
  while IFS= read -r database; do
    summary=$(docker exec --env PGDATABASE="$database" "$1" psql -U "$DB_USER" -At -c "$SUMMARY_SQL" </dev/null)
    echo "database $database: $summary"
  done <<<"$databases"
  docker exec "$1" psql -U "$DB_USER" -d postgres -At -c \
    "SELECT 'database ' || datname || ' owner ' || pg_get_userbyid(datdba) || ' encoding ' ||
       pg_encoding_to_char(encoding) FROM pg_database WHERE NOT datistemplate ORDER BY 1"
  docker exec "$1" psql -U "$DB_USER" -d postgres -At -c \
    "SELECT 'role ' || rolname || ' super=' || rolsuper || ' login=' || rolcanlogin
       FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY 1"
}

# Step 2. Nothing here modifies the data volume.
dump_and_back_up() {
  docker run --detach --name "$LEGACY_CONTAINER" --network none \
    --volume "$VOLUME:/var/lib/postgresql/data" "$LEGACY_IMAGE" >/dev/null
  wait_for_server "$LEGACY_CONTAINER" || die "PostgreSQL $OLD_MAJOR did not start on the existing volume"
  cluster_state "$LEGACY_CONTAINER" >"$STATE_FILE"
  sed -n 's/^database \(.*: .*\)$/    \1/p' "$STATE_FILE"
  docker exec "$LEGACY_CONTAINER" pg_dumpall -U "$DB_USER" >"$DUMP_FILE"
  grep -q '^-- PostgreSQL database cluster dump complete' "$DUMP_FILE" || die "the dump is incomplete"
  docker stop "$LEGACY_CONTAINER" >/dev/null
  docker rm "$LEGACY_CONTAINER" >/dev/null

  docker volume create "$BACKUP_VOLUME" >/dev/null
  # shellcheck disable=SC2016 # expanded by the container's shell
  on_volumes 'cp -a /from/. /to/ && [ "$(find /from | wc -l)" = "$(find /to | wc -l)" ]' \
    "$VOLUME:/from:ro" "$BACKUP_VOLUME:/to" || die "could not copy the old data files"
}

# Step 3. The marker is written first and removed last.
replace_cluster() {
  local restored
  on_volumes "echo $OLD_MAJOR > /v/$MARKER && find /v -mindepth 1 ! -name $MARKER -delete" "$VOLUME:/v"
  compose run --detach --no-deps --name "$NEW_CONTAINER" db >/dev/null
  wait_for_server "$NEW_CONTAINER" || die "PostgreSQL $NEW_MAJOR did not start on the emptied volume"
  # The entrypoint pre-creates this database and role; the dump recreates the
  # database with its original owner, encoding and settings.
  if [ "$DB_NAME" != postgres ]; then
    docker exec "$NEW_CONTAINER" dropdb -U "$DB_USER" "$DB_NAME"
  fi
  echo "    Restoring into PostgreSQL $NEW_MAJOR..."
  # The entrypoint already created this role, so drop the dump's CREATE ROLE for
  # it. Only its first occurrence in the roles section (before any \connect)
  # is removed: table data that happens to contain the same text is untouched.
  awk -v statement="CREATE ROLE ${DB_USER};" '
      !past && $0 == statement { past = 1; next }
      /^\\connect / { past = 1 }
      { print }' "$DUMP_FILE" |
    docker exec --interactive "$NEW_CONTAINER" \
      psql -U "$DB_USER" -d postgres --quiet --set ON_ERROR_STOP=1 >/dev/null
  restored=$(cluster_state "$NEW_CONTAINER")
  if [ "$restored" != "$(cat "$STATE_FILE")" ]; then
    echo "ERROR: the restored cluster differs from the original:" >&2
    diff <(cat "$STATE_FILE") <(echo "$restored") >&2 || true
    return 1
  fi
  docker stop "$NEW_CONTAINER" >/dev/null
  docker rm "$NEW_CONTAINER" >/dev/null
  on_volumes "rm -f /v/$MARKER" "$VOLUME:/v"
}

# Copies the old data files back. Refuses to delete anything unless the backup
# volume exists and holds a cluster; the marker goes last, so an interrupted
# rollback is simply retried by the next run.
roll_back() {
  echo "    Restoring the PostgreSQL $OLD_MAJOR data files from $BACKUP_VOLUME..." >&2
  docker rm --force "$NEW_CONTAINER" "$LEGACY_CONTAINER" >/dev/null 2>&1 || true
  if ! docker volume inspect "$BACKUP_VOLUME" >/dev/null 2>&1; then
    echo "ERROR: backup volume '$BACKUP_VOLUME' does not exist; nothing was deleted." >&2
    return 1
  fi
  on_volumes "[ \"\$(cat /from/PG_VERSION 2>/dev/null)\" = $OLD_MAJOR ] &&
      find /to -mindepth 1 ! -name $MARKER -delete && cp -a /from/. /to/ &&
      [ \"\$(find /from | wc -l)\" = \"\$(find /to ! -name $MARKER | wc -l)\" ] &&
      rm -f /to/$MARKER" "$BACKUP_VOLUME:/from:ro" "$VOLUME:/to" || {
    echo "ERROR: could not restore automatically. The intact PostgreSQL $OLD_MAJOR files are in the" >&2
    echo "       Docker volume '$BACKUP_VOLUME'; the dump is in $BACKUP_DIR." >&2
    return 1
  }
  docker volume rm "$BACKUP_VOLUME" >/dev/null
  echo "       Restored. The volume is unchanged." >&2
}

restart_previous() {
  [ -n "$RUNNING" ] || return 0
  echo "    Starting the previously running services again..." >&2
  # shellcheck disable=SC2086 # one word per service name
  compose start $RUNNING >/dev/null || echo "WARNING: could not restart: $RUNNING" >&2
}

set_names() { # OLD_MAJOR
  OLD_MAJOR=$1
  [[ "$OLD_MAJOR" =~ ^[0-9]+$ ]] || die "unexpected PostgreSQL version '$OLD_MAJOR'"
  if [ "$OLD_MAJOR" = 16 ]; then
    LEGACY_IMAGE="${POSTGRES_LEGACY_IMAGE:-$PG16_IMAGE}"
  else
    LEGACY_IMAGE="${POSTGRES_LEGACY_IMAGE:-postgres:${OLD_MAJOR}-alpine}"
  fi
  BACKUP_VOLUME="${VOLUME}_pg${OLD_MAJOR}_backup"
  LEGACY_CONTAINER="${VOLUME}-pg${OLD_MAJOR}-upgrade-old"
  NEW_CONTAINER="${VOLUME}-pg${OLD_MAJOR}-upgrade-new"
  docker pull --quiet "$LEGACY_IMAGE" >/dev/null || die "could not pull $LEGACY_IMAGE"
}

# --- 1. Read-only checks; the current stack keeps serving ---------------------
read_service
STATUS=0
"$SCRIPT_DIR/check-postgres-volume.sh" "${COMPOSE_FILES[@]}" || STATUS=$?

if [ "$STATUS" -eq 4 ]; then
  # A previous run was killed mid-upgrade. Put the old files back, then go on.
  echo "==> Recovering from an interrupted PostgreSQL upgrade..."
  set_names "$(compose run --rm --no-deps -T --entrypoint cat db "/var/lib/postgresql/$MARKER")"
  compose stop db >/dev/null 2>&1 || true
  # Whatever is in the volume now may include data written after the
  # interruption (a database started by hand). Set it aside; never delete it.
  if [ -n "$(on_volumes "find /v -mindepth 1 ! -name $MARKER ! -type d | head -n 1" "$VOLUME:/v:ro")" ]; then
    INTERRUPTED_VOLUME="${VOLUME}_interrupted_$(date +%Y%m%d-%H%M%S)"
    docker volume create "$INTERRUPTED_VOLUME" >/dev/null
    # shellcheck disable=SC2016 # expanded by the container's shell
    on_volumes 'cp -a /from/. /to/ && [ "$(find /from | wc -l)" = "$(find /to | wc -l)" ]' \
      "$VOLUME:/from:ro" "$INTERRUPTED_VOLUME:/to" ||
      die "could not set aside the interrupted volume contents. Nothing was changed."
    echo "    The interrupted volume contents were kept in the Docker volume $INTERRUPTED_VOLUME"
  fi
  roll_back || exit 1
  STATUS=0
  "$SCRIPT_DIR/check-postgres-volume.sh" "${COMPOSE_FILES[@]}" || STATUS=$?
fi
[ "$STATUS" -ne 0 ] || exit 0
[ "$STATUS" -eq 3 ] || exit 1

set_names "$(compose run --rm --no-deps -T --entrypoint cat db /var/lib/postgresql/PG_VERSION)"
# shellcheck disable=SC2016 # expanded by the container's shell
NEW_MAJOR=$(compose run --rm --no-deps -T --entrypoint sh db -c 'echo "$PG_MAJOR"')

# Dumps hold password hashes and guest data: owner-only, like the data volume.
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
BACKUP_DIR=$(cd "$BACKUP_DIR" && pwd)
DUMP_FILE="$BACKUP_DIR/postgres${OLD_MAJOR}-$(date +%Y%m%d-%H%M%S)-cluster.sql"
STATE_FILE="$DUMP_FILE.state"

if docker volume inspect "$BACKUP_VOLUME" >/dev/null 2>&1; then
  die "backup volume '$BACKUP_VOLUME' already exists from an earlier upgrade. Nothing was changed.
       Remove it once it is no longer needed: docker volume rm $BACKUP_VOLUME"
fi
# The file copy needs the data's size again next to the volume (twice, so the
# restored cluster fits too), and the dump needs up to that size in BACKUP_DIR.
USED_KB=$(on_volumes 'du -sk /v | cut -f1' "$VOLUME:/v:ro")
# shellcheck disable=SC2016 # expanded by the container's shell
VOLUME_FREE_KB=$(on_volumes 'df -Pk /v | awk "NR==2 {print \$4}"' "$VOLUME:/v:ro")
DUMP_FREE_KB=$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')
[ "$VOLUME_FREE_KB" -gt $((USED_KB * 2)) ] && [ "$DUMP_FREE_KB" -gt "$USED_KB" ] ||
  die "not enough free disk space to upgrade safely (database: ${USED_KB} kB). Nothing was changed."

echo "==> Upgrading PostgreSQL $OLD_MAJOR -> $NEW_MAJOR (volume $VOLUME)..."
echo "    Old data files will be kept in the Docker volume $BACKUP_VOLUME"
echo "    The dump will be kept in $DUMP_FILE"

# --- 2. Stop the stack, dump, back up (the volume is not modified) ------------
RUNNING=$(compose ps --services --status running | tr '\n' ' ')
trap 'docker rm --force "$LEGACY_CONTAINER" "$NEW_CONTAINER" >/dev/null 2>&1 || true' EXIT
trap 'echo "Interrupted." >&2' INT TERM
compose stop >/dev/null
# Each step runs in a subshell at top level: errexit is fully active there, but
# is suppressed inside anything called from `if` or `||`.
set +e
(
  set -e
  dump_and_back_up
)
STEP=$?
set -e
if [ "$STEP" -ne 0 ]; then
  docker rm --force "$LEGACY_CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$BACKUP_VOLUME" >/dev/null 2>&1 || true
  echo "ERROR: the upgrade could not start. The data volume was not modified." >&2
  restart_previous
  exit 1
fi

# --- 3. Replace the cluster; any failure restores the old files ---------------
set +e
(
  set -e
  replace_cluster
)
STEP=$?
set -e
if [ "$STEP" -ne 0 ]; then
  echo "ERROR: the upgrade failed." >&2
  roll_back && restart_previous
  exit 1
fi

echo "==> PostgreSQL upgraded to $NEW_MAJOR."
echo "    Once you are satisfied, reclaim the space with: docker volume rm $BACKUP_VOLUME"
