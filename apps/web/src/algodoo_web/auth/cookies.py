"""Session cookie names and helpers shared by routes, middleware, and API guards."""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.responses import Response

from algodoo_web.auth.base import SessionTokens
from algodoo_web.config import get_settings

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


def _set_cookie(response: Response, key: str, value: str) -> None:
    response.set_cookie(
        key,
        value,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )


def apply_session_cookies(response: Response, tokens: SessionTokens) -> Response:
    _set_cookie(response, "algodoo_name", tokens.name)
    _set_cookie(response, "algodoo_sub", tokens.sub)
    _set_cookie(response, "algodoo_idtoken", tokens.id_token)
    _set_cookie(response, "algodoo_refresh", tokens.refresh_token)
    _set_cookie(response, "algodoo_access_exp", tokens.access_exp.isoformat())
    _set_cookie(response, "algodoo_refresh_exp", tokens.refresh_exp.isoformat())
    return response


def strip_auth_cookies(response: Response) -> Response:
    for name in AUTH_COOKIE_NAMES:
        response.delete_cookie(name)
    return response
