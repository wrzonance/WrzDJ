#!/usr/bin/env bash
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-path hooks)"
HOOK_PATH="$HOOK_DIR/pre-commit"

mkdir -p "$HOOK_DIR"
ln -sfn "$REPO_ROOT/scripts/pre-commit" "$HOOK_PATH"

echo "Git hooks installed."
