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
    update_user_from_token,
    user_payload,
)
from algodoo_domain.models import LegacyRoute, LikeType
from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter()


def _submission(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("submition") or body.get("submission") or body


def _result_error(errors: dict[str, str]) -> dict[str, object]:
    return {"result": False, "errors": errors}


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


def _route(route: str) -> LegacyRoute:
    try:
        return LegacyRoute(route.upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="route not found") from exc


@router.get("/threads/{route}")
def api_list_threads(route: str) -> dict[str, list[dict]]:
    items = [thread_payload(thread) for thread in list_threads(_route(route))]
    return {"submitions": items}


@router.post("/threads/{route}")
def api_create_thread(
    route: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_thread(data):
        return errors
    thread = create_thread(
        route=_route(route),
        title=str(data.get("title", "")).strip(),
        content=str(data.get("content", "")).strip(),
        user_name=str(data.get("user_name", "")).strip(),
        user_id=str(data.get("user_id", data.get("user_name", "anonymous"))),
        filedata=_filedata(data),
    )
    return {"result": True, "thread": thread_payload(thread)}


@router.get("/threads/{route}/{thread_id}")
def api_get_thread(route: str, thread_id: str) -> dict[str, dict]:
    thread = get_thread(_route(route), thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"thread_info": thread_payload(thread)}


@router.put("/threads/{route}/{thread_id}")
def api_update_thread(
    route: str,
    thread_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_thread(data, editing=True):
        return errors
    thread = update_thread_details(
        _route(route),
        thread_id,
        str(data.get("title", "")).strip(),
        str(data.get("content", "")).strip(),
        _filedata(data),
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"result": True, "thread_info": thread_payload(thread)}


@router.delete("/threads/{route}/{thread_id}")
def api_delete_thread(route: str, thread_id: str) -> dict[str, bool]:
    delete_thread(_route(route), thread_id)
    return {"result": True}


@router.get("/bbslogs/{thread_id}")
def api_list_logs(thread_id: str) -> dict[str, list[dict]]:
    items = [log_payload(log) for log in list_logs(thread_id)]
    return {"submitions": items}


@router.post("/bbslogs/{thread_id}")
def api_create_log(
    thread_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_log(data):
        return errors
    log = create_log(
        thread_id=thread_id,
        content=str(data.get("content", "")).strip(),
        user_name=str(data.get("user_name", "anonymous")),
        user_id=str(data.get("user_id", data.get("user_name", "anonymous"))),
    )
    return {"result": True, "log": log_payload(log)}


@router.get("/bbslogs/{thread_id}/{log_id}")
def api_get_log(thread_id: str, log_id: str) -> dict[str, dict]:
    log = get_log(thread_id, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="log not found")
    return {"log_info": log_payload(log)}


@router.get("/bbslogs/{thread_id}/{log_id}/responses")
def api_list_responses(thread_id: str, log_id: str) -> dict[str, list[dict]]:
    items = [log_payload(log) for log in list_responses(thread_id, log_id)]
    return {"responses": items}


@router.post("/bbslogs/{thread_id}/{log_id}")
def api_create_response(
    thread_id: str,
    log_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_log(data):
        return errors
    log = create_log(
        thread_id=thread_id,
        content=str(data.get("content", "")).strip(),
        user_name=str(data.get("user_name", "anonymous")),
        user_id=str(data.get("user_id", data.get("user_name", "anonymous"))),
        response_to=log_id,
    )
    return {"result": True, "log": log_payload(log)}


@router.put("/bbslogs/{thread_id}/{log_id}")
def api_update_log(
    thread_id: str,
    log_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    data = _submission(body)
    if errors := _validate_log(data):
        return errors
    log = update_log_details(thread_id, log_id, str(data.get("content", "")).strip())
    if log is None:
        raise HTTPException(status_code=404, detail="log not found")
    return {"result": True, "log": log_payload(log)}


@router.delete("/bbslogs/{thread_id}/{log_id}")
def api_delete_log(thread_id: str, log_id: str) -> dict[str, bool]:
    delete_log(thread_id, log_id)
    return {"result": True}


@router.post("/like/own/batch")
def api_own_likes_batch(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, object]:
    user_id = str(body.get("user_id") or request.cookies.get("algodoo_sub") or "anonymous")
    likes = [get_own_like(str(post_id), user_id) for post_id in body.get("post_ids", [])]
    return {"result": True, "likes": likes}


@router.get("/like/{post_id}")
def api_get_likes(post_id: str) -> dict[str, dict[str, int]]:
    return {"likes": get_like_summary(post_id)}


@router.get("/like/{post_id}/own")
def api_get_own_like(request: Request, post_id: str) -> dict[str, dict]:
    user_id = request.cookies.get("algodoo_sub") or "anonymous"
    return {"like": get_own_like(post_id, user_id)}


@router.post("/like")
def api_create_like(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, bool]:
    create_like(
        str(body.get("post_id", "")),
        str(body.get("user_id", "anonymous")),
        LikeType(str(body.get("type", "good"))),
    )
    return {"result": True}


@router.delete("/like")
def api_delete_like(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, bool]:
    delete_like(str(body.get("post_id", "")), str(body.get("user_id", "anonymous")))
    return {"result": True}


@router.post("/user")
def api_create_user(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, bool]:
    data = _submission(body)
    create_user(
        username=str(data.get("Username") or data.get("username") or ""),
        email=str(data.get("email") or ""),
        sub=str(data.get("sub") or data.get("Username") or ""),
        email_verified=bool(data.get("email_verified", True)),
    )
    return {"result": True}


@router.post("/user/signin")
def api_signin_user(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, bool]:
    data = _submission(body)
    return signin_user(str(data.get("Username", "")), str(data.get("v1_password", "")))


@router.post("/user/update")
def api_update_user(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, object]:
    data = _submission(body)
    user = update_user_from_token(str(data.get("idToken", "")))
    return {"result": True, "user_info": user_payload(user)}
