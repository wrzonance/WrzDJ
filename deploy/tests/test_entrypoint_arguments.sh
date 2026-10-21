#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin"
sentinel="$scratch/unexpected-command"

for command_name in id dirname realpath cp ln; do
  cat > "$scratch/bin/$command_name" <<'STUB'
#!/usr/bin/env bash
touch "${ARGUMENT_GUARD_SENTINEL:?}"
exit 99
STUB
  chmod +x "$scratch/bin/$command_name"
done

expect_rejected_args() {
  local path="$1" label="$2"
  local output="$scratch/$label.log"
  shift 2
  if PATH="$scratch/bin:$PATH" ARGUMENT_GUARD_SENTINEL="$sentinel" \
    bash "$path" "$@" >"$output" 2>&1; then
    echo "$label accepted extra arguments" >&2
    exit 1
  fi
  grep -Fq 'Usage:' "$output" || {
    cat "$output" >&2
    echo "$label did not print usage" >&2
    exit 1
  }
  test ! -e "$sentinel" || {
    echo "$label ran a command before rejecting arguments" >&2
    exit 1
  }
}

expect_rejected_args "$repo_root/deploy/setup-user.sh" setup-user --dry-run unexpected
expect_rejected_args "$repo_root/deploy/setup-nginx.sh" setup-nginx --dry-run unexpected
expect_rejected_args "$repo_root/deploy/wrappers/wrzdj-nginx-install" nginx-install
expect_rejected_args "$repo_root/deploy/wrappers/wrzdj-nginx-install" nginx-install --dry-run unexpected
expect_rejected_args "$repo_root/deploy/wrappers/wrzdj-nginx-confd-install" confd-install
expect_rejected_args "$repo_root/deploy/wrappers/wrzdj-nginx-confd-install" confd-install --dry-run unexpected

printf 'Deploy entrypoints reject invalid argument counts before running commands.\n'
