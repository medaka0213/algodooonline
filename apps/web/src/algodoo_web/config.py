import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class WebSettings:
    app_name: str = os.getenv("APP_NAME", "algodooonline")
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")
    cognito_user_pool_id: str = os.getenv("COGNITO_USER_POOL_ID", "")
    cognito_client_id: str = os.getenv("COGNITO_CLIENT_ID", "")
    cognito_domain: str = os.getenv("COGNITO_DOMAIN", "")
    dynamodb_table_name: str = os.getenv("DDB_TABLE_NAME", "algodoo-main")
    # Legacy API expects x-api-key (SPEC §11). Set env to empty to disable (local only).
    legacy_x_api_key: str = field(
        default_factory=lambda: (os.getenv("LEGACY_X_API_KEY") or "local-x-api-key").strip()
    )
    # Optional S3 object storage for IMAGE/DATA keys (SPEC §575). Empty bucket → local media/ only.
    asset_s3_bucket: str = field(default_factory=lambda: (os.getenv("ASSET_S3_BUCKET") or "").strip())
    asset_s3_prefix: str = field(
        default_factory=lambda: (os.getenv("ASSET_S3_PREFIX") or "").strip().strip("/")
    )
    asset_public_base_url: str = field(
        default_factory=lambda: (os.getenv("ASSET_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    )
    asset_s3_public_acl: bool = field(
        default_factory=lambda: os.getenv("ASSET_S3_PUBLIC_ACL", "").lower() in {"1", "true", "yes"}
    )


@lru_cache
def get_settings() -> WebSettings:
    return WebSettings()

