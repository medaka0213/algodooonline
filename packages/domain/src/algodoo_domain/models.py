from dataclasses import dataclass, field
from enum import StrEnum


class LegacyRoute(StrEnum):
    BBS = "BBS"
    WIKI = "WIKI"
    DATA = "DATA"
    IMAGE = "IMAGE"


class LikeType(StrEnum):
    GOOD = "good"
    BAD = "bad"


@dataclass(slots=True)
class Thread:
    route: LegacyRoute
    thread_id: str
    user_name: str
    title: str = ""
    content: str = ""
    user_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    n_res: int = 0
    n_like: int = 0
    filedata: list[str] = field(default_factory=list)
    is_edited: bool = False
    is_deleted: bool = False
    v1_id: str | None = None
    v1_user_id: str | None = None
    v1_user_name: str | None = None


@dataclass(slots=True)
class Log:
    thread_id: str
    log_id: str
    user_id: str
    user_name: str = "anonymous"
    content: str = ""
    created_at: str = ""
    updated_at: str = ""
    response_to: str | None = None
    n_res: int = 0
    n_like: int = 0
    is_edited: bool = False
    is_deleted: bool = False
    v1_id: str | None = None
    v1_res_id: str | None = None
    v1_thread_id: str | None = None
    v1_user_id: str | None = None
    v1_user_name: str | None = None


@dataclass(slots=True)
class Like:
    post_id: str
    user_id: str
    like_type: LikeType
    created_at: str = ""
    is_deleted: bool = False


@dataclass(slots=True)
class UserProfile:
    username: str
    sub: str
    email: str
    email_verified: bool
    version: str = "2"
    v1_password: str | None = None
