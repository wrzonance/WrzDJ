#!/usr/bin/env bash
set -Eeuo pipefail # -E: the rollback ERR trap must also fire inside functions

# Automatic PostgreSQL major-version upgrade for the Compose data volume (#734).
# Usage: upgrade-postgres-volume.sh COMPOSE_FILE [COMPOSE_FILE...]
#
# Called by the deploy scripts before they stop anything. A compatible or empty
# volume is a no-op. A volume holding an older major version is migrated in
# place with a dump/restore:
#
#   1. Read-only checks while the current stack still serves (layout, free
#      space, no leftover backup). Any doubt aborts here with nothing changed.
#   2. Stop the stack, dump every database with the OLD server version.
#   3. Copy the old data files to a backup volume "<volume>_pg<major>_backup".
#   4. Empty the volume, start the new PostgreSQL on it, restore the dumps.
#
# If step 4 fails, the old files are copied back and the volume is exactly as
# it was. The backup volume and the dump files are never deleted on success.
#
# Environment: POSTGRES_USER (default wrzdj), POSTGRES_DB (default wrzdj),
#   POSTGRES_UPGRADE_BACKUP_DIR (default deploy/backups),
#   POSTGRES_LEGACY_IMAGE (default postgres:<old major>-alpine).

: "${1:?Usage: upgrade-postgres-volume.sh COMPOSE_FILE [COMPOSE_FILE...]}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILES=("$@")
COMPOSE_ARGS=()
for file in "$@"; do COMPOSE_ARGS+=(-f "$file"); done

DB_USER="${POSTGRES_USER:-wrzdj}"
DB_NAME="${POSTGRES_DB:-wrzdj}"
BACKUP_DIR="${POSTGRES_UPGRADE_BACKUP_DIR:-$SCRIPT_DIR/../backups}"
# The digest-pinned image every earlier release shipped for PostgreSQL 16.
PG16_IMAGE=postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea

DATABASES=()
declare -A SUMMARIES=()

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

# The real volume name, read from a container created from the db service, so
# project names and POSTGRES_VOLUME_NAME are honoured without re-deriving them.
resolve_volume() {
  local id name
  id=$(compose run --detach --no-deps --entrypoint sleep db 60)
  name=$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Name}}{{end}}{{end}}' "$id")
  docker rm --force "$id" >/dev/null
  [ -n "$name" ] || die "could not resolve the PostgreSQL data volume name"
  echo "$name"
}

wait_for_legacy_server() {
  local attempt
  for ((attempt = 0; attempt < 60; attempt++)); do
    if docker exec "$LEGACY_CONTAINER" pg_isready --quiet --username "$DB_USER"; then return 0; fi
    sleep 1
  done
  docker logs --tail 20 "$LEGACY_CONTAINER" >&2 || true
  return 1
}

# One line per database: relation count and exact total row count. Compared
# before and after, so a restore that silently lost anything is rolled back.
SUMMARY_SQL="SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_toast'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S'))
  || ' relations, ' ||
  (SELECT coalesce(sum((xpath('/row/c/text()', query_to_xml(
      format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint), 0)
    FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema'))
  || ' rows'"

# Dumps every user database with the old server. Sets DATABASES and SUMMARIES.
dump_databases() {
  docker run --detach --name "$LEGACY_CONTAINER" --network none \
    --volume "$VOLUME:/var/lib/postgresql/data" "$LEGACY_IMAGE" >/dev/null
  wait_for_legacy_server || die "PostgreSQL $OLD_MAJOR did not start on the existing volume"
  mapfile -t DATABASES < <(docker exec "$LEGACY_CONTAINER" psql -U "$DB_USER" -d postgres -At -c \
    "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1")
  [ "${#DATABASES[@]}" -gt 0 ] || die "no databases found to migrate"
  local database
  for database in "${DATABASES[@]}"; do
    SUMMARIES[$database]=$(docker exec "$LEGACY_CONTAINER" \
      psql -U "$DB_USER" -d "$database" -At -c "$SUMMARY_SQL" </dev/null)
    echo "    Dumping database '$database' (${SUMMARIES[$database]})..."
    docker exec "$LEGACY_CONTAINER" pg_dump -U "$DB_USER" -Fc "$database" \
      >"$DUMP_PREFIX-$database.dump" </dev/null
    [ -s "$DUMP_PREFIX-$database.dump" ] || die "the dump of '$database' is empty"
  done
  docker stop "$LEGACY_CONTAINER" >/dev/null
  docker rm "$LEGACY_CONTAINER" >/dev/null
}

# Restores every dump, then proves each database matches what was dumped.
restore_databases() {
  local database restored
  compose up --detach --wait --wait-timeout 180 db
  for database in "${DATABASES[@]}"; do
    echo "    Restoring database '$database'..."
    if [ "$database" != "$DB_NAME" ]; then
      compose exec -T db createdb -U "$DB_USER" "$database" </dev/null
    fi
    compose exec -T db pg_restore -U "$DB_USER" -d "$database" --no-owner --exit-on-error \
      <"$DUMP_PREFIX-$database.dump"
    restored=$(compose exec -T db psql -U "$DB_USER" -d "$database" -At -c "$SUMMARY_SQL" </dev/null)
    if [ "$restored" != "${SUMMARIES[$database]}" ]; then
      echo "ERROR: '$database' has $restored after restore, expected ${SUMMARIES[$database]}" >&2
      return 1
    fi
  done
}

# Puts the old data files back so the previous release can start unchanged.
roll_back() {
  echo "ERROR: the upgrade failed; restoring the PostgreSQL $OLD_MAJOR data files..." >&2
  compose rm --stop --force db >/dev/null 2>&1 || true
  # shellcheck disable=SC2016 # expanded by the container's shell
  if on_volumes 'find /to -mindepth 1 -delete && cp -a /from/. /to/ &&
      [ "$(find /from | wc -l)" = "$(find /to | wc -l)" ]' "$BACKUP_VOLUME:/from:ro" "$VOLUME:/to"; then
    docker volume rm "$BACKUP_VOLUME" >/dev/null
    echo "       Restored. The volume is unchanged; the previous release can be redeployed." >&2
    echo "       Dumps were kept in $BACKUP_DIR." >&2
  else
    echo "       COULD NOT restore automatically. The intact PostgreSQL $OLD_MAJOR files are in" >&2
    echo "       the Docker volume '$BACKUP_VOLUME'; dumps are in $BACKUP_DIR." >&2
  fi
}

# --- 1. Read-only checks; the current stack keeps serving ---------------------
STATUS=0
"$SCRIPT_DIR/check-postgres-volume.sh" "${COMPOSE_FILES[@]}" || STATUS=$?
[ "$STATUS" -ne 0 ] || exit 0
[ "$STATUS" -eq 3 ] || exit 1

OLD_MAJOR=$(compose run --rm --no-deps -T --entrypoint cat db /var/lib/postgresql/PG_VERSION)
# shellcheck disable=SC2016 # expanded by the container's shell
NEW_MAJOR=$(compose run --rm --no-deps -T --entrypoint sh db -c 'echo "$PG_MAJOR"')
if [ "$OLD_MAJOR" = 16 ]; then
  LEGACY_IMAGE="${POSTGRES_LEGACY_IMAGE:-$PG16_IMAGE}"
else
  LEGACY_IMAGE="${POSTGRES_LEGACY_IMAGE:-postgres:${OLD_MAJOR}-alpine}"
fi
VOLUME=$(resolve_volume)
BACKUP_VOLUME="${VOLUME}_pg${OLD_MAJOR}_backup"
LEGACY_CONTAINER="${VOLUME}-pg${OLD_MAJOR}-upgrade"
mkdir -p "$BACKUP_DIR"
DUMP_PREFIX="$(cd "$BACKUP_DIR" && pwd)/postgres${OLD_MAJOR}-$(date +%Y%m%d-%H%M%S)"

docker pull --quiet "$LEGACY_IMAGE" >/dev/null || die "could not pull $LEGACY_IMAGE"
if docker volume inspect "$BACKUP_VOLUME" >/dev/null 2>&1; then
  die "backup volume '$BACKUP_VOLUME' already exists from an earlier upgrade. Nothing was changed.
       Remove it once it is no longer needed: docker volume rm $BACKUP_VOLUME"
fi
# The file copy needs the data's size again on the same filesystem; require
# double that so the restored cluster fits too.
# shellcheck disable=SC2016 # expanded by the container's shell
on_volumes 'used=$(du -sk /v | cut -f1); free=$(df -Pk /v | awk "NR==2 {print \$4}")
  [ "$free" -gt $((used * 2)) ]' "$VOLUME:/v:ro" ||
  die "not enough free disk space to upgrade safely (need twice the database size). Nothing was changed."

echo "==> Upgrading PostgreSQL $OLD_MAJOR -> $NEW_MAJOR (volume $VOLUME)..."
echo "    Old data files will be kept in the Docker volume $BACKUP_VOLUME"
echo "    Dumps will be kept in $BACKUP_DIR"

# --- 2. Stop the stack and dump with the old server ---------------------------
trap 'docker rm --force "$LEGACY_CONTAINER" >/dev/null 2>&1 || true' EXIT
compose stop >/dev/null
dump_databases

# --- 3. Keep the old data files ------------------------------------------------
docker volume create "$BACKUP_VOLUME" >/dev/null
# shellcheck disable=SC2016 # expanded by the container's shell
on_volumes 'cp -a /from/. /to/ && [ "$(find /from | wc -l)" = "$(find /to | wc -l)" ]' \
  "$VOLUME:/from:ro" "$BACKUP_VOLUME:/to" || {
  docker volume rm "$BACKUP_VOLUME" >/dev/null || true
  die "could not copy the old data files. The volume is unchanged."
}

# --- 4. Replace the cluster; any failure from here restores the old files ------
trap roll_back ERR
on_volumes 'find /v -mindepth 1 -delete' "$VOLUME:/v"
restore_databases
trap - ERR

echo "==> PostgreSQL upgraded to $NEW_MAJOR."
echo "    Once you are satisfied, reclaim the space with: docker volume rm $BACKUP_VOLUME"
