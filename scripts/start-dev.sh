#!/bin/sh
set -eu

cd /app

# The pinned ddb-single git dependency needs a git executable (bare uv image).
if ! command -v git >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git
fi

uv sync --all-packages

exec uv run --package algodoo-web uvicorn algodoo_web.main:app --host 0.0.0.0 --port 8000
