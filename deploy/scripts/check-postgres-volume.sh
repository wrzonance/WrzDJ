#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL data-volume compatibility preflight (#734).
# Usage: ./deploy/scripts/check-postgres-volume.sh COMPOSE_FILE
#
# PostgreSQL cannot open another major version's data directory, and the
# PostgreSQL 18+ image stores data under /var/lib/postgresql/<major>/docker.
# The deploy scripts run this BEFORE stopping anything, so a volume that still
# holds an older major version aborts the deploy while the current stack keeps
# serving. It only reads the volume; it never modifies or removes data.
#
# Exit status: 0 = empty or matching volume, 1 = anything else (fails closed).

COMPOSE_FILE="${1:?Usage: check-postgres-volume.sh COMPOSE_FILE}"

# Runs in the db service's own image with its own volume mount, so custom
# project names and POSTGRES_VOLUME_NAME are honoured without re-deriving them.
# shellcheck disable=SC2016 # expanded by the container's shell, not this one
INSPECT='
root=/var/lib/postgresql
current="$root/$PG_MAJOR/docker"
if [ -s "$current/PG_VERSION" ] && [ "$(cat "$current/PG_VERSION")" = "$PG_MAJOR" ]; then
  exit 0
fi
found=0
for dir in "$root" "$root/data" "$root"/*/docker; do
  if [ -s "$dir/PG_VERSION" ]; then
    echo "PostgreSQL $(cat "$dir/PG_VERSION") data in $dir (this release needs PostgreSQL $PG_MAJOR)"
    found=1
  fi
done
# Fail closed: without a matching cluster, anything but empty directories is
# data this check cannot vouch for (damaged marker, partial init, foreign files).
if [ "$found" = 0 ] && [ -n "$(find "$root" -mindepth 1 ! -type d | head -n 1)" ]; then
  echo "unrecognised files and no valid PostgreSQL $PG_MAJOR data directory"
  found=1
fi
exit "$found"
'

if FOUND=$(docker compose -f "$COMPOSE_FILE" run --rm --no-deps -T --entrypoint sh db -c "$INSPECT"); then
  echo "    PostgreSQL data volume is compatible"
  exit 0
fi

if [ -z "$FOUND" ]; then
  echo "ERROR: could not inspect the PostgreSQL data volume (see the error above)." >&2
  exit 1
fi

cat >&2 <<EOF
ERROR: the PostgreSQL data volume is not usable by this release:
         $FOUND

       Nothing was stopped or changed. This release cannot open that data
       directly; migrate it with a dump/restore during a maintenance window.
       See "Upgrading PostgreSQL (16 -> 18)" in deploy/DEPLOYMENT.md.
EOF
exit 1
