"""Legacy JSON API gates: x-api-key (SPEC §11) and verified session for auth routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Request

from algodoo_web.auth import get_auth_backend
from algodoo_web.auth.cookies import parse_session_expiry
from algodoo_web.config import get_settings


def require_configured_api_key(request: Request) -> None:
    expected = get_settings().legacy_x_api_key
    if not expected:
        return
    incoming = (request.headers.get("x-api-key") or request.headers.get("X-Api-Key") or "").strip()
    if incoming != expected:
        raise HTTPException(status_code=403, detail="invalid x-api-key")


def _session_token(request: Request) -> str | None:
    token = request.cookies.get("algodoo_idtoken")
    if token:
        refresh_deadline = parse_session_expiry(request.cookies.get("algodoo_refresh_exp", ""))
        if refresh_deadline is not None and refresh_deadline < datetime.now(UTC):
            return None
        return token
    # The old Chalice API authenticated with the raw idToken in Authorization.
    header = (request.headers.get("authorization") or "").strip()
    if header.lower().startswith("bearer "):
        header = header[len("bearer ") :].strip()
    return header or None


def session_sub(request: Request) -> str | None:
    token = _session_token(request)
    if not token:
        return None
    claims = get_auth_backend().verify_id_token(token)
    if not claims:
        return None
    return str(claims.get("sub") or "") or None


def require_session(request: Request) -> str:
    require_configured_api_key(request)
    sub = session_sub(request)
    if not sub:
        raise HTTPException(status_code=401, detail="authentication required")
    return sub


def require_matching_user_id(request: Request, user_id: str | None) -> str:
    sub = require_session(request)
    uid = (user_id or "").strip()
    if not uid:
        return sub
    if uid != sub:
        raise HTTPException(status_code=403, detail="user_id does not match session")
    return sub
