"""Block until a URL answers 2xx (used by compose test profiles without healthchecks)."""

import sys
import time
from urllib.request import urlopen

url = sys.argv[1]
deadline = time.monotonic() + float(sys.argv[2] if len(sys.argv) > 2 else 120)
while True:
    try:
        with urlopen(url, timeout=30) as resp:
            if 200 <= resp.status < 300:
                break
    except Exception as exc:  # noqa: BLE001 - keep polling until the deadline
        if time.monotonic() > deadline:
            sys.exit(f"timed out waiting for {url}: {exc}")
    time.sleep(1)
print(f"ready: {url}")
