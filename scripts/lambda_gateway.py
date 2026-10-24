"""Local stand-in for API Gateway HTTP API in front of the Lambda runtime emulator.

Translates plain HTTP requests into payload-format-2.0 events, invokes the
function through the Runtime Interface Emulator bundled in the AWS Lambda
Python base image, and turns the result back into an HTTP response. Lets
scripts/integration_local.py run unchanged against the packaged Lambda zip.

Env: LAMBDA_INVOKE_URL (default http://lambda:8080/2015-03-31/functions/function/invocations),
PORT (default 8000).
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

INVOKE_URL = os.environ.get(
    "LAMBDA_INVOKE_URL", "http://lambda:8080/2015-03-31/functions/function/invocations"
)
PORT = int(os.environ.get("PORT", "8000"))
# The emulator runs one invocation at a time, like a single warm Lambda instance.
_INVOKE_LOCK = threading.Lock()


def build_event(method: str, target: str, headers, body: bytes, client_ip: str) -> dict:
    url = urlsplit(target)
    joined: dict[str, str] = {}
    cookies: list[str] = []
    for name, value in headers.items():
        key = name.lower()
        if key == "cookie":
            # HTTP API moves cookies out of the headers into a dedicated list.
            cookies.extend(part.strip() for part in value.split(";") if part.strip())
            continue
        joined[key] = f"{joined[key]},{value}" if key in joined else value
    joined.setdefault("x-forwarded-proto", "http")
    joined.setdefault("x-forwarded-for", client_ip)
    now = time.time()
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": url.path or "/",
        "rawQueryString": url.query,
        "headers": joined,
        "requestContext": {
            "accountId": "000000000000",
            "apiId": "local",
            "domainName": joined.get("host", "localhost"),
            "domainPrefix": "local",
            "http": {
                "method": method,
                "path": url.path or "/",
                "protocol": "HTTP/1.1",
                "sourceIp": client_ip,
                "userAgent": joined.get("user-agent", ""),
            },
            "requestId": uuid.uuid4().hex,
            "routeKey": "$default",
            "stage": "$default",
            "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime(now)),
            "timeEpoch": int(now * 1000),
        },
        "isBase64Encoded": bool(body),
    }
    if cookies:
        event["cookies"] = cookies
    if body:
        event["body"] = base64.b64encode(body).decode()
    return event


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        event = build_event(self.command, self.path, self.headers, body, self.client_address[0])
        req = Request(INVOKE_URL, data=json.dumps(event).encode(), method="POST")
        with _INVOKE_LOCK, urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        if "statusCode" not in result:
            self.send_error(502, "invalid Lambda response")
            return
        payload = result.get("body") or ""
        data = base64.b64decode(payload) if result.get("isBase64Encoded") else payload.encode()
        self.send_response(int(result["statusCode"]))
        for name, value in (result.get("headers") or {}).items():
            if name.lower() in {"content-length", "transfer-encoding", "connection"}:
                continue
            self.send_header(name, value)
        for name, values in (result.get("multiValueHeaders") or {}).items():
            for value in values:
                self.send_header(name, value)
        for cookie in result.get("cookies") or []:
            self.send_header("set-cookie", cookie)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _handle

    def log_message(self, fmt, *args) -> None:  # noqa: D401 - keep stdout quiet
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
