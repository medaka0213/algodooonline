from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import time

from ddb_single import Query

from algodoo_domain.models import LegacyRoute, Like, LikeType, Log, Thread
from algodoo_data.single_table import (
    LikeRecord,
    LogRecord,
    TABLE,
    ThreadRecord,
    create_log_id,
    create_thread_id,
    like_to_record,
    log_to_record,
    thread_to_record,
)


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def query() -> Query:
    return Query(TABLE)


def init_table() -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            TABLE.init(create_if_not_exists=True)
            TABLE.all_items(pk_only=True)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError("failed to initialize or query the single table") from last_error


def thread_from_item(item: dict) -> Thread:
    return Thread(
        route=LegacyRoute(item["route"].upper()),
        thread_id=item["thread_id"],
        user_name=item.get("user_name") or "anonymous",
        title=item.get("title") or "",
        content=item.get("content") or "",
        user_id=item.get("user_id"),
        created_at=item.get("created_at") or "",
        updated_at=item.get("updated_at") or "",
        n_res=int(item.get("n_res") or 0),
        n_like=int(item.get("n_like") or 0),
        file_keys=item.get("file_keys") or [],
    )


def log_from_item(item: dict) -> Log:
    return Log(
        thread_id=item["thread_id"],
        log_id=item["log_id"],
        user_id=item.get("user_id") or "anonymous",
        user_name=item.get("user_name") or "anonymous",
        content=item.get("content") or "",
        created_at=item.get("created_at") or "",
        updated_at=item.get("updated_at") or "",
        response_to=item.get("response_to"),
        n_res=int(item.get("n_res") or 0),
        n_like=int(item.get("n_like") or 0),
    )


def list_threads(route: LegacyRoute, query_text: str | None = None) -> list[Thread]:
    items = query().model(ThreadRecord).search(ThreadRecord.route.eq(route.value))
    threads = [thread_from_item(item) for item in items]
    if query_text:
        normalized = query_text.lower()
        threads = [
            thread
            for thread in threads
            if normalized in thread.title.lower()
            or normalized in thread.content.lower()
            or normalized in thread.user_name.lower()
        ]
    return sorted(threads, key=lambda item: item.updated_at, reverse=True)


def get_thread(route: LegacyRoute, thread_id: str) -> Thread | None:
    items = query().model(ThreadRecord).search(
        ThreadRecord.thread_id.eq(thread_id),
        ThreadRecord.route.eq(route.value),
        limit=1,
    )
    if not items:
        return None
    return thread_from_item(items[0])


def list_logs(thread_id: str) -> list[Log]:
    items = query().model(LogRecord).search(LogRecord.thread_id.eq(thread_id))
    logs = [log_from_item(item) for item in items]
    return sorted(logs, key=lambda item: item.created_at)


def list_responses(thread_id: str, log_id: str) -> list[Log]:
    items = query().model(LogRecord).search(
        LogRecord.thread_id.eq(thread_id),
        LogRecord.response_to.eq(log_id),
    )
    logs = [log_from_item(item) for item in items]
    return sorted(logs, key=lambda item: item.created_at)


def get_log(thread_id: str, log_id: str) -> Log | None:
    items = query().model(LogRecord).search(
        LogRecord.thread_id.eq(thread_id),
        LogRecord.log_id.eq(log_id),
        limit=1,
    )
    if not items:
        return None
    return log_from_item(items[0])


def get_like_summary(post_id: str) -> dict[str, int]:
    items = query().model(LikeRecord).search(LikeRecord.post_id.eq(post_id))
    counts = Counter(item["like_type"] for item in items)
    good = counts.get(LikeType.GOOD.value, 0)
    bad = counts.get(LikeType.BAD.value, 0)
    return {
        "n_good": good,
        "n_bad": bad,
        "n_total": good - bad,
    }


def _persist_thread_counts(thread_id: str) -> None:
    items = query().model(ThreadRecord).search(ThreadRecord.thread_id.eq(thread_id), limit=1)
    if not items:
        return
    item = items[0]
    route = LegacyRoute(item["route"].upper())
    summary = get_like_summary(thread_id)
    logs = list_logs(thread_id)
    updated = Thread(
        route=route,
        thread_id=item["thread_id"],
        user_name=item.get("user_name") or "anonymous",
        title=item.get("title") or "",
        content=item.get("content") or "",
        user_id=item.get("user_id"),
        created_at=item.get("created_at") or "",
        updated_at=utcnow(),
        n_res=len(logs),
        n_like=summary["n_total"],
        file_keys=item.get("file_keys") or [],
    )
    query().model(thread_to_record(updated)).update()


def _persist_log_counts(thread_id: str, log_id: str) -> None:
    items = query().model(LogRecord).search(
        LogRecord.log_id.eq(log_id),
        LogRecord.thread_id.eq(thread_id),
        limit=1,
    )
    if not items:
        return
    item = items[0]
    summary = get_like_summary(log_id)
    responses = list_responses(thread_id, log_id)
    updated = Log(
        thread_id=item["thread_id"],
        log_id=item["log_id"],
        user_id=item.get("user_id") or "anonymous",
        user_name=item.get("user_name") or "anonymous",
        content=item.get("content") or "",
        created_at=item.get("created_at") or "",
        updated_at=utcnow(),
        response_to=item.get("response_to"),
        n_res=len(responses),
        n_like=summary["n_total"],
    )
    query().model(log_to_record(updated)).update()


def create_thread(
    route: LegacyRoute,
    title: str,
    content: str,
    user_name: str,
    user_id: str | None = None,
    file_keys: list[str] | None = None,
) -> Thread:
    now = utcnow()
    thread = Thread(
        route=route,
        thread_id=create_thread_id(route.value),
        user_name=user_name,
        title=title,
        content=content,
        user_id=user_id,
        created_at=now,
        updated_at=now,
        file_keys=file_keys or [],
    )
    record = thread_to_record(thread)
    query().model(record).create()
    return thread_from_item(record.data)


def update_thread_details(
    route: LegacyRoute,
    thread_id: str,
    title: str,
    content: str,
    file_keys: list[str] | None = None,
) -> Thread | None:
    current = get_thread(route, thread_id)
    if current is None:
        return None
    updated = Thread(
        route=current.route,
        thread_id=current.thread_id,
        user_name=current.user_name,
        title=title,
        content=content,
        user_id=current.user_id,
        created_at=current.created_at,
        updated_at=utcnow(),
        n_res=current.n_res,
        n_like=current.n_like,
        file_keys=file_keys if file_keys is not None else current.file_keys,
    )
    query().model(thread_to_record(updated)).update()
    return updated


def create_log(
    thread_id: str,
    content: str,
    user_name: str,
    user_id: str = "anonymous",
    response_to: str | None = None,
) -> Log:
    now = utcnow()
    log = Log(
        thread_id=thread_id,
        log_id=create_log_id(thread_id),
        user_id=user_id,
        user_name=user_name,
        content=content,
        created_at=now,
        updated_at=now,
        response_to=response_to,
    )
    record = log_to_record(log)
    query().model(record).create()
    _persist_thread_counts(thread_id)
    if response_to:
        _persist_log_counts(thread_id, response_to)
    return log_from_item(record.data)


def update_log_details(thread_id: str, log_id: str, content: str) -> Log | None:
    current = get_log(thread_id, log_id)
    if current is None:
        return None
    updated = Log(
        thread_id=current.thread_id,
        log_id=current.log_id,
        user_id=current.user_id,
        user_name=current.user_name,
        content=content,
        created_at=current.created_at,
        updated_at=utcnow(),
        response_to=current.response_to,
        n_res=current.n_res,
        n_like=current.n_like,
    )
    query().model(log_to_record(updated)).update()
    return updated


def _delete_likes(post_id: str) -> None:
    items = query().model(LikeRecord).search(LikeRecord.post_id.eq(post_id))
    for item in items:
        query().model(LikeRecord).delete_by_unique(item["like_key"])


def delete_log(thread_id: str, log_id: str) -> None:
    target = get_log(thread_id, log_id)
    if target is None:
        return

    logs_to_delete = [
        log for log in list_logs(thread_id) if log.log_id == log_id or log.response_to == log_id
    ]
    for log in logs_to_delete:
        _delete_likes(log.log_id)
        query().model(LogRecord).delete_by_unique(log.log_id)

    _persist_thread_counts(thread_id)
    if target.response_to:
        _persist_log_counts(thread_id, target.response_to)


def delete_thread(route: LegacyRoute, thread_id: str) -> None:
    if get_thread(route, thread_id) is None:
        return
    for log in list_logs(thread_id):
        _delete_likes(log.log_id)
        query().model(LogRecord).delete_by_unique(log.log_id)
    _delete_likes(thread_id)
    query().model(ThreadRecord).delete_by_unique(thread_id)


def create_like(post_id: str, user_id: str, like_type: LikeType) -> dict[str, int]:
    like = Like(
        post_id=post_id,
        user_id=user_id,
        like_type=like_type,
        created_at=utcnow(),
    )
    record = like_to_record(like)
    query().model(record).update()
    if post_id.count("_") >= 2:
        thread_id = post_id.rsplit("_", 1)[0]
        _persist_log_counts(thread_id, post_id)
        _persist_thread_counts(thread_id)
    else:
        _persist_thread_counts(post_id)
    return get_like_summary(post_id)


def seed_demo_data() -> None:
    if TABLE.all_items(pk_only=True):
        return

    created_threads: list[Thread] = []
    for route, title, content in [
        (LegacyRoute.BBS, "Algodoo 作品相談スレッド", "シーン作成、スクリプト、物理挙動の相談はこちら。"),
        (LegacyRoute.WIKI, "よく使う操作メモ", "ツール、ショートカット、素材管理のメモをまとめます。"),
        (LegacyRoute.DATA, "サンプルデータ置き場", "PHZ や画像メタデータの共有に使う場所です。"),
    ]:
        created_threads.append(
            create_thread(route=route, title=title, content=content, user_name="demo-user")
        )

    first_thread = created_threads[0]
    first_log = create_log(
        thread_id=first_thread.thread_id,
        content="新しい車両サスペンションの挙動が跳ねやすいので調整中です。",
        user_name="demo-user",
        user_id="user-demo",
    )
    create_log(
        thread_id=first_thread.thread_id,
        content="ダンパー値を少し上げて、重心を下げると安定しやすいです。",
        user_name="reviewer",
        user_id="user-reviewer",
        response_to=first_log.log_id,
    )
    create_like(first_thread.thread_id, "user-demo", LikeType.GOOD)
    create_like(first_thread.thread_id, "user-reviewer", LikeType.GOOD)
    create_like(first_log.log_id, "user-demo", LikeType.GOOD)


def thread_payload(thread: Thread) -> dict:
    return asdict(thread) | {"route": thread.route.value}


def log_payload(log: Log) -> dict:
    return asdict(log)
