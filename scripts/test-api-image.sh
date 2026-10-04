#!/usr/bin/env bash
# Regression for 3d178561: the production image ignored server/uv.lock.
set -euo pipefail

image=${1:?Usage: test-api-image.sh IMAGE}
root=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d)
network=
database=
container=
id=
trap '
  if [ "$?" -ne 0 ]; then
    for id in "$container" "$database"; do
      if [ -n "$id" ]; then docker logs "$id" >&2 || true; fi
    done
  fi
  for id in "$container" "$database"; do
    if [ -n "$id" ]; then docker rm --force "$id" >/dev/null || true; fi
  done
  if [ -n "$network" ]; then docker network rm "$network" >/dev/null || true; fi
  rm -rf "$scratch"
' EXIT

# Export independently from the checkout, not a manifest supplied by the image.
# Frozen/offline needs no Python interpreter in the distroless uv container.
docker run --rm --network none --volume "$root/server:/work:ro" --workdir /work \
  ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 \
  export --frozen --no-dev --no-emit-project --no-hashes --offline > "$scratch/requirements.txt"

docker run --rm --interactive --network none --entrypoint python \
  --volume "$scratch/requirements.txt:/tmp/expected-requirements.txt:ro" "$image" - <<'PY'
import importlib.metadata
import importlib.util
from pathlib import Path
import shutil

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

errors = []
checked = 0
expected_names = set()
for line in Path("/tmp/expected-requirements.txt").read_text().splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    requirement = Requirement(line)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    checked += 1
    expected_names.add(canonicalize_name(requirement.name))
    try:
        installed = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed is None or installed not in requirement.specifier:
        errors.append(f"{requirement}: installed {installed or 'MISSING'}")
if not checked:
    errors.append("No production dependencies were checked")
# Regression for 63b1a819: matching required versions also allowed extra build
# dependencies and a reintroduced editable application installation to pass.
installed_names = {
    canonicalize_name(distribution.metadata["Name"])
    for distribution in importlib.metadata.distributions()
}
unexpected = installed_names - expected_names
if unexpected:
    errors.append(f"Unexpected installed distributions: {', '.join(sorted(unexpected))}")
for installer in ("pip", "uv"):
    if importlib.util.find_spec(installer) or shutil.which(installer):
        errors.append(f"The runtime contains {installer}")
if errors:
    raise SystemExit("\n".join(errors))
print(f"All {checked} production dependencies match the lock; no installers remain.")
PY

# No published ports and no route to external services from either container.
network=$(docker network create --internal "wrzdj-api-smoke-$(basename "$scratch")")
database=$(docker run --detach --network "$network" --network-alias database \
  --env POSTGRES_USER=wrzdj --env POSTGRES_PASSWORD=wrzdj --env POSTGRES_DB=wrzdj_test \
  postgres:16@sha256:71e27bf60b70bded003791b5573f8b808365613f341df20ffcf0c1ed7bc13ddf)
container=$(docker run --detach --network "$network" \
  --env DATABASE_URL=postgresql+psycopg://wrzdj:wrzdj@database:5432/wrzdj_test \
  --env JWT_SECRET=test-secret-key --env ENV=development "$image")
runtime_uid=$(docker exec "$container" stat -c %u /proc/1)
if [ "$runtime_uid" = 0 ]; then
  echo 'The API runtime must not run as root.' >&2
  exit 1
fi

for ((attempt = 0; attempt < 60; attempt++)); do
  if docker exec "$container" curl --fail --silent --max-time 2 \
    http://127.0.0.1:8000/health >/dev/null; then
    echo 'API runtime startup, migrations and health check passed.'
    exit 0
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]; then
    break
  fi
  sleep 1
done
echo 'The API runtime did not become healthy within 60 attempts.' >&2
exit 1
