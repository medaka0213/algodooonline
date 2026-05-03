from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from mangum import Mangum

from algodoo_data.repository import (
    create_like,
    create_log,
    create_thread,
    delete_log,
    delete_thread,
    get_like_summary,
    get_thread,
    list_logs,
    list_threads,
    update_log_details,
    update_thread_details,
)
from algodoo_domain.models import LegacyRoute, LikeType
from algodoo_web.api import router as api_router
from algodoo_web.bootstrap import bootstrap_data

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_data()
    yield


app = FastAPI(title="algodooonline", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
handler = Mangum(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "app": "algodooonline"}


def _route_or_404(route: str) -> LegacyRoute:
    try:
        return LegacyRoute(route.upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="route not found") from exc


async def _form_data(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _current_user(request: Request) -> str:
    return request.cookies.get("algodoo_user", "anonymous")


def _file_keys_from_text(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _thread_view_context(
    request: Request,
    route: LegacyRoute,
    thread_id: str | None = None,
) -> dict[str, object]:
    search_query = request.query_params.get("q", "").strip()
    threads = list_threads(route, search_query or None)
    selected_thread = get_thread(route, thread_id) if thread_id else (threads[0] if threads else None)
    logs = list_logs(selected_thread.thread_id) if selected_thread else []
    top_level_logs = [log for log in logs if not log.response_to]
    responses_by_log = {
        log.log_id: [reply for reply in logs if reply.response_to == log.log_id]
        for log in top_level_logs
    }
    like_summary = (
        get_like_summary(selected_thread.thread_id)
        if selected_thread
        else {"n_good": 0, "n_bad": 0, "n_total": 0}
    )
    log_like_summary = {log.log_id: get_like_summary(log.log_id) for log in logs}

    return {
        "routes": list(LegacyRoute),
        "active_route": route,
        "current_user": _current_user(request),
        "search_query": search_query,
        "threads": threads,
        "selected_thread": selected_thread,
        "top_level_logs": top_level_logs,
        "responses_by_log": responses_by_log,
        "like_summary": like_summary,
        "log_like_summary": log_like_summary,
    }


@app.get("/", response_class=HTMLResponse)
def home() -> RedirectResponse:
    return RedirectResponse(url="/BBS", status_code=303)


@app.get("/{route}", response_class=HTMLResponse)
def route_page(request: Request, route: str) -> HTMLResponse:
    legacy_route = _route_or_404(route)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, **_thread_view_context(request, legacy_route)},
    )


@app.get("/{route}/{thread_id}", response_class=HTMLResponse)
def thread_page(request: Request, route: str, thread_id: str) -> HTMLResponse:
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, **_thread_view_context(request, legacy_route, thread_id)},
    )


@app.post("/session")
async def set_session(request: Request) -> RedirectResponse:
    form = await _form_data(request)
    user_name = form.get("user_name", "").strip() or "anonymous"
    redirect_to = request.headers.get("referer", "/BBS")
    response = RedirectResponse(url=redirect_to, status_code=303)
    response.set_cookie(
        key="algodoo_user",
        value=user_name,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    response = RedirectResponse(url=request.headers.get("referer", "/BBS"), status_code=303)
    response.delete_cookie("algodoo_user")
    return response


@app.post("/{route}/threads")
async def create_thread_form(request: Request, route: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    thread = create_thread(
        route=legacy_route,
        title=form.get("title", "").strip(),
        content=form.get("content", "").strip(),
        user_name=_current_user(request),
        file_keys=_file_keys_from_text(form.get("file_keys", "")),
    )
    return RedirectResponse(url=f"/{legacy_route.value}/{thread.thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/edit")
async def edit_thread_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    updated = update_thread_details(
        route=legacy_route,
        thread_id=thread_id,
        title=form.get("title", "").strip(),
        content=form.get("content", "").strip(),
        file_keys=_file_keys_from_text(form.get("file_keys", "")),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/delete")
def delete_thread_form(route: str, thread_id: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    delete_thread(legacy_route, thread_id)
    return RedirectResponse(url=f"/{legacy_route.value}", status_code=303)


@app.post("/{route}/{thread_id}/logs")
async def create_log_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    form = await _form_data(request)
    create_log(
        thread_id=thread_id,
        content=form.get("content", "").strip(),
        user_name=_current_user(request),
    )
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/logs/{log_id}/responses")
async def create_response_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    form = await _form_data(request)
    create_log(
        thread_id=thread_id,
        content=form.get("content", "").strip(),
        user_name=_current_user(request),
        response_to=log_id,
    )
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/logs/{log_id}/edit")
async def edit_log_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    updated = update_log_details(thread_id, log_id, form.get("content", "").strip())
    if updated is None:
        raise HTTPException(status_code=404, detail="log not found")
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/logs/{log_id}/delete")
def delete_log_form(route: str, thread_id: str, log_id: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    delete_log(thread_id, log_id)
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/like")
def like_thread_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    create_like(thread_id, _current_user(request), LikeType.GOOD)
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/{route}/{thread_id}/logs/{log_id}/like")
def like_log_form(request: Request, route: str, thread_id: str, log_id: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    create_like(log_id, _current_user(request), LikeType.GOOD)
    return RedirectResponse(url=f"/{legacy_route.value}/{thread_id}", status_code=303)
