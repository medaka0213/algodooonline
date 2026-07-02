#!/bin/sh
set -eu

cd /app

# The pinned ddb-single git dependency needs a git executable (bare uv image),
# and ffmpeg transcodes Playwright's WebM recordings to MP4 for the HTML
# report (Playwright's bundled ffmpeg can't mux MP4). Install both in one shot.
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
