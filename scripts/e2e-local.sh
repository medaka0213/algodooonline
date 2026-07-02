#!/bin/sh
set -eu

cd /app

# The pinned ddb-single git dependency needs a git executable (bare uv image).
if ! command -v git >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git
fi

uv sync --all-packages --group e2e
uv run --group e2e playwright install --with-deps chromium
exec uv run --group e2e pytest tests/e2e "$@"
