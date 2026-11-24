#!/usr/bin/env bash
# Prints `<job>=true|false` for every job in GROUP (see ci-path-filter.cjs), for
# a workflow step to append to "$GITHUB_OUTPUT".
#
#   bash scripts/ci-select-jobs.sh ci | tee -a "$GITHUB_OUTPUT"
#
# Only a pull request is filtered, by the files it changes. Every other event
# selects every job, and so does a pull request whose file list cannot be
# fetched or has reached the API's 3000-file limit (it would be truncated).
#
# Environment: GH_TOKEN, GITHUB_REPOSITORY, EVENT_NAME, PR_NUMBER.
set -euo pipefail

group=${1:?Usage: ci-select-jobs.sh GROUP}
filter="$(dirname "$0")/ci-path-filter.cjs"

if [ "${EVENT_NAME:-}" = pull_request ] &&
  files=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER/files" --paginate \
    --jq '.[] | .filename, (.previous_filename // empty)') &&
  [ "$(wc -l <<<"$files")" -lt 3000 ]; then
  node "$filter" "$group" <<<"$files"
else
  CI_FILTER_RUN_ALL=true node "$filter" "$group" </dev/null
fi
