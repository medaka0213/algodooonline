from ulid import ULID

from algodoo_domain.models import Like, Log, Thread, UserProfile
from ddb_single import BaseModel, DBField, Table
from ddb_single.table import FieldType

from algodoo_data.config import get_data_settings

settings = get_data_settings()


def build_table() -> Table:
    kwargs = {
        "table_name": settings.table_name,
        "region_name": settings.aws_region,
    }
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return Table(**kwargs)


TABLE = build_table()


def join_key(*parts: str) -> str:
    return "#".join(part for part in parts if part)


def create_thread_id(route: str) -> str:
    return f"{route}_{str(ULID())}"


def create_log_id(thread_id: str) -> str:
    return f"{thread_id}_{str(ULID())}"


class ThreadRecord(BaseModel):
    __table__ = TABLE
    __model_name__ = "thread"

    thread_id = DBField(unique_key=True, nullable=False)
    route = DBField(search_key=True, nullable=False, ignore_case=True)
    route_updated = DBField(search_key=True, nullable=False)
    user_id = DBField(search_key=True)
    user_name = DBField(search_key=True, ignore_case=True)
    title = DBField()
    content = DBField()
    created_at = DBField(search_key=True, nullable=False)
    updated_at = DBField(search_key=True, nullable=False)
    n_res = DBField(type=FieldType.NUMBER, default=0)
    n_like = DBField(type=FieldType.NUMBER, default=0)
    filedata = DBField(type=FieldType.LIST, default_factory=lambda _model: [])
    file_keys = DBField(type=FieldType.LIST, default_factory=lambda _model: [])
    is_edited = DBField(type=FieldType.BOOLEAN, default=False)
    is_deleted = DBField(type=FieldType.BOOLEAN, default=False)
    v1_id = DBField()
    v1_user_id = DBField()
    v1_user_name = DBField()


class LogRecord(BaseModel):
    __table__ = TABLE
    __model_name__ = "log"

    log_id = DBField(unique_key=True, nullable=False)
    thread_id = DBField(search_key=True, nullable=False)
    thread_created = DBField(search_key=True, nullable=False)
    thread_response = DBField(search_key=True)
    user_id = DBField(search_key=True, nullable=False)
    user_name = DBField(search_key=True, ignore_case=True)
    response_to = DBField(search_key=True)
    content = DBField()
    created_at = DBField(search_key=True, nullable=False)
    updated_at = DBField(search_key=True, nullable=False)
    n_res = DBField(type=FieldType.NUMBER, default=0)
    n_like = DBField(type=FieldType.NUMBER, default=0)
    is_edited = DBField(type=FieldType.BOOLEAN, default=False)
    is_deleted = DBField(type=FieldType.BOOLEAN, default=False)
    v1_id = DBField()
    v1_res_id = DBField()
    v1_thread_id = DBField()
    v1_user_id = DBField()
    v1_user_name = DBField()


class LikeRecord(BaseModel):
    __table__ = TABLE
    __model_name__ = "like"

    like_key = DBField(unique_key=True, nullable=False)
    post_id = DBField(search_key=True, nullable=False)
    user_id = DBField(search_key=True, nullable=False)
    like_type = DBField(search_key=True, nullable=False)
    post_type = DBField(search_key=True, nullable=False)
    created_at = DBField(search_key=True, nullable=False)
    is_deleted = DBField(type=FieldType.BOOLEAN, default=False)


class UserRecord(BaseModel):
    __table__ = TABLE
    __model_name__ = "user"

    username = DBField(unique_key=True, nullable=False, ignore_case=True)
    sub = DBField(search_key=True, nullable=False)
    email = DBField(search_key=True, nullable=False, ignore_case=True)
    email_verified = DBField(type=FieldType.BOOLEAN, default=False)
    version = DBField(search_key=True, nullable=False)
    v1_password = DBField()
    v1_id = DBField()
    v1_name = DBField()


def thread_to_record(thread: Thread) -> ThreadRecord:
    return ThreadRecord(
        thread_id=thread.thread_id,
        route=thread.route.value,
        route_updated=join_key(thread.route.value, thread.updated_at),
        user_id=thread.user_id,
        user_name=thread.user_name,
        title=thread.title,
        content=thread.content,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        n_res=thread.n_res,
        n_like=thread.n_like,
        filedata=thread.filedata,
        file_keys=thread.filedata,
        is_edited=thread.is_edited,
        is_deleted=thread.is_deleted,
        v1_id=thread.v1_id,
        v1_user_id=thread.v1_user_id,
        v1_user_name=thread.v1_user_name,
    )


def log_to_record(log: Log) -> LogRecord:
    return LogRecord(
        log_id=log.log_id,
        thread_id=log.thread_id,
        thread_created=join_key(log.thread_id, log.created_at),
        thread_response=join_key(log.thread_id, log.response_to) if log.response_to else None,
        user_id=log.user_id,
        user_name=log.user_name,
        response_to=log.response_to,
        content=log.content,
        created_at=log.created_at,
        updated_at=log.updated_at,
        n_res=log.n_res,
        n_like=log.n_like,
        is_edited=log.is_edited,
        is_deleted=log.is_deleted,
        v1_id=log.v1_id,
        v1_res_id=log.v1_res_id,
        v1_thread_id=log.v1_thread_id,
        v1_user_id=log.v1_user_id,
        v1_user_name=log.v1_user_name,
    )


def like_to_record(like: Like) -> LikeRecord:
    return LikeRecord(
        like_key=join_key(like.post_id, like.user_id),
        post_id=like.post_id,
        user_id=like.user_id,
        like_type=like.like_type.value,
        post_type=join_key(like.post_id, like.like_type.value),
        created_at=like.created_at,
        is_deleted=like.is_deleted,
    )


def user_to_record(user: UserProfile) -> UserRecord:
    return UserRecord(
        username=user.username,
        sub=user.sub,
        email=user.email,
        email_verified=user.email_verified,
        version=user.version,
        v1_password=user.v1_password,
        v1_id=user.v1_id,
        v1_name=user.v1_name,
    )
