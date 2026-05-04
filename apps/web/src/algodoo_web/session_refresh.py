"""Local Cookie session: refresh expiry, id token rotation (SPEC §18-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

AUTH_COOKIE_NAMES = (
    "algodoo_name",
    "algodoo_sub",
    "algodoo_idtoken",
    "algodoo_refresh",
    "algodoo_refresh_exp",
    "algodoo_access_exp",
)


def parse_session_expiry(value: str) -> datetime | None:
    """Parse ISO datetime from session cookies; None if missing or legacy placeholder."""
    if not value or value == "local":
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def strip_auth_cookies(response: Response) -> Response:
    for name in AUTH_COOKIE_NAMES:
        response.delete_cookie(name)
    return response


class LocalSessionRefreshMiddleware(BaseHTTPMiddleware):
    """Clear dead sessions; refresh local idToken when access window lapses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        now = datetime.now(UTC)
        token = request.cookies.get("algodoo_idtoken")
        refresh_exp = parse_session_expiry(request.cookies.get("algodoo_refresh_exp", ""))
        if token and refresh_exp and refresh_exp < now:
            response = await call_next(request)
            return strip_auth_cookies(response)

        response = await call_next(request)
        refresh = request.cookies.get("algodoo_refresh", "")
        if not token or not refresh.startswith("local-refresh-"):
            return response
        access_exp = parse_session_expiry(request.cookies.get("algodoo_access_exp", ""))
        if refresh_exp and refresh_exp < now:
            return response
        if access_exp and access_exp > now + timedelta(seconds=5):
            return response
        if not token.startswith("local-token-"):
            return response
        username = (request.cookies.get("algodoo_name") or "").strip()
        if not username:
            return response
        new_token = f"local-token-{username}-r{int(now.timestamp())}"
        new_access = (now + timedelta(minutes=15)).isoformat()
        response.set_cookie("algodoo_idtoken", new_token, httponly=True, samesite="lax")
        response.set_cookie("algodoo_access_exp", new_access, httponly=True, samesite="lax")
        return response
