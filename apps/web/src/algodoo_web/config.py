import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)

DEFAULT_LEGACY_X_API_KEY = "local-x-api-key"

_PRODUCTION_ENV_NAMES = {"production", "prod"}
_TRUTHY = {"1", "true", "yes"}


def _env_flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).lower() in _TRUTHY


def _resolve_app_env() -> str:
    """Deployment environment flag: APP_ENV (fallback ENVIRONMENT), default dev."""
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower() or "development"


def _default_cookie_secure() -> bool:
    """COOKIE_SECURE env wins; unset defaults to true in production mode."""
    value = os.getenv("COOKIE_SECURE")
    if value is not None:
        return value.strip().lower() in _TRUTHY
    return _resolve_app_env() in _PRODUCTION_ENV_NAMES


def _env_value(name: str, default: str = "") -> str:
    """Like os.getenv but keeps an explicitly empty value (only unset uses default)."""
    value = os.getenv(name)
    return default if value is None else value.strip()


@dataclass(frozen=True)
class WebSettings:
    app_name: str = os.getenv("APP_NAME", "algodooonline")
    # "production"/"prod" turns on strict startup validation; anything else is dev.
    app_env: str = field(default_factory=_resolve_app_env)
    # Explicit, loudly-logged escape hatch for the local backend in production mode.
    allow_insecure_local_auth: bool = field(
        default_factory=lambda: _env_flag("ALLOW_INSECURE_LOCAL_AUTH")
    )
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")
    # local: pseudo session for compose/dev/CI. cognito: real Amazon Cognito User Pool.
    auth_backend: str = field(
        default_factory=lambda: (os.getenv("AUTH_BACKEND") or "local").strip().lower()
    )
    cognito_user_pool_id: str = os.getenv("COGNITO_USER_POOL_ID", "")
    cognito_client_id: str = os.getenv("COGNITO_CLIENT_ID", "")
    cognito_client_secret: str = os.getenv("COGNITO_CLIENT_SECRET", "")
    cognito_domain: str = os.getenv("COGNITO_DOMAIN", "")
    # Override for moto-based integration tests; empty → real AWS endpoint.
    cognito_endpoint_url: str = field(
        default_factory=lambda: (os.getenv("COGNITO_ENDPOINT_URL") or "").strip()
    )
    cognito_refresh_ttl_days: int = field(
        default_factory=lambda: int(os.getenv("COGNITO_REFRESH_TTL_DAYS", "30"))
    )
    cookie_secure: bool = field(default_factory=_default_cookie_secure)
    dynamodb_table_name: str = os.getenv("DDB_TABLE_NAME", "algodoo-main")
    # Legacy API expects x-api-key (SPEC §11). Set env to empty to disable (local only).
    legacy_x_api_key: str = field(
        default_factory=lambda: _env_value("LEGACY_X_API_KEY", DEFAULT_LEGACY_X_API_KEY)
    )
    # Optional S3 for IMAGE/DATA (SPEC §575). Empty bucket → local media/ only.
    asset_s3_bucket: str = field(
        default_factory=lambda: (os.getenv("ASSET_S3_BUCKET") or "").strip(),
    )
    asset_s3_endpoint_url: str = field(
        default_factory=lambda: (os.getenv("ASSET_S3_ENDPOINT_URL") or "").strip(),
    )
    asset_s3_prefix: str = field(
        default_factory=lambda: (os.getenv("ASSET_S3_PREFIX") or "").strip().strip("/")
    )
    asset_public_base_url: str = field(
        default_factory=lambda: (os.getenv("ASSET_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    )
    asset_s3_public_acl: bool = field(default_factory=lambda: _env_flag("ASSET_S3_PUBLIC_ACL"))
    # Dedicated credentials for the asset object store (e.g. self-hosted S3 app key).
    # Empty → boto3 default credential chain (AWS_ACCESS_KEY_ID etc.).
    asset_s3_access_key_id: str = field(
        default_factory=lambda: (os.getenv("ASSET_S3_ACCESS_KEY_ID") or "").strip()
    )
    asset_s3_secret_access_key: str = field(
        default_factory=lambda: (os.getenv("ASSET_S3_SECRET_ACCESS_KEY") or "").strip()
    )
    # Bucket creation belongs to compose init jobs in production.
    asset_s3_auto_create: bool = field(
        default_factory=lambda: _env_flag("ASSET_S3_AUTO_CREATE", "true")
    )
    media_root_override: str = field(
        default_factory=lambda: (os.getenv("MEDIA_ROOT") or "").strip()
    )

    @property
    def is_production(self) -> bool:
        return self.app_env in _PRODUCTION_ENV_NAMES


def validate_production_settings(settings: WebSettings) -> None:
    """Refuse to start with local-grade auth or secrets in production.

    Production mode is signaled by APP_ENV=production (or ENVIRONMENT=production)
    and is validated unconditionally, regardless of AUTH_BACKEND. In addition,
    AUTH_BACKEND=cognito enforces its required settings even without the flag,
    so real-Cognito deployments stay guarded either way.
    """
    if settings.auth_backend not in {"local", "cognito"}:
        raise RuntimeError(
            f"AUTH_BACKEND must be 'local' or 'cognito', got {settings.auth_backend!r}"
        )
    problems: list[str] = []
    if settings.auth_backend == "cognito":
        if not settings.cognito_user_pool_id:
            problems.append("COGNITO_USER_POOL_ID is required")
        if not settings.cognito_client_id:
            problems.append("COGNITO_CLIENT_ID is required")
        if settings.legacy_x_api_key == DEFAULT_LEGACY_X_API_KEY:
            problems.append("LEGACY_X_API_KEY must not keep the local default value")
        if (
            not settings.is_production
            and not settings.cognito_endpoint_url
            and not settings.cookie_secure
        ):
            problems.append("COOKIE_SECURE must be true when using real Cognito")
    if settings.is_production:
        if settings.auth_backend == "local":
            if settings.allow_insecure_local_auth:
                logger.warning(
                    "SECURITY: ALLOW_INSECURE_LOCAL_AUTH is set — the passwordless "
                    "local auth backend is running in PRODUCTION mode. Any "
                    "username/password combination is accepted. Never expose this "
                    "deployment to untrusted networks."
                )
            else:
                problems.append(
                    "AUTH_BACKEND=local is a full auth bypass and is refused when "
                    "APP_ENV=production (set ALLOW_INSECURE_LOCAL_AUTH=1 only for an "
                    "isolated, non-exposed environment)"
                )
        if not settings.legacy_x_api_key:
            problems.append("LEGACY_X_API_KEY must not be empty in production")
        elif (
            settings.auth_backend != "cognito"
            and settings.legacy_x_api_key == DEFAULT_LEGACY_X_API_KEY
        ):
            problems.append("LEGACY_X_API_KEY must not keep the local default value")
        if not settings.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
    if problems:
        raise RuntimeError("invalid production settings: " + "; ".join(problems))


@lru_cache
def get_settings() -> WebSettings:
    return WebSettings()
