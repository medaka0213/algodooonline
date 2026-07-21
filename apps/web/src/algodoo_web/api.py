import threading
import time
from typing import Any

from algodoo_data.repository import (
    create_like,
    create_log,
    create_thread,
    create_user,
    delete_like,
    delete_log,
    delete_thread,
    get_like_summary,
    get_log,
    get_own_like,
    get_thread,
    list_logs,
    list_responses,
    list_threads,
    log_payload,
    signin_user,
    thread_payload,
    update_log_details,
    update_thread_details,
    upsert_user_from_claims,
    user_payload,
)
from algodoo_data.uploads import validate_thread_filedata
from algodoo_domain.models import LegacyRoute, LikeType
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from algodoo_web.asset_store import normalize_and_persist_filedata
from algodoo_web.auth import get_auth_backend
from algodoo_web.legacy_api_guard import (
    require_configured_api_key,
    require_matching_user_id,
    require_session,
)

router = APIRouter(dependencies=[Depends(require_configured_api_key)])

# Cap for POST /like/own/batch (OWASP A04, issue #19): the web UI batches one
# page of threads/logs at a time, far below this.
MAX_BATCH_POST_IDS = 100

# Sliding-window rate limit for POST /user/signin (OWASP A07, issue #26).
# Keyed on username + direct client IP; in-process only, which matches the
# single-process deployment of this app.
SIGNIN_MAX_ATTEMPTS = 10
SIGNIN_WINDOW_SECONDS = 300.0
_signin_attempts: dict[str, list[float]] = {}
_signin_lock = threading.Lock()


def _check_signin_rate_limit(username: str, client_ip: str) -> None:
    key = f"{username}\n{client_ip}"
    now = time.monotonic()
    with _signin_lock:
        # Opportunistic prune so the map cannot grow without bound.
        if len(_signin_attempts) > 1024:
            for stale in [
                k
                for k, stamps in _signin_attempts.items()
                if not stamps or now - stamps[-1] >= SIGNIN_WINDOW_SECONDS
            ]:
                del _signin_attempts[stale]
        attempts = [t for t in _signin_attempts.get(key, []) if now - t < SIGNIN_WINDOW_SECONDS]
        if len(attempts) >= SIGNIN_MAX_ATTEMPTS:
            _signin_attempts[key] = attempts
            raise HTTPException(
                status_code=429, detail="too many sign-in attempts, try again later"
            )
        attempts.append(now)
        _signin_attempts[key] = attempts


def _session_claims(request: Request) -> dict[str, Any]:
    """Verified claims for the current session (cookie or legacy Bearer token)."""
    token = request.cookies.get("algodoo_idtoken")
    if not token:
        header = (request.headers.get("authorization") or "").strip()
        if header.lower().startswith("bearer "):
            header = header[len("bearer ") :].strip()
        token = header
    claims = get_auth_backend().verify_id_token(token or "")
    if not claims:
        raise HTTPException(status_code=401, detail="authentication required")
    return claims


def _submission(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("submition") or body.get("submission") or body


def _result_error(errors: dict[str, str]) -> dict[str, object]:
    lines = ["Server-side Error"] + [f"{k}: {v}" for k, v in errors.items()]
    return {"result": False, "errors": errors, "message": "\n".join(lines)}


def _validate_thread(data: dict[str, Any], editing: bool = False) -> dict[str, object] | None:
    errors: dict[str, str] = {}
    if not str(data.get("title", "")).strip():
        errors["title"] = "required"
    if len(str(data.get("title", ""))) > 32:
        errors["title"] = "max length is 32"
    if not str(data.get("content", "")).strip():
        errors["content"] = "required"
    if len(str(data.get("content", ""))) > 32000:
        errors["content"] = "max length is 32000"
    if not editing and not str(data.get("user_name", "")).strip():
        errors["user_name"] = "required"
    return _result_error(errors) if errors else None


def _validate_log(data: dict[str, Any]) -> dict[str, object] | None:
    content = str(data.get("content", ""))
    if not content.strip():
        return _result_error({"content": "required"})
    if len(content) > 32000:
        return _result_error({"content": "max length is 32000"})
    return None


def _filedata(data: dict[str, Any]) -> list[str]:
    value = data.get("filedata", data.get("file_keys", []))
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def _optional_filedata(data: dict[str, Any]) -> list[str] | None:
    if "filedata" not in data and "file_keys" not in data:
        return None
    return _filedata(data)


def _route(route: str) -> LegacyRoute:
    try:
        return LegacyRoute(route.upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="route not found") from exc


def _assert_thread_owner(route: LegacyRoute, thread_id: str, sub: str) -> None:
    thread = get_thread(route, thread_id)
    if thread is None or thread.user_id != sub:
        raise HTTPException(status_code=403, detail="not allowed to modify this thread")


def _assert_log_owner(thread_id: str, log_id: str, sub: str) -> None:
    log = get_log(thread_id, log_id)
    if log is None or log.user_id != sub:
        raise HTTPException(status_code=403, detail="not allowed to modify this log")


@router.get("/threads/{route}")
def api_list_threads(route: str) -> dict[str, list[dict]]:
    items = [thread_payload(thread) for thread in list_threads(_route(route))]
    return {"submitions": items}


@router.post("/threads/{route}")
def api_create_thread(
    route: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_thread(data):
        return errors
    uid = str(data.get("user_id", "")).strip() or str(data.get("user_name", "")).strip()
    sub = require_matching_user_id(request, uid or None)
    lr = _route(route)
    files = _filedata(data)
    if err := validate_thread_filedata(lr, files):
        return _result_error({"filedata": err})
    thread = create_thread(
        route=lr,
        title=str(data.get("title", "")).strip(),
        content=str(data.get("content", "")).strip(),
        user_name=str(data.get("user_name", "")).strip(),
        user_id=uid or sub,
        filedata=[],
    )
    keys, nerr = normalize_and_persist_filedata(
        route=lr,
        thread_id=thread.thread_id,
        filedata=files,
    )
    if nerr:
        delete_thread(lr, thread.thread_id)
        return _result_error({"filedata": nerr})
    if keys or files:
        updated = update_thread_details(lr, thread.thread_id, thread.title, thread.content, keys)
        if updated is not None:
            thread = updated
    return {"result": True, "thread": thread_payload(thread)}


@router.get("/threads/{route}/{thread_id}")
def api_get_thread(route: str, thread_id: str) -> dict[str, dict]:
    thread = get_thread(_route(route), thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"thread_info": thread_payload(thread)}


@router.put("/threads/{route}/{thread_id}")
def api_update_thread(
    request: Request,
    route: str,
    thread_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    sub = require_session(request)
    lr = _route(route)
    _assert_thread_owner(lr, thread_id, sub)
    data = _submission(body)
    if errors := _validate_thread(data, editing=True):
        return errors
    files = _optional_filedata(data)
    if files is not None:
        if err := validate_thread_filedata(lr, files):
            return _result_error({"filedata": err})
        keys, nerr = normalize_and_persist_filedata(route=lr, thread_id=thread_id, filedata=files)
        if nerr:
            return _result_error({"filedata": nerr})
        files = keys
    thread = update_thread_details(
        lr,
        thread_id,
        str(data.get("title", "")).strip(),
        str(data.get("content", "")).strip(),
        files,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"result": True, "thread_info": thread_payload(thread)}


@router.delete("/threads/{route}/{thread_id}")
def api_delete_thread(request: Request, route: str, thread_id: str) -> dict[str, bool]:
    sub = require_session(request)
    lr = _route(route)
    _assert_thread_owner(lr, thread_id, sub)
    delete_thread(lr, thread_id)
    return {"result": True}


@router.get("/bbslogs/{thread_id}")
def api_list_logs(thread_id: str, _sub: str = Depends(require_session)) -> dict[str, list[dict]]:
    items = [log_payload(log) for log in list_logs(thread_id)]
    return {"submitions": items}


@router.post("/bbslogs/{thread_id}")
def api_create_log(
    request: Request,
    thread_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_log(data):
        return errors
    uid = str(data.get("user_id", data.get("user_name", "anonymous")))
    require_matching_user_id(request, uid)
    log = create_log(
        thread_id=thread_id,
        content=str(data.get("content", "")).strip(),
        user_name=str(data.get("user_name", "anonymous")),
        user_id=uid,
    )
    return {"result": True, "log": log_payload(log)}


@router.get("/bbslogs/{thread_id}/{log_id}")
def api_get_log(
    thread_id: str, log_id: str, _sub: str = Depends(require_session)
) -> dict[str, dict]:
    log = get_log(thread_id, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="log not found")
    return {"log_info": log_payload(log)}


@router.get("/bbslogs/{thread_id}/{log_id}/responses")
def api_list_responses(
    thread_id: str, log_id: str, _sub: str = Depends(require_session)
) -> dict[str, list[dict]]:
    items = [log_payload(log) for log in list_responses(thread_id, log_id)]
    return {"responses": items}


@router.post("/bbslogs/{thread_id}/{log_id}")
def api_create_response(
    request: Request,
    thread_id: str,
    log_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_log(data):
        return errors
    uid = str(data.get("user_id", data.get("user_name", "anonymous")))
    require_matching_user_id(request, uid)
    log = create_log(
        thread_id=thread_id,
        content=str(data.get("content", "")).strip(),
        user_name=str(data.get("user_name", "anonymous")),
        user_id=uid,
        response_to=log_id,
    )
    return {"result": True, "log": log_payload(log)}


@router.put("/bbslogs/{thread_id}/{log_id}")
def api_update_log(
    request: Request,
    thread_id: str,
    log_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    sub = require_session(request)
    _assert_log_owner(thread_id, log_id, sub)
    data = _submission(body)
    if errors := _validate_log(data):
        return errors
    log = update_log_details(thread_id, log_id, str(data.get("content", "")).strip())
    if log is None:
        raise HTTPException(status_code=404, detail="log not found")
    return {"result": True, "log": log_payload(log)}


@router.delete("/bbslogs/{thread_id}/{log_id}")
def api_delete_log(request: Request, thread_id: str, log_id: str) -> dict[str, bool]:
    sub = require_session(request)
    _assert_log_owner(thread_id, log_id, sub)
    delete_log(thread_id, log_id)
    return {"result": True}


@router.post("/like/own/batch")
def api_own_likes_batch(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    sub = require_session(request)
    user_id = str(body.get("user_id") or sub)
    if user_id != sub:
        raise HTTPException(status_code=403, detail="user_id does not match session")
    post_ids = body.get("post_ids", [])
    if not isinstance(post_ids, list) or len(post_ids) > MAX_BATCH_POST_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"post_ids must be a list of at most {MAX_BATCH_POST_IDS} ids",
        )
    likes = [get_own_like(str(post_id), user_id) for post_id in post_ids]
    return {"result": True, "likes": likes}


@router.get("/like/{post_id}")
def api_get_likes(post_id: str) -> dict[str, dict[str, int]]:
    return {"likes": get_like_summary(post_id)}


@router.get("/like/{post_id}/own")
def api_get_own_like(request: Request, post_id: str) -> dict[str, dict]:
    sub = require_session(request)
    return {"like": get_own_like(post_id, sub)}


@router.post("/like")
def api_create_like(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, bool]:
    uid = str(body.get("user_id", "anonymous"))
    require_matching_user_id(request, uid)
    create_like(
        str(body.get("post_id", "")),
        uid,
        LikeType(str(body.get("type", "good"))),
    )
    return {"result": True}


@router.delete("/like")
def api_delete_like(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, bool]:
    uid = str(body.get("user_id", "anonymous"))
    require_matching_user_id(request, uid)
    delete_like(str(body.get("post_id", "")), uid)
    return {"result": True}


@router.post("/user")
def api_create_user(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, bool]:
    # OWASP A01 (issue #11): identity comes from the verified session token,
    # never from the request body — otherwise any signed-in caller could
    # create/overwrite arbitrary user records (and hijack their sub).
    sub = require_session(request)
    claims = _session_claims(request)
    session_username = str(claims.get("name") or claims.get("cognito:username") or "").strip()
    data = _submission(body)
    body_sub = str(data.get("sub") or "").strip()
    if body_sub and body_sub != sub:
        raise HTTPException(status_code=403, detail="sub does not match session")
    body_username = str(data.get("Username") or data.get("username") or "").strip()
    if body_username and session_username and body_username != session_username:
        raise HTTPException(status_code=403, detail="username does not match session")
    create_user(
        username=session_username or body_username,
        email=str(claims.get("email") or data.get("email") or ""),
        sub=sub,
        email_verified=bool(claims.get("email_verified", data.get("email_verified", True))),
        v1_id=data.get("v1_id"),
        v1_name=data.get("v1_name"),
    )
    return {"result": True}


@router.post("/user/signin")
def api_signin_user(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, bool]:
    data = _submission(body)
    username = str(data.get("Username", ""))
    client_ip = request.client.host if request.client else "unknown"
    # OWASP A07 (issue #26): throttle credential guessing per username+IP.
    _check_signin_rate_limit(username, client_ip)
    # The isV1/isV2 flags reveal whether a username is a legacy v1 account.
    # They are kept intentionally: SPEC §472 and the v1→v2 migration flow
    # (login page redirecting v1 users to /auth/signup/{name}) require them,
    # so the rate limit above is the mitigation for enumeration abuse.
    return signin_user(username, str(data.get("v1_password", "")))


@router.post("/user/update")
def api_update_user(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, object]:
    data = _submission(body)
    claims = get_auth_backend().verify_id_token(str(data.get("idToken", "")))
    if claims is None:
        raise HTTPException(status_code=401, detail="invalid id token")
    user = upsert_user_from_claims(claims)
    return {"result": True, "user_info": user_payload(user)}
