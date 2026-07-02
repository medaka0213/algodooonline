from functools import lru_cache

from algodoo_web.auth.base import AuthBackend, AuthError, SessionTokens
from algodoo_web.config import get_settings

__all__ = ["AuthBackend", "AuthError", "SessionTokens", "get_auth_backend"]


@lru_cache
def get_auth_backend() -> AuthBackend:
    settings = get_settings()
    if settings.auth_backend == "cognito":
        from algodoo_web.auth.cognito import CognitoAuthBackend

        return CognitoAuthBackend(settings)
    from algodoo_web.auth.local import LocalAuthBackend

    return LocalAuthBackend()
