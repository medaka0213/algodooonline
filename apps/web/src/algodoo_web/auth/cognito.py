"""Real Amazon Cognito backend: USER_PASSWORD_AUTH flows + JWKS-verified id tokens.

COGNITO_ENDPOINT_URL redirects both the cognito-idp API and the JWKS fetch to a
moto server for integration tests; production leaves it empty."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import boto3
import jwt
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from algodoo_web.auth.base import AuthError, SessionTokens
from algodoo_web.config import WebSettings

_ERROR_MESSAGES = {
    "NotAuthorizedException": "ユーザー名またはパスワードが違います",
    "UserNotFoundException": "ユーザー名またはパスワードが違います",
    "UserNotConfirmedException": "メールアドレスの確認が完了していません",
    "UsernameExistsException": "このユーザー名は既に使われています",
    "AliasExistsException": "このメールアドレスは既に使われています",
    "CodeMismatchException": "検証コードが正しくありません",
    "ExpiredCodeException": "検証コードの有効期限が切れています",
    "InvalidPasswordException": "パスワードが要件を満たしていません (8文字以上)",
    "InvalidParameterException": "入力内容が正しくありません",
    "PasswordResetRequiredException": "パスワードの再設定が必要です",
    "LimitExceededException": "試行回数の上限に達しました。時間をおいて再度お試しください",
    "TooManyRequestsException": "リクエストが混み合っています。時間をおいて再度お試しください",
}


def _auth_error(exc: ClientError) -> AuthError:
    code = exc.response.get("Error", {}).get("Code", "")
    message = _ERROR_MESSAGES.get(code, f"認証エラーが発生しました ({code})")
    return AuthError(message)


class CognitoAuthBackend:
    def __init__(self, settings: WebSettings):
        self._settings = settings
        # Only unauthenticated cognito-idp APIs are used, so requests stay unsigned
        # and no AWS credentials are required for auth.
        self._client = boto3.client(
            "cognito-idp",
            region_name=settings.aws_region,
            endpoint_url=settings.cognito_endpoint_url or None,
            config=Config(signature_version=UNSIGNED),
        )
        self._issuer = (
            f"https://cognito-idp.{settings.aws_region}.amazonaws.com/"
            f"{settings.cognito_user_pool_id}"
        )
        jwks_base = (
            settings.cognito_endpoint_url.rstrip("/")
            if settings.cognito_endpoint_url
            else f"https://cognito-idp.{settings.aws_region}.amazonaws.com"
        )
        self._jwk_client = jwt.PyJWKClient(
            f"{jwks_base}/{settings.cognito_user_pool_id}/.well-known/jwks.json",
            cache_keys=True,
        )

    def _secret_hash(self, username: str) -> str | None:
        secret = self._settings.cognito_client_secret
        if not secret:
            return None
        digest = hmac.new(
            secret.encode(),
            (username + self._settings.cognito_client_id).encode(),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode()

    def _with_secret_hash(self, params: dict, username: str, key: str = "SECRET_HASH") -> dict:
        secret_hash = self._secret_hash(username)
        if secret_hash:
            params[key] = secret_hash
        return params

    def _tokens_from_auth_result(
        self, result: dict, *, fallback_refresh_token: str = ""
    ) -> SessionTokens:
        id_token = result.get("IdToken", "")
        claims = self.verify_id_token(id_token)
        if claims is None:
            raise AuthError("トークンの検証に失敗しました")
        now = datetime.now(UTC)
        return SessionTokens(
            id_token=id_token,
            refresh_token=result.get("RefreshToken", "") or fallback_refresh_token,
            access_exp=now + timedelta(seconds=int(result.get("ExpiresIn") or 3600)),
            refresh_exp=now + timedelta(days=self._settings.cognito_refresh_ttl_days),
            name=str(claims.get("name") or ""),
            sub=str(claims.get("sub") or ""),
        )

    def sign_in(self, username: str, password: str) -> SessionTokens:
        try:
            response = self._client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters=self._with_secret_hash(
                    {"USERNAME": username, "PASSWORD": password}, username
                ),
                ClientId=self._settings.cognito_client_id,
            )
        except ClientError as exc:
            raise _auth_error(exc) from exc
        result = response.get("AuthenticationResult")
        if not result:
            # NEW_PASSWORD_REQUIRED etc. — not part of the legacy screens.
            raise AuthError("このアカウントは追加の認証手続きが必要です")
        return self._tokens_from_auth_result(result)

    def sign_up(self, username: str, email: str, password: str) -> None:
        try:
            self._client.sign_up(
                **self._with_secret_hash(
                    {
                        "ClientId": self._settings.cognito_client_id,
                        "Username": username,
                        "Password": password,
                        "UserAttributes": [{"Name": "email", "Value": email}],
                    },
                    username,
                    key="SecretHash",
                )
            )
        except ClientError as exc:
            raise _auth_error(exc) from exc

    def confirm_sign_up(self, username: str, code: str) -> None:
        try:
            self._client.confirm_sign_up(
                **self._with_secret_hash(
                    {
                        "ClientId": self._settings.cognito_client_id,
                        "Username": username,
                        "ConfirmationCode": code,
                    },
                    username,
                    key="SecretHash",
                )
            )
        except ClientError as exc:
            raise _auth_error(exc) from exc

    def forgot_password(self, username: str) -> None:
        try:
            self._client.forgot_password(
                **self._with_secret_hash(
                    {
                        "ClientId": self._settings.cognito_client_id,
                        "Username": username,
                    },
                    username,
                    key="SecretHash",
                )
            )
        except ClientError as exc:
            raise _auth_error(exc) from exc

    def confirm_forgot_password(self, username: str, code: str, new_password: str) -> None:
        try:
            self._client.confirm_forgot_password(
                **self._with_secret_hash(
                    {
                        "ClientId": self._settings.cognito_client_id,
                        "Username": username,
                        "ConfirmationCode": code,
                        "Password": new_password,
                    },
                    username,
                    key="SecretHash",
                )
            )
        except ClientError as exc:
            raise _auth_error(exc) from exc

    def change_password(self, username: str, old_password: str, new_password: str) -> None:
        # The legacy screen submits username + old password, so authenticate first
        # and use the resulting access token; nothing is persisted in cookies.
        tokens = None
        try:
            response = self._client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters=self._with_secret_hash(
                    {"USERNAME": username, "PASSWORD": old_password}, username
                ),
                ClientId=self._settings.cognito_client_id,
            )
            tokens = response.get("AuthenticationResult") or {}
            self._client.change_password(
                PreviousPassword=old_password,
                ProposedPassword=new_password,
                AccessToken=tokens.get("AccessToken", ""),
            )
        except ClientError as exc:
            raise _auth_error(exc) from exc

    def refresh(self, refresh_token: str, username: str, sub: str) -> SessionTokens | None:
        if not refresh_token:
            return None
        try:
            response = self._client.initiate_auth(
                AuthFlow="REFRESH_TOKEN_AUTH",
                # SECRET_HASH is HMAC(username + client_id); Cognito's internal
                # username, not sub, or secret-bearing clients get NotAuthorizedException.
                AuthParameters=self._with_secret_hash(
                    {"REFRESH_TOKEN": refresh_token}, username or sub
                ),
                ClientId=self._settings.cognito_client_id,
            )
        except ClientError:
            return None
        result = response.get("AuthenticationResult")
        if not result:
            return None
        try:
            return self._tokens_from_auth_result(result, fallback_refresh_token=refresh_token)
        except AuthError:
            return None

    def verify_id_token(self, token: str) -> dict | None:
        if not token or token.count(".") != 2:
            return None
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._settings.cognito_client_id,
                issuer=self._issuer,
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError, OSError, ValueError):
            return None
        if claims.get("token_use") != "id":
            return None
        username = claims.get("cognito:username") or claims.get("name") or ""
        return {
            "name": str(username),
            "sub": str(claims.get("sub") or ""),
            "email": str(claims.get("email") or ""),
            "email_verified": bool(claims.get("email_verified", False)),
        }
