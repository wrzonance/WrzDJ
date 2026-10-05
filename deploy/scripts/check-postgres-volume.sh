#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL data-volume compatibility preflight (#734).
# PostgreSQL cannot open another major version's data directory, and the
# PostgreSQL 18+ image stores data under /var/lib/postgresql/<major>/docker.
# The deploy scripts run this BEFORE stopping anything, so a volume that still
# holds an older major version aborts the deploy while the current stack keeps
# serving. It only reads the volume; it never modifies or removes data.
#
# Exit status: 0 = empty or matching volume
#              3 = an older major version in the pre-18 layout, which
#                  upgrade-postgres-volume.sh can migrate automatically
#              4 = an upgrade was interrupted part-way; upgrade-postgres-volume.sh
#                  restores the old data files and retries
#              1 = anything else (fails closed)
#
# Usage: check-postgres-volume.sh COMPOSE_FILE [COMPOSE_FILE...]

: "${1:?Usage: check-postgres-volume.sh COMPOSE_FILE [COMPOSE_FILE...]}"
COMPOSE_ARGS=()
for file in "$@"; do COMPOSE_ARGS+=(-f "$file"); done

# Runs in the db service's own image with its own volume mount, so custom
# project names and POSTGRES_VOLUME_NAME are honoured without re-deriving them.
# shellcheck disable=SC2016 # expanded by the container's shell, not this one
INSPECT='
root=/var/lib/postgresql
# Written before an upgrade empties the volume and removed only after the
# restored cluster is verified (keep in sync with upgrade-postgres-volume.sh).
if [ -e "$root/.wrzdj-postgres-upgrade" ]; then
  echo "an interrupted upgrade from PostgreSQL $(cat "$root/.wrzdj-postgres-upgrade")"
  exit 4
fi
current="$root/$PG_MAJOR/docker"
if [ -s "$current/PG_VERSION" ] && [ "$(cat "$current/PG_VERSION")" = "$PG_MAJOR" ]; then
  exit 0
fi
found=0
for dir in "$root" "$root/data" "$root"/*/docker; do
  if [ -s "$dir/PG_VERSION" ]; then
    echo "PostgreSQL $(cat "$dir/PG_VERSION") data in $dir (this release needs PostgreSQL $PG_MAJOR)"
    found=$((found + 1))
  fi
done
# Exactly one older cluster at the volume root is the layout every earlier
# release created, and the only one the automatic upgrade handles.
legacy=$(cat "$root/PG_VERSION" 2>/dev/null || true)
if [ "$found" = 1 ] && [ "$legacy" -lt "$PG_MAJOR" ] 2>/dev/null; then
  exit 3
fi
# Fail closed: without a matching cluster, anything but empty directories is
# data this check cannot vouch for (damaged marker, partial init, foreign files).
if [ "$found" = 0 ] && [ -z "$(find "$root" -mindepth 1 ! -type d | head -n 1)" ]; then
  exit 0
fi
[ "$found" != 0 ] || echo "unrecognised files and no valid PostgreSQL $PG_MAJOR data directory"
exit 1
'

STATUS=0
FOUND=$(docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps -T --entrypoint sh db -c "$INSPECT") || STATUS=$?

case "$STATUS" in
  0)
    echo "    PostgreSQL data volume is compatible"
    ;;
  3 | 4)
    echo "    Found $FOUND" >&2
    ;;
  *)
    STATUS=1
    cat >&2 <<EOF
ERROR: the PostgreSQL data volume is not usable by this release:
         ${FOUND:-could not inspect the volume (see the error above)}

       Nothing was stopped or changed. See "Upgrading PostgreSQL" in
       deploy/DEPLOYMENT.md.
EOF
    ;;
esac
exit "$STATUS"
