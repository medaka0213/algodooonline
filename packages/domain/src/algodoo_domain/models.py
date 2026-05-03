from dataclasses import dataclass, field
from enum import Enum


class LegacyRoute(str, Enum):
    BBS = "BBS"
    WIKI = "WIKI"
    DATA = "DATA"
    IMAGE = "IMAGE"


class LikeType(str, Enum):
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
    file_keys: list[str] = field(default_factory=list)


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


@dataclass(slots=True)
class Like:
    post_id: str
    user_id: str
    like_type: LikeType
    created_at: str = ""


@dataclass(slots=True)
class UserProfile:
    username: str
    sub: str
    email: str
    email_verified: bool
    version: str = "2"
    v1_password: str | None = None

