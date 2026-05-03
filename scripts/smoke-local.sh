#!/bin/sh
set -eu

docker compose exec app python /app/scripts/smoke_local.py
