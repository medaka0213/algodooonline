"""Import the old Algon2 4-table DynamoDB layout into the new single table.

Source: the old production tables (`thread`, `log`, `like`, `user`, optionally
with a suffix such as `_test`), read via plain boto3 scans. The source can be
real AWS (use --source-profile / ambient credentials) or a local DynamoDB
endpoint holding a dump (--source-endpoint-url).

Destination: the single table configured through the usual env vars
(DDB_TABLE_NAME / DDB_ENDPOINT_URL / AWS_REGION), written through the same
ddb_single models the app uses. Original IDs, timestamps, and v1_* attributes
are preserved; re-running the import upserts by ID and stays idempotent.

The script runs in DRY-RUN mode by default (scan + map, no writes). Pass
--apply to actually write; applying prompts for interactive confirmation
unless --yes is given (for CI).

Examples:
    uv run python scripts/migrate_v2_import.py \
        --source-profile algon2-prod
    uv run python scripts/migrate_v2_import.py --apply --yes \
        --source-endpoint-url http://localhost:8001 --recompute-counts

S3 assets are migrated separately (keys are unchanged):
    aws s3 sync s3://img.algodooonline.net ./assets-dump
    aws --endpoint-url http://127.0.0.1:9000 s3 sync ./assets-dump s3://algodoo-assets
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from decimal import Decimal

import boto3
from algodoo_data.repository import (
    _persist_log_counts,
    _persist_thread_counts,
    get_log,
    get_thread,
    get_user,
    init_table,
    is_modern_password_hash,
    list_threads,
    query,
)
from algodoo_data.single_table import (
    like_to_record,
    log_to_record,
    thread_to_record,
    user_to_record,
)
from algodoo_domain.models import LegacyRoute, Like, LikeType, Log, Thread, UserProfile

KINDS = ("user", "thread", "log", "like")


def _plain(value):
    """Normalize DynamoDB scan output (Decimal → int, sets → lists)."""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, set):
        return sorted(_plain(v) for v in value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _opt_str(value) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def scan_all(table) -> Iterator[dict]:
    kwargs: dict = {}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            yield _plain(item)
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            return
        kwargs["ExclusiveStartKey"] = last_key


def map_thread(item: dict) -> Thread:
    return Thread(
        route=LegacyRoute(str(item["route"]).upper()),
        thread_id=str(item["thread_id"]),
        user_name=str(item.get("user_name") or "anonymous"),
        title=str(item.get("title") or ""),
        content=str(item.get("content") or ""),
        user_id=str(item.get("user_id") or "anonymous"),
        created_at=str(item.get("created_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
        n_res=int(item.get("nRes") or 0),
        n_like=int(item.get("nLike") or 0),
        filedata=[str(f) for f in item.get("filedata") or []],
        is_edited=bool(item.get("isEdited")),
        is_deleted=bool(item.get("isDeleted")),
        v1_id=_opt_str(item.get("v1_id")),
        v1_user_id=_opt_str(item.get("v1_userID")),
        v1_user_name=_opt_str(item.get("v1_userName")),
    )


def map_log(item: dict) -> Log:
    return Log(
        thread_id=str(item["thread_id"]),
        log_id=str(item["log_id"]),
        user_id=str(item.get("user_id") or "anonymous"),
        user_name=str(item.get("user_name") or "anonymous"),
        content=str(item.get("content") or ""),
        created_at=str(item.get("created_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
        response_to=_opt_str(item.get("response_to")),
        n_res=int(item.get("nRes") or 0),
        n_like=int(item.get("nLike") or 0),
        is_edited=bool(item.get("isEdited")),
        is_deleted=bool(item.get("isDeleted")),
        v1_id=_opt_str(item.get("v1_id")),
        v1_res_id=_opt_str(item.get("v1_resID")),
        v1_thread_id=_opt_str(item.get("v1_threadID")),
        v1_user_id=_opt_str(item.get("v1_userID")),
        v1_user_name=_opt_str(item.get("v1_userName")),
    )


# The old like table has no created_at; use a fixed placeholder so re-imports
# stay idempotent (nullable=False on the destination record).
_UNKNOWN_LIKE_CREATED_AT = "1970-01-01T00:00:00+00:00"


def map_like(item: dict) -> Like:
    return Like(
        post_id=str(item["post_id"]),
        user_id=str(item["user_id"]),
        like_type=LikeType(str(item.get("type") or "good")),
        created_at=str(item.get("created_at") or _UNKNOWN_LIKE_CREATED_AT),
        is_deleted=bool(item.get("isDeleted")),
    )


def map_user(item: dict) -> UserProfile:
    return UserProfile(
        username=str(item["Username"]),
        sub=str(item.get("sub") or item["Username"]),
        email=str(item.get("email") or ""),
        email_verified=bool(item.get("email_verified", False)),
        # Keep the source version verbatim: "1" drives the v1 signin flow.
        version=str(item.get("version") or "1"),
        v1_password=_opt_str(item.get("v1_password")),
        v1_id=_opt_str(item.get("v1_id")),
        v1_name=_opt_str(item.get("v1_name")),
    )


_MAPPERS = {
    "thread": (map_thread, thread_to_record),
    "log": (map_log, log_to_record),
    "like": (map_like, like_to_record),
    "user": (map_user, user_to_record),
}

_SENSITIVE_KEYS = {"v1_password", "email"}


def _safe_repr(item: dict) -> str:
    redacted = {k: ("***" if k in _SENSITIVE_KEYS else v) for k, v in item.items()}
    return repr(redacted)[:120]


def migrate_kind(source_table, kind: str, *, dry_run: bool, limit: int | None) -> dict[str, int]:
    mapper, to_record = _MAPPERS[kind]
    stats = {"read": 0, "written": 0, "errors": 0}
    for item in scan_all(source_table):
        if limit is not None and stats["read"] >= limit:
            break
        stats["read"] += 1
        try:
            model = mapper(item)
        except Exception as exc:  # noqa: BLE001 — report and continue
            stats["errors"] += 1
            print(f"  [error] {kind} {_safe_repr(item)}: {exc}")
            continue
        if dry_run:
            print(f"  [dry-run] would write {kind} {_safe_repr(item)}")
            continue
        if kind == "user":
            # Never downgrade a v1_password already upgraded to the salted
            # scrypt format (upgrade-on-login) back to a legacy sha512 digest.
            existing = get_user(model.username)
            if (
                existing is not None
                and is_modern_password_hash(existing.v1_password)
                and not is_modern_password_hash(model.v1_password)
            ):
                model.v1_password = existing.v1_password
        query().model(to_record(model)).update()
        stats["written"] += 1
    return stats


def recompute_counts() -> None:
    """Recalculate nRes/nLike from the imported data and report differences."""
    for route in LegacyRoute:
        for thread in list_threads(route, include_deleted=True):
            before = (thread.n_res, thread.n_like)
            _persist_thread_counts(thread.thread_id, touch_updated=False)
            after = get_thread(route, thread.thread_id, include_deleted=True)
            if after and (after.n_res, after.n_like) != before:
                print(
                    f"  [counts] {thread.thread_id}: "
                    f"nRes {before[0]}→{after.n_res}, nLike {before[1]}→{after.n_like}"
                )


def recompute_log_counts(source_log_table) -> None:
    for item in scan_all(source_log_table):
        thread_id = str(item["thread_id"])
        log_id = str(item["log_id"])
        before = get_log(thread_id, log_id)
        if before is None:
            continue
        counts = (before.n_res, before.n_like)
        _persist_log_counts(thread_id, log_id)
        after = get_log(thread_id, log_id)
        if after and (after.n_res, after.n_like) != counts:
            print(
                f"  [counts] {log_id}: "
                f"nRes {counts[0]}→{after.n_res}, nLike {counts[1]}→{after.n_like}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-endpoint-url", default=os.getenv("SOURCE_DDB_ENDPOINT_URL", ""))
    parser.add_argument(
        "--source-region",
        default=os.getenv("SOURCE_AWS_REGION", os.getenv("AWS_REGION", "ap-northeast-1")),
    )
    parser.add_argument("--source-profile", default=os.getenv("SOURCE_AWS_PROFILE", ""))
    parser.add_argument("--table-suffix", default="", help='old table suffix, e.g. "_test"')
    parser.add_argument("--only", action="append", choices=KINDS, help="restrict imported kinds")
    parser.add_argument(
        "--apply",
        "--execute",
        dest="apply",
        action="store_true",
        help="actually write to the destination table (default is dry-run)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation when applying (for CI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and map, write nothing (this is the default; overrides --apply)",
    )
    parser.add_argument("--limit", type=int, default=None, help="max items per kind")
    parser.add_argument(
        "--recompute-counts",
        action="store_true",
        help="recalculate nRes/nLike after import instead of trusting source values",
    )
    args = parser.parse_args()

    # Safety default (issue #29): never write unless --apply was given
    # explicitly, and --dry-run always wins.
    dry_run = args.dry_run or not args.apply
    destination_table = os.getenv("DDB_TABLE_NAME", "algodoo-main")
    source_desc = (
        args.source_endpoint_url
        or (f"profile {args.source_profile}" if args.source_profile else "ambient AWS credentials")
    )
    if not dry_run:
        print(f"source:      {source_desc} (region {args.source_region})")
        print(f"destination: DynamoDB table {destination_table!r}")
        if not args.yes:
            try:
                answer = input("Type 'yes' to write to the destination table: ")
            except EOFError:
                answer = ""
            if answer.strip().lower() != "yes":
                print("aborted (no writes performed)")
                return
    else:
        print("dry-run mode: no writes will be performed (pass --apply to write)")

    session_kwargs = {"region_name": args.source_region}
    if args.source_profile:
        session_kwargs["profile_name"] = args.source_profile
    session = boto3.Session(**session_kwargs)
    resource_kwargs = {}
    if args.source_endpoint_url:
        resource_kwargs["endpoint_url"] = args.source_endpoint_url
    source = session.resource("dynamodb", **resource_kwargs)

    if not dry_run:
        init_table()

    kinds = [kind for kind in KINDS if not args.only or kind in args.only]
    for kind in kinds:
        table = source.Table(f"{kind}{args.table_suffix}")
        stats = migrate_kind(table, kind, dry_run=dry_run, limit=args.limit)
        mode = "dry-run" if dry_run else "imported"
        print(
            f"{kind}: read={stats['read']} written={stats['written']} "
            f"errors={stats['errors']} ({mode})"
        )

    if args.recompute_counts and not dry_run:
        print("recomputing nRes/nLike ...")
        recompute_log_counts(source.Table(f"log{args.table_suffix}"))
        recompute_counts()

    print("migration done")


if __name__ == "__main__":
    main()
