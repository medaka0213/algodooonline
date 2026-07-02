"""Auth backend protocol: local pseudo sessions or real Amazon Cognito."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class AuthError(Exception):
    """User-facing auth failure rendered into the form error block (SPEC §16)."""

    def __init__(self, message: str, field: str = "auth"):
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass(frozen=True)
class SessionTokens:
    id_token: str
    refresh_token: str
    access_exp: datetime
    refresh_exp: datetime
    name: str
    sub: str


class AuthBackend(Protocol):
    def sign_in(self, username: str, password: str) -> SessionTokens: ...

    def sign_up(self, username: str, email: str, password: str) -> None: ...

    def confirm_sign_up(self, username: str, code: str) -> None: ...

    def forgot_password(self, username: str) -> None: ...

    def confirm_forgot_password(self, username: str, code: str, new_password: str) -> None: ...

    def change_password(self, username: str, old_password: str, new_password: str) -> None: ...

    def refresh(self, refresh_token: str, username: str, sub: str) -> SessionTokens | None: ...

    def verify_id_token(self, token: str) -> dict | None:
        """Return claims with at least name/sub, or None when the token is invalid."""
        ...
