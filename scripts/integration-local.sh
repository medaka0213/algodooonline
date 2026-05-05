#!/bin/sh
set -eu

cd /app

uv sync --all-packages
uv run python /app/scripts/integration_local.py
