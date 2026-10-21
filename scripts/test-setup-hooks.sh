#!/usr/bin/env bash
# Verify hook setup works in ordinary repositories and linked worktrees.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
export GIT_CONFIG_GLOBAL="$WORK_DIR/global-gitconfig"
export GIT_CONFIG_NOSYSTEM=1
REPO="$WORK_DIR/repo"
LINKED="$WORK_DIR/linked"
mkdir -p "$REPO/scripts"
cp "$SCRIPT_DIR/setup-hooks.sh" "$REPO/scripts/setup-hooks.sh"
cp "$SCRIPT_DIR/pre-commit" "$REPO/scripts/pre-commit"
git init -q "$REPO"
git -C "$REPO" config user.name 'WrzDJ hook test'
git -C "$REPO" config user.email 'hooks@example.invalid'
git -C "$REPO" add scripts
git -C "$REPO" -c commit.gpgsign=false commit -qm 'fixture'

assert_hook() {
  local repo="$1"
  local hook_path expected_target
  hook_path="$(git -C "$repo" rev-parse --path-format=absolute --git-path hooks)/pre-commit"
  expected_target="$repo/scripts/pre-commit"
  [[ -L "$hook_path" ]] || { printf 'expected hook symlink at %s\n' "$hook_path" >&2; return 1; }
  [[ "$(readlink "$hook_path")" == "$expected_target" ]] || {
    printf 'expected hook target %s, got %s\n' "$expected_target" "$(readlink "$hook_path")" >&2
    return 1
  }
}

(cd "$REPO" && bash scripts/setup-hooks.sh >/dev/null)
assert_hook "$REPO"
git -C "$REPO" worktree add -q "$LINKED" -b linked-hooks-test
(cd "$LINKED" && bash scripts/setup-hooks.sh >/dev/null)
assert_hook "$LINKED"
echo 'Git hooks install in repositories and linked worktrees.'

# Regression coverage for staged-file gating at baseline 57cfcdc6867f.
# Real Git commits exercise the installed hook; only external checkers are stubbed.
mkdir -p "$REPO/server/.venv/bin" "$REPO/server/app"
export HOOK_CHECK_LOG="$WORK_DIR/checks.log"
cat > "$WORK_DIR/checker" <<'CHECKER'
#!/usr/bin/env bash
set -euo pipefail
checker=${0##*/}
printf '%s %s|%s\n' "$checker" "$*" "$PWD" >> "$HOOK_CHECK_LOG"
if [ "$checker $*" = "${HOOK_FAIL_COMMAND:-}" ]; then
  exit 17
fi
CHECKER
chmod +x "$WORK_DIR/checker"
cp "$WORK_DIR/checker" "$REPO/server/.venv/bin/ruff"
cp "$WORK_DIR/checker" "$REPO/server/.venv/bin/bandit"
touch "$HOOK_CHECK_LOG"

printf 'unrelated documentation\n' > "$REPO/README.md"
printf 'value = 1\n' > "$REPO/server/app/example.py"
git -C "$REPO" add README.md
git -C "$REPO" -c commit.gpgsign=false commit -qm 'unrelated change' > "$WORK_DIR/unrelated.log"
test ! -s "$HOOK_CHECK_LOG"

git -C "$REPO" add server/app/example.py
git -C "$REPO" -c commit.gpgsign=false commit -qm 'nested Python change' > "$WORK_DIR/nested.log"
cat > "$WORK_DIR/expected-checks" <<EXPECTED
ruff check .|$REPO/server
ruff format --check .|$REPO/server
bandit -r app -c pyproject.toml -q|$REPO/server
EXPECTED
diff -u "$WORK_DIR/expected-checks" "$HOOK_CHECK_LOG"

: > "$HOOK_CHECK_LOG"
printf 'value = 2\n' > "$REPO/server/entry.py"
git -C "$REPO" add server/entry.py
previous_head=$(git -C "$REPO" rev-parse HEAD)
if HOOK_FAIL_COMMAND='ruff check .' git -C "$REPO" -c commit.gpgsign=false \
  commit -qm 'rejected Python change' > "$WORK_DIR/rejected.log" 2>&1; then
  echo 'a failing backend check must reject the commit' >&2
  exit 1
fi
test "$(git -C "$REPO" rev-parse HEAD)" = "$previous_head"
printf 'ruff check .|%s/server\n' "$REPO" > "$WORK_DIR/expected-failure"
diff -u "$WORK_DIR/expected-failure" "$HOOK_CHECK_LOG"

echo 'Installed pre-commit hook gates staged Python files and rejects failing checks.'
