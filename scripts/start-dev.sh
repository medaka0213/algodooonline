#!/bin/sh
set -eu

cd /app

uv sync --all-packages

exec uv run --package algodoo-web uvicorn algodoo_web.main:app --host 0.0.0.0 --port 8000
