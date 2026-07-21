"""Pseudo-session backend for compose/dev/CI. Keeps the pre-Cognito behavior:
no password checks. Tokens are plain `local-token-{username}-e{unix_expiry}`
strings; the `-e...` suffix gives them a real expiry so a captured token (e.g.
sent via the Authorization header, which skips the cookie refresh logic) does
not stay valid forever. Tokens without an expiry suffix are rejected."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from algodoo_data.repository import create_user, get_user

from algodoo_web.auth.base import SessionTokens

_TOKEN_PREFIX = "local-token-"
_REFRESH_PREFIX = "local-refresh-"
_EXPIRY_SUFFIX = re.compile(r"-e(\d{1,12})$")

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)


class LocalAuthBackend:
    def _tokens(self, username: str, sub: str, refresh_token: str | None = None) -> SessionTokens:
        now = datetime.now(UTC)
        access_exp = now + ACCESS_TTL
        return SessionTokens(
            id_token=f"{_TOKEN_PREFIX}{username}-e{int(access_exp.timestamp())}",
            refresh_token=refresh_token or f"{_REFRESH_PREFIX}{username}",
            access_exp=access_exp,
            refresh_exp=now + REFRESH_TTL,
            name=username,
            sub=sub,
        )

    def sign_in(self, username: str, password: str) -> SessionTokens:
        user = get_user(username)
        if user is None:
            user = create_user(
                username=username,
                email=f"{username}@local.invalid",
                sub=f"local-{username}",
            )
        return self._tokens(username, user.sub)

    def sign_up(self, username: str, email: str, password: str) -> None:
        return None

    def confirm_sign_up(self, username: str, code: str) -> None:
        create_user(
            username=username,
            email=f"{username}@local.invalid",
            sub=f"local-{username}",
        )

    def forgot_password(self, username: str) -> None:
        return None

    def confirm_forgot_password(self, username: str, code: str, new_password: str) -> None:
        return None

    def change_password(self, username: str, old_password: str, new_password: str) -> None:
        return None

    def refresh(self, refresh_token: str, username: str, sub: str) -> SessionTokens | None:
        if not refresh_token.startswith(_REFRESH_PREFIX) or not username:
            return None
        return self._tokens(username, sub or f"local-{username}", refresh_token=refresh_token)

    def verify_id_token(self, token: str) -> dict | None:
        if not token.startswith(_TOKEN_PREFIX):
            return None
        body = token.removeprefix(_TOKEN_PREFIX)
        match = _EXPIRY_SUFFIX.search(body)
        if match is None:
            # Legacy `local-token-{username}` tokens carry no expiry: reject them
            # so header-supplied local tokens cannot be valid forever.
            return None
        if int(match.group(1)) <= datetime.now(UTC).timestamp():
            return None
        username = body[: match.start()] or "anonymous"
        user = get_user(username)
        sub = user.sub if user else f"local-{username}"
        email = user.email if user else f"{username}@local.invalid"
        return {
            "name": username,
            "sub": sub,
            "email": email,
            "email_verified": True,
        }
