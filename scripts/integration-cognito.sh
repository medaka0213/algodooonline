#!/bin/sh
set -eu

cd /app

# The pinned ddb-single git dependency needs a git executable. The compose dev
# image (Dockerfile `dev` stage) preinstalls it; this apt fallback only runs
# when the container image lacks it (e.g. running against the bare uv image).
if ! command -v git >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git
fi

uv sync --all-packages
uv run python /app/scripts/integration_cognito.py
