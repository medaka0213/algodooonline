"""Migration integration test: old 4-table layout → single table.

Creates the old `thread/log/like/user` tables (suffix `_mig`) in the moto
DynamoDB endpoint, seeds v1-era data, runs scripts/migrate_v2_import.py twice,
and asserts IDs, v1_* attributes, soft deletes, counts, and idempotency.
"""

import hashlib
import os
import subprocess
import sys

os.environ.setdefault("DDB_TABLE_NAME", "algodoo-main-migration")
os.environ.setdefault("SEED_DEMO_DATA", "false")

import boto3  # noqa: E402
from algodoo_data.repository import (  # noqa: E402
    get_thread,
    get_user,
    init_table,
    list_logs,
    list_threads,
    signin_user,
)
from algodoo_domain.models import LegacyRoute  # noqa: E402

ENDPOINT = os.environ["DDB_ENDPOINT_URL"]
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
SUFFIX = "_mig"

OLD_THREAD_ID = "BBS_01ARZ3NDEKTSV4RRFFQ69G5FAV"
OLD_LOG_ID = f"{OLD_THREAD_ID}_01BX5ZZKBKACTAV9WEVGEMMVRZ"
OLD_CHILD_LOG_ID = f"{OLD_THREAD_ID}_01BX5ZZKBKACTAV9WEVGEMMVS0"
V1_PASSWORD = "old-secret"


def _resource():
    return boto3.resource("dynamodb", region_name=REGION, endpoint_url=ENDPOINT)


def _create_table(ddb, name: str, key_schema: list[dict], attrs: list[dict]) -> None:
    existing = [t.name for t in ddb.tables.all()]
    if name in existing:
        ddb.Table(name).delete()
    ddb.create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attrs,
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )


def seed_old_tables() -> None:
    ddb = _resource()
    _create_table(
        ddb,
        f"thread{SUFFIX}",
        [
            {"AttributeName": "route", "KeyType": "HASH"},
            {"AttributeName": "thread_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "route", "AttributeType": "S"},
            {"AttributeName": "thread_id", "AttributeType": "S"},
        ],
    )
    _create_table(
        ddb,
        f"log{SUFFIX}",
        [
            {"AttributeName": "thread_id", "KeyType": "HASH"},
            {"AttributeName": "log_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "thread_id", "AttributeType": "S"},
            {"AttributeName": "log_id", "AttributeType": "S"},
        ],
    )
    _create_table(
        ddb,
        f"like{SUFFIX}",
        [
            {"AttributeName": "post_id", "KeyType": "HASH"},
            {"AttributeName": "user_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "post_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
        ],
    )
    _create_table(
        ddb,
        f"user{SUFFIX}",
        [{"AttributeName": "Username", "KeyType": "HASH"}],
        [{"AttributeName": "Username", "AttributeType": "S"}],
    )

    ddb.Table(f"user{SUFFIX}").put_item(
        Item={
            "Username": "olduser",
            "version": "1",
            "v1_id": 42,
            "v1_name": "OldUser",
            "v1_password": hashlib.sha512(V1_PASSWORD.encode()).hexdigest(),
        }
    )
    ddb.Table(f"user{SUFFIX}").put_item(
        Item={
            "Username": "newuser",
            "sub": "sub-newuser",
            "email": "new@example.invalid",
            "email_verified": True,
            "version": "2",
        }
    )
    ddb.Table(f"thread{SUFFIX}").put_item(
        Item={
            "route": "BBS",
            "thread_id": OLD_THREAD_ID,
            "title": "旧スレッド",
            "content": "旧本文",
            "user_id": "v1-user-42",
            "user_name": "OldUser",
            "created_at": "2019-05-01T00:00:00+00:00",
            "updated_at": "2019-06-01T00:00:00+00:00",
            "nRes": 2,
            "nLike": 1,
            "isEdited": False,
            "isDeleted": False,
            "filedata": [],
            "v1_id": 100,
            "v1_userID": 42,
            "v1_userName": "OldUser",
        }
    )
    ddb.Table(f"thread{SUFFIX}").put_item(
        Item={
            "route": "BBS",
            "thread_id": "BBS_01ARZ3NDEKTSV4RRFFQ69G5FB0",
            "title": "削除済みスレッド",
            "content": "deleted",
            "user_name": "OldUser",
            "created_at": "2019-05-02T00:00:00+00:00",
            "updated_at": "2019-05-02T00:00:00+00:00",
            "isDeleted": True,
        }
    )
    ddb.Table(f"log{SUFFIX}").put_item(
        Item={
            "thread_id": OLD_THREAD_ID,
            "log_id": OLD_LOG_ID,
            "content": "旧ログ",
            "user_id": "v1-user-42",
            "user_name": "OldUser",
            "created_at": "2019-05-03T00:00:00+00:00",
            "updated_at": "2019-05-03T00:00:00+00:00",
            "nRes": 1,
            "nLike": 0,
            "v1_id": 200,
            "v1_resID": 300,
            "v1_threadID": 100,
        }
    )
    ddb.Table(f"log{SUFFIX}").put_item(
        Item={
            "thread_id": OLD_THREAD_ID,
            "log_id": OLD_CHILD_LOG_ID,
            "response_to": OLD_LOG_ID,
            "content": "旧返信",
            "user_id": "sub-newuser",
            "user_name": "newuser",
            "created_at": "2019-05-04T00:00:00+00:00",
            "updated_at": "2019-05-04T00:00:00+00:00",
            "isDeleted": False,
        }
    )
    ddb.Table(f"like{SUFFIX}").put_item(
        Item={"post_id": OLD_THREAD_ID, "user_id": "sub-newuser", "type": "good"}
    )


def run_migration() -> None:
    subprocess.run(
        [
            sys.executable,
            "scripts/migrate_v2_import.py",
            "--apply",
            "--yes",
            "--source-endpoint-url",
            ENDPOINT,
            "--table-suffix",
            SUFFIX,
            "--recompute-counts",
        ],
        check=True,
        env=os.environ.copy(),
    )


def destination_item_count() -> int:
    table = boto3.resource("dynamodb", region_name=REGION, endpoint_url=ENDPOINT).Table(
        os.environ["DDB_TABLE_NAME"]
    )
    count = 0
    kwargs: dict = {"Select": "COUNT"}
    while True:
        page = table.scan(**kwargs)
        count += page["Count"]
        if "LastEvaluatedKey" not in page:
            return count
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main() -> None:
    seed_old_tables()
    run_migration()
    # Bind this process's ddb_single Table handle before reading assertions.
    init_table()

    thread = get_thread(LegacyRoute.BBS, OLD_THREAD_ID)
    assert thread is not None, "old thread must be importable by its original ID"
    assert thread.title == "旧スレッド"
    assert thread.v1_id == "100"
    assert thread.v1_user_id == "42"
    assert thread.v1_user_name == "OldUser"
    assert thread.created_at == "2019-05-01T00:00:00+00:00"
    assert thread.n_res == 2, f"trusted/recomputed nRes should stay 2, got {thread.n_res}"
    assert thread.n_like == 1

    visible = list_threads(LegacyRoute.BBS)
    assert all(t.thread_id != "BBS_01ARZ3NDEKTSV4RRFFQ69G5FB0" for t in visible), (
        "soft-deleted thread must stay hidden"
    )
    deleted = get_thread(LegacyRoute.BBS, "BBS_01ARZ3NDEKTSV4RRFFQ69G5FB0", include_deleted=True)
    assert deleted is not None and deleted.is_deleted

    logs = list_logs(OLD_THREAD_ID)
    by_id = {log.log_id: log for log in logs}
    assert OLD_LOG_ID in by_id and OLD_CHILD_LOG_ID in by_id
    assert by_id[OLD_CHILD_LOG_ID].response_to == OLD_LOG_ID
    assert by_id[OLD_LOG_ID].v1_res_id == "300"
    assert by_id[OLD_LOG_ID].n_res == 1

    olduser = get_user("olduser")
    assert olduser is not None
    assert olduser.version == "1"
    assert olduser.v1_id == "42"
    assert olduser.v1_name == "OldUser"
    signin = signin_user("olduser", V1_PASSWORD)
    assert signin == {"result": True, "isV2": False, "isV1": True}, signin
    # Successful legacy signin must upgrade the stored digest to salted scrypt.
    upgraded = get_user("olduser")
    assert upgraded is not None and upgraded.v1_password is not None
    assert upgraded.v1_password.startswith("scrypt$"), upgraded.v1_password
    # Verification against the upgraded hash must still work.
    assert signin_user("olduser", V1_PASSWORD)["isV1"] is True
    assert signin_user("olduser", "wrong")["isV1"] is False

    newuser = get_user("newuser")
    assert newuser is not None and newuser.version == "2" and newuser.sub == "sub-newuser"

    before = destination_item_count()
    run_migration()
    after = destination_item_count()
    assert before == after, f"re-import must be idempotent ({before} → {after})"

    reimported = get_user("olduser")
    assert reimported is not None and reimported.v1_password is not None
    assert reimported.v1_password.startswith("scrypt$"), (
        "re-import must not downgrade an upgraded password hash"
    )

    print("migration integration ok")


if __name__ == "__main__":
    main()
