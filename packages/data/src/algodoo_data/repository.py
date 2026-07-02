import hashlib
import time
from collections import Counter
from datetime import UTC, datetime
from operator import attrgetter

from algodoo_domain.models import LegacyRoute, Like, LikeType, Log, Thread, UserProfile
from ddb_single import Query

from algodoo_data.single_table import (
    TABLE,
    LikeRecord,
    LogRecord,
    ThreadRecord,
    UserRecord,
    create_log_id,
    create_thread_id,
    like_to_record,
    log_to_record,
    thread_to_record,
    user_to_record,
)

SORT_KEYS = {
    "NEWEST_UPDATED",
    "NEWEST_CREATED",
    "OLDEST_UPDATED",
    "OLDEST_CREATED",
    "BEST",
    "MOST_RESPONSED",
}


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


def _bool(item: dict, key: str) -> bool:
    return bool(item.get(key, False))


def thread_from_item(item: dict) -> Thread:
    return Thread(
        route=LegacyRoute(item["route"].upper()),
        thread_id=item["thread_id"],
        user_name=item.get("user_name") or "anonymous",
        title=item.get("title") or "",
        content=item.get("content") or "",
        user_id=item.get("user_id") or "anonymous",
        created_at=item.get("created_at") or "",
        updated_at=item.get("updated_at") or "",
        n_res=int(item.get("n_res") or 0),
        n_like=int(item.get("n_like") or 0),
        filedata=item.get("filedata") or item.get("file_keys") or [],
        is_edited=_bool(item, "is_edited"),
        is_deleted=_bool(item, "is_deleted"),
        v1_id=item.get("v1_id"),
        v1_user_id=item.get("v1_user_id"),
        v1_user_name=item.get("v1_user_name"),
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
        response_to=item.get("response_to") or None,
        n_res=int(item.get("n_res") or 0),
        n_like=int(item.get("n_like") or 0),
        is_edited=_bool(item, "is_edited"),
        is_deleted=_bool(item, "is_deleted"),
        v1_id=item.get("v1_id"),
        v1_res_id=item.get("v1_res_id"),
        v1_thread_id=item.get("v1_thread_id"),
        v1_user_id=item.get("v1_user_id"),
        v1_user_name=item.get("v1_user_name"),
    )


def user_from_item(item: dict) -> UserProfile:
    return UserProfile(
        username=item["username"],
        sub=item.get("sub") or item["username"],
        email=item.get("email") or "",
        email_verified=bool(item.get("email_verified")),
        version=item.get("version") or "2",
        v1_password=item.get("v1_password"),
        v1_id=item.get("v1_id"),
        v1_name=item.get("v1_name"),
    )


def _tokens(query_text: str | None) -> list[str]:
    if not query_text:
        return []
    return [token.lower() for token in query_text.replace("　", " ").split() if token.strip()]


def _matches(text: str, tokens: list[str]) -> bool:
    lowered = text.lower()
    return all(token in lowered for token in tokens)


def _sort_threads(threads: list[Thread], sort: str | None) -> list[Thread]:
    selected = sort if sort in SORT_KEYS else "NEWEST_UPDATED"
    reverse = selected in {"NEWEST_UPDATED", "NEWEST_CREATED", "BEST", "MOST_RESPONSED"}
    if selected.endswith("UPDATED"):
        key = attrgetter("updated_at")
    elif selected.endswith("CREATED"):
        key = attrgetter("created_at")
    elif selected == "BEST":
        key = attrgetter("n_like")
    else:
        key = attrgetter("n_res")
    return sorted(threads, key=key, reverse=reverse)


def _sort_logs(logs: list[Log], sort: str | None) -> list[Log]:
    selected = sort if sort in SORT_KEYS else "NEWEST_UPDATED"
    reverse = selected in {"NEWEST_UPDATED", "NEWEST_CREATED", "BEST", "MOST_RESPONSED"}
    if selected.endswith("UPDATED"):
        key = attrgetter("updated_at")
    elif selected.endswith("CREATED"):
        key = attrgetter("created_at")
    elif selected == "BEST":
        key = attrgetter("n_like")
    else:
        key = attrgetter("n_res")
    return sorted(logs, key=key, reverse=reverse)


def list_threads(
    route: LegacyRoute,
    query_text: str | None = None,
    sort: str | None = None,
    include_deleted: bool = False,
) -> list[Thread]:
    items = query().model(ThreadRecord).search(ThreadRecord.route.eq(route.value))
    threads = [thread_from_item(item) for item in items]
    if not include_deleted:
        threads = [thread for thread in threads if not thread.is_deleted]
    tokens = _tokens(query_text)
    if tokens:
        threads = [
            thread
            for thread in threads
            if _matches(f"{thread.title}\n{thread.content}", tokens)
        ]
    return _sort_threads(threads, sort)


def get_thread(route: LegacyRoute, thread_id: str, include_deleted: bool = False) -> Thread | None:
    items = query().model(ThreadRecord).search(
        ThreadRecord.thread_id.eq(thread_id),
        ThreadRecord.route.eq(route.value),
        limit=1,
    )
    if not items:
        return None
    thread = thread_from_item(items[0])
    if thread.is_deleted and not include_deleted:
        return None
    return thread


def list_logs(
    thread_id: str,
    query_text: str | None = None,
    sort: str | None = None,
    include_deleted: bool = True,
) -> list[Log]:
    items = query().model(LogRecord).search(LogRecord.thread_id.eq(thread_id))
    logs = [log_from_item(item) for item in items]
    if not include_deleted:
        logs = [log for log in logs if not log.is_deleted]
    tokens = _tokens(query_text)
    if tokens:
        by_id = {log.log_id: log for log in logs}
        matched = {log.log_id for log in logs if _matches(log.content, tokens)}
        stack = list(matched)
        while stack:
            lid = stack.pop()
            parent_id = by_id[lid].response_to if lid in by_id else None
            if parent_id and parent_id in by_id and parent_id not in matched:
                matched.add(parent_id)
                stack.append(parent_id)
        logs = [log for log in logs if log.log_id in matched]
    return _sort_logs(logs, sort)


def list_responses(thread_id: str, log_id: str, include_deleted: bool = True) -> list[Log]:
    items = query().model(LogRecord).search(
        LogRecord.thread_id.eq(thread_id),
        LogRecord.response_to.eq(log_id),
    )
    logs = [log_from_item(item) for item in items]
    if not include_deleted:
        logs = [log for log in logs if not log.is_deleted]
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
    counts = Counter(item["like_type"] for item in items if not item.get("is_deleted"))
    good = counts.get(LikeType.GOOD.value, 0)
    bad = counts.get(LikeType.BAD.value, 0)
    return {"n_good": good, "n_bad": bad, "n_total": good - bad}


def get_own_like(post_id: str, user_id: str) -> dict:
    items = query().model(LikeRecord).search(
        LikeRecord.post_id.eq(post_id),
        LikeRecord.user_id.eq(user_id),
        limit=1,
    )
    if not items or items[0].get("is_deleted"):
        return {}
    return {
        "post_id": items[0]["post_id"],
        "user_id": items[0]["user_id"],
        "type": items[0]["like_type"],
        "isDeleted": False,
    }


def get_own_likes_batch(post_ids: list[str], user_id: str) -> dict[str, dict]:
    if not post_ids or not user_id:
        return {}
    post_id_set = set(post_ids)
    all_items = query().model(LikeRecord).search(LikeRecord.user_id.eq(user_id))
    results: dict[str, dict] = {pid: {} for pid in post_ids}
    for item in all_items:
        pid = item.get("post_id")
        if pid in post_id_set and not item.get("is_deleted"):
            results[pid] = {
                "post_id": pid,
                "user_id": item["user_id"],
                "type": item["like_type"],
                "isDeleted": False,
            }
    return results


def _persist_thread_counts(thread_id: str, touch_updated: bool = True) -> None:
    items = query().model(ThreadRecord).search(ThreadRecord.thread_id.eq(thread_id), limit=1)
    if not items:
        return
    item = items[0]
    route = LegacyRoute(item["route"].upper())
    summary = get_like_summary(thread_id)
    logs = list_logs(thread_id, include_deleted=False)
    updated = thread_from_item(item)
    updated.n_res = len(logs)
    updated.n_like = summary["n_total"]
    if touch_updated:
        updated.updated_at = utcnow()
    updated.route = route
    query().model(thread_to_record(updated)).update()


def _persist_log_counts(thread_id: str, log_id: str) -> None:
    current = get_log(thread_id, log_id)
    if current is None:
        return
    summary = get_like_summary(log_id)
    current.n_like = summary["n_total"]
    current.n_res = len(list_responses(thread_id, log_id, include_deleted=False))
    query().model(log_to_record(current)).update()


def create_thread(
    route: LegacyRoute,
    title: str,
    content: str,
    user_name: str,
    user_id: str | None = None,
    filedata: list[str] | None = None,
    file_keys: list[str] | None = None,
) -> Thread:
    now = utcnow()
    thread = Thread(
        route=route,
        thread_id=create_thread_id(route.value),
        user_name=user_name,
        title=title,
        content=content,
        user_id=user_id or user_name,
        created_at=now,
        updated_at=now,
        filedata=filedata if filedata is not None else file_keys or [],
    )
    record = thread_to_record(thread)
    query().model(record).create()
    return thread_from_item(record.data)


def update_thread_details(
    route: LegacyRoute,
    thread_id: str,
    title: str,
    content: str,
    filedata: list[str] | None = None,
) -> Thread | None:
    current = get_thread(route, thread_id)
    if current is None:
        return None
    current.title = title
    current.content = content
    if filedata is not None:
        current.filedata = filedata
    current.updated_at = utcnow()
    current.is_edited = True
    query().model(thread_to_record(current)).update()
    return current


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
        response_to=response_to or None,
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
    current.content = content
    current.updated_at = utcnow()
    current.is_edited = True
    query().model(log_to_record(current)).update()
    return current


def delete_log(thread_id: str, log_id: str) -> None:
    target = get_log(thread_id, log_id)
    if target is None:
        return
    target.is_deleted = True
    target.updated_at = utcnow()
    query().model(log_to_record(target)).update()
    _persist_thread_counts(thread_id)
    if target.response_to:
        _persist_log_counts(thread_id, target.response_to)


def delete_thread(route: LegacyRoute, thread_id: str) -> None:
    target = get_thread(route, thread_id, include_deleted=True)
    if target is None:
        return
    target.is_deleted = True
    target.updated_at = utcnow()
    query().model(thread_to_record(target)).update()
    for log in list_logs(thread_id):
        log.is_deleted = True
        query().model(log_to_record(log)).update()


def create_like(post_id: str, user_id: str, like_type: LikeType) -> dict[str, int]:
    like = Like(post_id=post_id, user_id=user_id, like_type=like_type, created_at=utcnow())
    query().model(like_to_record(like)).update()
    _refresh_post_like_counts(post_id)
    return get_like_summary(post_id)


def delete_like(post_id: str, user_id: str) -> dict[str, int]:
    like = get_own_like(post_id, user_id)
    if like:
        deleted = Like(
            post_id=post_id,
            user_id=user_id,
            like_type=LikeType(like["type"]),
            created_at=utcnow(),
            is_deleted=True,
        )
        query().model(like_to_record(deleted)).update()
    _refresh_post_like_counts(post_id)
    return get_like_summary(post_id)


def _refresh_post_like_counts(post_id: str) -> None:
    if post_id.count("_") >= 2:
        thread_id = post_id.rsplit("_", 1)[0]
        _persist_log_counts(thread_id, post_id)
        _persist_thread_counts(thread_id, touch_updated=False)
    else:
        _persist_thread_counts(post_id, touch_updated=False)


def create_user(
    username: str,
    email: str,
    sub: str | None = None,
    email_verified: bool = True,
    version: str = "2",
    v1_password: str | None = None,
    v1_id: str | None = None,
    v1_name: str | None = None,
) -> UserProfile:
    user = UserProfile(
        username=username,
        sub=sub or f"local-{username}",
        email=email,
        email_verified=email_verified,
        version=version,
        v1_password=v1_password,
        v1_id=v1_id,
        v1_name=v1_name,
    )
    query().model(user_to_record(user)).update()
    return user


def get_user(username: str) -> UserProfile | None:
    items = query().model(UserRecord).search(UserRecord.username.eq(username), limit=1)
    if not items:
        return None
    return user_from_item(items[0])


def signin_user(username: str, password: str) -> dict[str, bool]:
    user = get_user(username)
    if user is None:
        return {"result": True, "isV2": True, "isV1": False}
    if user.version == "1" or user.v1_password:
        digest = hashlib.sha512(password.encode()).hexdigest()
        return {"result": True, "isV2": False, "isV1": user.v1_password == digest}
    return {"result": True, "isV2": True, "isV1": False}


def upsert_user_from_claims(claims: dict) -> UserProfile:
    """Merge verified id-token claims into the user record (old POST /user/update)."""
    username = str(claims.get("name") or claims.get("cognito:username") or "").strip()
    username = username or "anonymous"
    existing = get_user(username)
    user = UserProfile(
        username=username,
        sub=str(claims.get("sub") or (existing.sub if existing else f"local-{username}")),
        email=str(claims.get("email") or (existing.email if existing else "")),
        email_verified=bool(
            claims.get("email_verified", existing.email_verified if existing else False)
        ),
        version="2",
        v1_password=existing.v1_password if existing else None,
        v1_id=existing.v1_id if existing else None,
        v1_name=existing.v1_name if existing else None,
    )
    query().model(user_to_record(user)).update()
    return user


def seed_demo_data() -> None:
    if TABLE.all_items(pk_only=True):
        return

    create_user(username="demo-user", email="demo@example.invalid", sub="user-demo")
    created_threads: list[Thread] = []
    for route, title, content, files in [
        (
            LegacyRoute.BBS,
            "Algodoo 作品相談スレッド",
            "シーン作成、スクリプト、物理挙動の相談はこちら。",
            [],
        ),
        (
            LegacyRoute.WIKI,
            "よく使う操作メモ",
            "## 操作メモ\n\nツール、ショートカット、素材管理のメモをまとめます。",
            [],
        ),
        (
            LegacyRoute.IMAGE,
            "画像つき作品紹介",
            "画像を添えて作品の見た目を共有します。",
            ["https://placehold.co/640x360.jpg?text=Algodoo"],
        ),
        (
            LegacyRoute.DATA,
            "サンプルデータ置き場",
            "PHZ や PHN の共有に使う場所です。",
            ["DATA/sample.phz", "DATA/sample_thumb.png"],
        ),
    ]:
        created_threads.append(
            create_thread(
                route=route,
                title=title,
                content=content,
                user_name="demo-user",
                filedata=files,
            )
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
    return {
        "route": thread.route.value,
        "thread_id": thread.thread_id,
        "updated_at": thread.updated_at,
        "created_at": thread.created_at,
        "user_id": thread.user_id,
        "user_name": thread.user_name,
        "title": thread.title,
        "content": thread.content,
        "nRes": thread.n_res,
        "nLike": thread.n_like,
        "filedata": thread.filedata,
        "file_keys": thread.filedata,
        "isEdited": thread.is_edited,
        "isDeleted": thread.is_deleted,
        "v1_id": thread.v1_id,
        "v1_userID": thread.v1_user_id,
        "v1_userName": thread.v1_user_name,
    }


def log_payload(log: Log) -> dict:
    return {
        "thread_id": log.thread_id,
        "log_id": log.log_id,
        "response_to": log.response_to or "",
        "updated_at": log.updated_at,
        "created_at": log.created_at,
        "user_id": log.user_id,
        "user_name": log.user_name,
        "content": log.content,
        "nRes": log.n_res,
        "nLike": log.n_like,
        "isEdited": log.is_edited,
        "isDeleted": log.is_deleted,
        "v1_id": log.v1_id,
        "v1_resID": log.v1_res_id,
        "v1_threadID": log.v1_thread_id,
        "v1_userID": log.v1_user_id,
        "v1_userName": log.v1_user_name,
    }


def user_payload(user: UserProfile) -> dict:
    return {
        "Username": user.username,
        "sub": user.sub,
        "email": user.email,
        "email_verified": user.email_verified,
        "version": user.version,
        "v1_id": user.v1_id,
        "v1_name": user.v1_name,
    }
