import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class WebSettings:
    app_name: str = os.getenv("APP_NAME", "algodooonline")
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")
    cognito_user_pool_id: str = os.getenv("COGNITO_USER_POOL_ID", "")
    cognito_client_id: str = os.getenv("COGNITO_CLIENT_ID", "")
    cognito_domain: str = os.getenv("COGNITO_DOMAIN", "")
    dynamodb_table_name: str = os.getenv("DDB_TABLE_NAME", "algodoo-main")


@lru_cache
def get_settings() -> WebSettings:
    return WebSettings()

