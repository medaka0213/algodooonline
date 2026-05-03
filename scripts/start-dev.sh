#!/bin/sh
set -eu

cd /app

uv sync --all-packages
uv run --with "moto[server]>=5.1.22" moto_server -H 127.0.0.1 -p 8001 >/tmp/moto.log 2>&1 &

python3 - <<'PY'
import socket
import time

deadline = time.time() + 60
while time.time() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 8001), timeout=1):
            raise SystemExit(0)
    except OSError:
        time.sleep(1)
raise SystemExit("moto server did not start within 60 seconds")
PY

exec uv run --package algodoo-web uvicorn algodoo_web.main:app --host 0.0.0.0 --port 8000
