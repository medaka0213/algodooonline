import time

from algodoo_data.config import get_data_settings
from algodoo_data.repository import init_table, seed_demo_data


def bootstrap_data() -> None:
    settings = get_data_settings()
    last_error: Exception | None = None
    for _ in range(30):
        try:
            init_table()
            break
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    else:
        raise RuntimeError("failed to initialize DynamoDB table") from last_error
    if settings.seed_demo_data:
        seed_demo_data()
