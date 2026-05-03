from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from algodoo_data.repository import (
    create_like,
    create_log,
    create_thread,
    delete_log,
    delete_thread,
    get_like_summary,
    get_thread,
    list_logs,
    list_responses,
    list_threads,
    log_payload,
    thread_payload,
    update_log_details,
    update_thread_details,
)
from algodoo_domain.models import LegacyRoute, LikeType

router = APIRouter(prefix="/api")


class CreateThreadBody(BaseModel):
    title: str = Field(default="", max_length=64)
    content: str = Field(default="", max_length=32000)
    user_name: str = Field(default="anonymous", max_length=64)
    user_id: str | None = Field(default=None, max_length=128)
    file_keys: list[str] = Field(default_factory=list)


class UpdateThreadBody(BaseModel):
    title: str = Field(default="", max_length=64)
    content: str = Field(default="", max_length=32000)
    file_keys: list[str] = Field(default_factory=list)


class CreateLogBody(BaseModel):
    content: str = Field(max_length=32000)
    user_name: str = Field(default="anonymous", max_length=64)
    user_id: str = Field(default="anonymous", max_length=128)
    response_to: str | None = Field(default=None, max_length=128)


class UpdateLogBody(BaseModel):
    content: str = Field(max_length=32000)


class CreateLikeBody(BaseModel):
    user_id: str = Field(max_length=128)
    like_type: LikeType


@router.get("/threads/{route}")
def api_list_threads(route: LegacyRoute) -> dict[str, list[dict]]:
    items = [thread_payload(thread) for thread in list_threads(route)]
    return {"submitions": items}


@router.post("/threads/{route}")
def api_create_thread(route: LegacyRoute, body: CreateThreadBody) -> dict[str, object]:
    thread = create_thread(
        route=route,
        title=body.title,
        content=body.content,
        user_name=body.user_name,
        user_id=body.user_id,
        file_keys=body.file_keys,
    )
    return {"result": True, "thread": thread_payload(thread)}


@router.get("/threads/{route}/{thread_id}")
def api_get_thread(route: LegacyRoute, thread_id: str) -> dict[str, dict]:
    thread = get_thread(route, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"thread_info": thread_payload(thread)}


@router.put("/threads/{route}/{thread_id}")
def api_update_thread(route: LegacyRoute, thread_id: str, body: UpdateThreadBody) -> dict[str, object]:
    thread = update_thread_details(route, thread_id, body.title, body.content, body.file_keys)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {"result": True, "thread_info": thread_payload(thread)}


@router.delete("/threads/{route}/{thread_id}")
def api_delete_thread(route: LegacyRoute, thread_id: str) -> dict[str, bool]:
    delete_thread(route, thread_id)
    return {"result": True}


@router.get("/bbslogs/{thread_id}")
def api_list_logs(thread_id: str) -> dict[str, list[dict]]:
    items = [log_payload(log) for log in list_logs(thread_id)]
    return {"submitions": items}


@router.post("/bbslogs/{thread_id}")
def api_create_log(thread_id: str, body: CreateLogBody) -> dict[str, object]:
    log = create_log(
        thread_id=thread_id,
        content=body.content,
        user_name=body.user_name,
        user_id=body.user_id,
        response_to=body.response_to,
    )
    return {"result": True, "log": log_payload(log)}


@router.get("/bbslogs/{thread_id}/{log_id}")
def api_get_log(thread_id: str, log_id: str) -> dict[str, dict]:
    for log in list_logs(thread_id):
        if log.log_id == log_id:
            return {"log_info": log_payload(log)}
    raise HTTPException(status_code=404, detail="log not found")


@router.put("/bbslogs/{thread_id}/{log_id}")
def api_update_log(thread_id: str, log_id: str, body: UpdateLogBody) -> dict[str, object]:
    log = update_log_details(thread_id, log_id, body.content)
    if log is None:
        raise HTTPException(status_code=404, detail="log not found")
    return {"result": True, "log": log_payload(log)}


@router.delete("/bbslogs/{thread_id}/{log_id}")
def api_delete_log(thread_id: str, log_id: str) -> dict[str, bool]:
    delete_log(thread_id, log_id)
    return {"result": True}


@router.get("/bbslogs/{thread_id}/{log_id}/responses")
def api_list_responses(thread_id: str, log_id: str) -> dict[str, list[dict]]:
    items = [log_payload(log) for log in list_responses(thread_id, log_id)]
    return {"responses": items}


@router.get("/like/{post_id}")
def api_get_likes(post_id: str) -> dict[str, int]:
    return {"likes": get_like_summary(post_id)}


@router.post("/like/{post_id}")
def api_create_like(post_id: str, body: CreateLikeBody) -> dict[str, dict[str, int]]:
    return {"likes": create_like(post_id, body.user_id, body.like_type)}
