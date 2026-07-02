"""Session refresh middleware (SPEC §18-2): clears dead sessions and renews the
id token BEFORE the handler runs, so real JWTs never reach handlers expired."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from algodoo_web.auth import get_auth_backend
from algodoo_web.auth.base import SessionTokens
from algodoo_web.auth.cookies import parse_session_expiry, strip_auth_cookies
from algodoo_web.config import get_settings


def _rewrite_request_cookies(request: Request, updates: dict[str, str]) -> None:
    cookies = dict(request.cookies)
    cookies.update(updates)
    header = "; ".join(f"{key}={value}" for key, value in cookies.items())
    headers = [(k, v) for k, v in request.scope["headers"] if k.lower() != b"cookie"]
    headers.append((b"cookie", header.encode()))
    request.scope["headers"] = headers


class SessionRefreshMiddleware(BaseHTTPMiddleware):
    """Drop sessions whose refresh window lapsed; renew lapsed access tokens."""

    async def dispatch(self, request: Request, call_next) -> Response:
        now = datetime.now(UTC)
        token = request.cookies.get("algodoo_idtoken")
        refresh = request.cookies.get("algodoo_refresh", "")
        refresh_exp = parse_session_expiry(request.cookies.get("algodoo_refresh_exp", ""))
        if token and refresh_exp and refresh_exp < now:
            response = await call_next(request)
            return strip_auth_cookies(response)

        tokens: SessionTokens | None = None
        if token and refresh:
            access_exp = parse_session_expiry(request.cookies.get("algodoo_access_exp", ""))
            if not access_exp or access_exp <= now + timedelta(seconds=5):
                username = (request.cookies.get("algodoo_name") or "").strip()
                sub = (request.cookies.get("algodoo_sub") or "").strip()
                tokens = get_auth_backend().refresh(refresh, username, sub)
                if tokens is not None:
                    _rewrite_request_cookies(
                        request,
                        {
                            "algodoo_idtoken": tokens.id_token,
                            "algodoo_access_exp": tokens.access_exp.isoformat(),
                        },
                    )

        response = await call_next(request)
        if tokens is not None:
            secure = get_settings().cookie_secure
            response.set_cookie(
                "algodoo_idtoken", tokens.id_token, httponly=True, samesite="lax", secure=secure
            )
            response.set_cookie(
                "algodoo_access_exp",
                tokens.access_exp.isoformat(),
                httponly=True,
                samesite="lax",
                secure=secure,
            )
            if tokens.refresh_token and tokens.refresh_token != refresh:
                response.set_cookie(
                    "algodoo_refresh",
                    tokens.refresh_token,
                    httponly=True,
                    samesite="lax",
                    secure=secure,
                )
        return response
