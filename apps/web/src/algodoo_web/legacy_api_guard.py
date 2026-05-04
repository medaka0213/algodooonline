"""Legacy JSON API gates: optional x-api-key (SPEC §11) and session for mutating routes."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request


def require_configured_api_key(request: Request) -> None:
    expected = os.getenv("LEGACY_X_API_KEY", "").strip()
    if not expected:
        return
    incoming = (request.headers.get("x-api-key") or request.headers.get("X-Api-Key") or "").strip()
    if incoming != expected:
        raise HTTPException(status_code=403, detail="invalid x-api-key")


def session_sub(request: Request) -> str | None:
    if not request.cookies.get("algodoo_idtoken"):
        return None
    return request.cookies.get("algodoo_sub") or None


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
