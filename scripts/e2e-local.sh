#!/bin/sh
set -eu

cd /app

# The pinned ddb-single git dependency needs a git executable, and ffmpeg
# transcodes Playwright's WebM recordings to MP4 for the HTML report
# (Playwright's bundled ffmpeg can't mux MP4). The compose dev image
# (Dockerfile `dev` stage) preinstalls both; this apt fallback only runs when
# the container image lacks them (e.g. running against the bare uv image).
missing=""
command -v git >/dev/null 2>&1 || missing="$missing git"
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
if [ -n "$missing" ]; then
  apt-get update -qq && apt-get install -y -qq --no-install-recommends $missing
fi

uv sync --all-packages --group e2e
uv run --group e2e playwright install --with-deps chromium

# pytest-html's --html target directory must exist beforehand; it doesn't
# create parent dirs itself (unlike Playwright's own screenshot/video dirs).
mkdir -p test-results

exec uv run --group e2e pytest tests/e2e "$@"
