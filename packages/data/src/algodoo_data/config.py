import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class DataSettings:
    table_name: str = os.getenv("DDB_TABLE_NAME", "algodoo-main")
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")
    endpoint_url: str | None = os.getenv("DDB_ENDPOINT_URL") or None
    aws_access_key_id: str | None = os.getenv("AWS_ACCESS_KEY_ID") or None
    aws_secret_access_key: str | None = os.getenv("AWS_SECRET_ACCESS_KEY") or None
    seed_demo_data: bool = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"


@lru_cache
def get_data_settings() -> DataSettings:
    return DataSettings()
