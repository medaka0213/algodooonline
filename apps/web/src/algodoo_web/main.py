import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

from algodoo_data.repository import (
    create_like,
    create_log,
    create_thread,
    create_user,
    delete_like,
    delete_log,
    delete_thread,
    get_like_summary,
    get_own_like,
    get_own_likes_batch,
    get_thread,
    get_user,
    list_logs,
    list_threads,
    update_log_details,
    update_thread_details,
)
from algodoo_domain.models import LegacyRoute, LikeType
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from mangum import Mangum
from markupsafe import Markup

from algodoo_web.api import router as api_router
from algodoo_web.bootstrap import bootstrap_data

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DISPLAY_ALIASES = {
    "BBS": LegacyRoute.BBS,
    "Wiki": LegacyRoute.WIKI,
    "Image": LegacyRoute.IMAGE,
    "Data": LegacyRoute.DATA,
}
ROUTE_LABELS = {
    LegacyRoute.BBS: "BBS掲示板",
    LegacyRoute.WIKI: "Wiki",
    LegacyRoute.IMAGE: "画像掲示板",
    LegacyRoute.DATA: "Phz/Phnデータ掲示板",
}
SORT_OPTIONS = [
    ("", "並べ替え"),
    ("NEWEST_UPDATED", "新着 (更新日時)"),
    ("NEWEST_CREATED", "新着 (投稿日時)"),
    ("OLDEST_UPDATED", "古い順 (更新日時)"),
    ("OLDEST_CREATED", "古い順 (投稿日時)"),
    ("BEST", "高評価"),
    ("MOST_RESPONSED", "コメント数"),
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_data()
    yield


app = FastAPI(title="algodooonline", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(api_router, prefix="/api")
handler = Mangum(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "app": "algodooonline"}


def _route_or_404(route: str) -> LegacyRoute:
    normalized = route.upper()
    if normalized == "WIKI":
        return LegacyRoute.WIKI
    try:
        return LegacyRoute(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="route not found") from exc


async def _form_data(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _current_user(request: Request) -> dict[str, str] | None:
    token = request.cookies.get("algodoo_idtoken")
    if not token:
        return None
    name = request.cookies.get("algodoo_name") or "anonymous"
    sub = request.cookies.get("algodoo_sub") or f"local-{name}"
    return {
        "name": name,
        "sub": sub,
        "idToken": token,
        "refreshToken": request.cookies.get("algodoo_refresh", ""),
        "refreshTokenExp": request.cookies.get("algodoo_refresh_exp", ""),
        "status": "authenticated",
    }


def _require_user(request: Request) -> dict[str, str]:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return user


def _filedata_from_form(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _wants_delete(form: dict[str, str]) -> bool:
    return form.get("deletepass", "") in {"削除", "delete"}


def _search_tokens(value: str) -> list[str]:
    return [token for token in value.replace("　", " ").split() if token]


def _highlight(value: str, query_text: str) -> Markup:
    text = escape(value)
    for token in _search_tokens(query_text):
        text = re.sub(
            re.escape(escape(token)),
            lambda match: f'<span class="bg-warning">{match.group(0)}</span>',
            text,
            flags=re.IGNORECASE,
        )
    return Markup(text)


def _snippet(value: str, query_text: str, length: int = 300) -> str:
    tokens = _search_tokens(query_text)
    if not tokens or len(value) <= length:
        return value[:length] + ("..." if len(value) > length else "")
    lowered = value.lower()
    first = min(
        (lowered.find(token.lower()) for token in tokens if token.lower() in lowered),
        default=0,
    )
    start = max(first - 80, 0)
    end = min(start + length, len(value))
    prefix = "..." if start else ""
    suffix = "..." if end < len(value) else ""
    return f"{prefix}{value[start:end]}{suffix}"


def _markdown(value: str) -> Markup:
    if value.lstrip().startswith(("<!", "<?", "<\\")):
        return Markup("")
    safe = escape(value)
    safe = re.sub(r"^### (.+)$", r"<h3>\1</h3>", safe, flags=re.MULTILINE)
    safe = re.sub(r"^## (.+)$", r"<h2>\1</h2>", safe, flags=re.MULTILINE)
    safe = re.sub(r"^# (.+)$", r"<h1>\1</h1>", safe, flags=re.MULTILINE)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    paragraphs = [
        line if line.startswith("<h") else f"<p>{line}</p>"
        for line in safe.splitlines()
        if line.strip()
    ]
    return Markup("\n".join(paragraphs))


def _relative(value: str) -> str:
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return value.replace("T", " ").split(".")[0]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    seconds = max(
        0,
        int((datetime.now(UTC) - dt.astimezone(UTC)).total_seconds()),
    )
    if seconds < 45:
        return "数秒前"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}時間前"
    days = hours // 24
    if days < 30:
        return f"{days}日前"
    months = days // 30
    if months < 12:
        return f"{months}ヶ月前"
    return f"{days // 365}年前"


def _is_image(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("data:image/") or lowered.endswith(
        (".jpg", ".jpeg", ".png", ".gif", ".webp")
    )


def _is_thumb(value: str) -> bool:
    return "_thumb." in value.lower() or value.lower().endswith("thumb.png")


def _first_image(values: list[str] | None) -> str:
    for value in values or []:
        if _is_image(value):
            return value
    return ""


def _first_data_thumb(values: list[str] | None) -> str:
    for value in values or []:
        if _is_thumb(value):
            return value
    first = next(iter(values or []), "")
    if first.lower().endswith(".phz"):
        return f"{first[:-4]}_thumb.png"
    return ""


templates.env.filters["highlight"] = _highlight
templates.env.filters["snippet"] = _snippet
templates.env.filters["markdown"] = _markdown
templates.env.filters["relative"] = _relative
templates.env.filters["is_image"] = _is_image
templates.env.filters["is_thumb"] = _is_thumb
templates.env.filters["first_image"] = _first_image
templates.env.filters["first_data_thumb"] = _first_data_thumb


def _base_context(request: Request) -> dict[str, object]:
    query_string = request.url.query
    return {
        "request": request,
        "routes": list(LegacyRoute),
        "route_labels": ROUTE_LABELS,
        "sort_options": SORT_OPTIONS,
        "current_user": _current_user(request),
        "current_path_with_query": (
            f"{request.url.path}?{query_string}" if query_string else request.url.path
        ),
    }


def _build_own_likes(items: list, current_user: dict | None) -> dict[str, dict]:
    if not current_user:
        return {}
    post_ids = [item.thread_id if hasattr(item, "thread_id") else item.log_id for item in items]
    return get_own_likes_batch(post_ids, current_user["sub"])


def _board_context(
    request: Request,
    route: LegacyRoute,
    thread_id: str | None = None,
) -> dict[str, object]:
    search_query = request.query_params.get("q", "").strip()
    sort = request.query_params.get("sort", "")
    threads = list_threads(route, search_query or None, sort or None)
    selected_thread = get_thread(route, thread_id) if thread_id else None
    if thread_id and selected_thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    logs = (
        list_logs(selected_thread.thread_id, search_query or None, sort or None)
        if selected_thread
        else []
    )
    top_level_logs = [log for log in logs if not log.response_to]
    responses_by_log = {
        log.log_id: [reply for reply in logs if reply.response_to == log.log_id]
        for log in logs
    }
    current_user = _current_user(request)
    return {
        **_base_context(request),
        "page": "board",
        "active_route": route,
        "search_query": search_query,
        "selected_sort": sort,
        "threads": threads,
        "selected_thread": selected_thread,
        "top_level_logs": top_level_logs,
        "responses_by_log": responses_by_log,
        "like_summary": get_like_summary(selected_thread.thread_id) if selected_thread else {},
        "log_like_summary": {log.log_id: get_like_summary(log.log_id) for log in logs},
        "thread_own_likes": (
            _build_own_likes(threads, current_user)
        ),
        "selected_thread_own_like": (
            get_own_like(selected_thread.thread_id, current_user["sub"])
            if selected_thread and current_user
            else {}
        ),
        "log_own_likes": (
            _build_own_likes(logs, current_user)
        ),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_base_context(request), "page": "home"},
    )


@app.get("/i/{route}", response_class=HTMLResponse)
def route_page(request: Request, route: str) -> HTMLResponse:
    legacy_route = _route_or_404(route)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_board_context(request, legacy_route),
    )


@app.get("/i/{route}/{thread_id}", response_class=HTMLResponse)
def thread_page(request: Request, route: str, thread_id: str) -> HTMLResponse:
    legacy_route = _route_or_404(route)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_board_context(request, legacy_route, thread_id),
    )


@app.get("/{route}", response_class=HTMLResponse)
def legacy_route_redirect(route: str) -> RedirectResponse:
    if route not in DISPLAY_ALIASES:
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url=f"/i/{DISPLAY_ALIASES[route].value}", status_code=303)


@app.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_base_context(request), "page": "login", "v1_username": ""},
    )


@app.post("/auth/login")
async def login_submit(request: Request):
    form = await _form_data(request)
    username = form.get("Username", "").strip()
    user = get_user(username)
    if user and user.version == "1":
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={**_base_context(request), "page": "login", "v1_username": username},
        )
    if user is None:
        user = create_user(
            username=username,
            email=f"{username}@local.invalid",
            sub=f"local-{username}",
        )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("algodoo_name", username, httponly=True, samesite="lax")
    response.set_cookie("algodoo_sub", user.sub, httponly=True, samesite="lax")
    response.set_cookie("algodoo_idtoken", f"local-token-{username}", httponly=True, samesite="lax")
    response.set_cookie(
        "algodoo_refresh",
        f"local-refresh-{username}",
        httponly=True,
        samesite="lax",
    )
    response.set_cookie("algodoo_refresh_exp", "local", httponly=True, samesite="lax")
    return response


@app.get("/auth/signup", response_class=HTMLResponse)
@app.get("/auth/signup/{username}", response_class=HTMLResponse)
def signup_page(request: Request, username: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **_base_context(request),
            "page": "signup",
            "fixed_username": username,
            "verify": False,
        },
    )


@app.post("/auth/signup")
@app.post("/auth/signup/{username}")
async def signup_submit(request: Request, username: str = ""):
    form = await _form_data(request)
    step = form.get("step", "register")
    selected_username = username or form.get("Username", "").strip()
    if step == "verify":
        create_user(
            username=selected_username,
            email=form.get("email", f"{selected_username}@local.invalid"),
            sub=f"local-{selected_username}",
        )
        return RedirectResponse(url="/auth/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **_base_context(request),
            "page": "signup",
            "fixed_username": selected_username,
            "email": form.get("email", ""),
            "verify": True,
        },
    )


@app.get("/auth/logout", response_class=HTMLResponse)
def logout_page(request: Request):
    if _current_user(request) is None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_base_context(request), "page": "logout"},
    )


@app.post("/auth/logout")
def logout_submit() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=303)
    for key in [
        "algodoo_name",
        "algodoo_sub",
        "algodoo_idtoken",
        "algodoo_refresh",
        "algodoo_refresh_exp",
    ]:
        response.delete_cookie(key)
    return response


@app.get("/auth/changepass", response_class=HTMLResponse)
def changepass_page(request: Request):
    if _current_user(request) is None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_base_context(request), "page": "changepass"},
    )


@app.post("/auth/changepass")
async def changepass_submit(request: Request) -> RedirectResponse:
    _require_user(request)
    return RedirectResponse(url="/", status_code=303)


@app.get("/auth/forgotpass", response_class=HTMLResponse)
def forgotpass_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_base_context(request), "page": "forgotpass", "recover": False},
    )


@app.post("/auth/forgotpass")
async def forgotpass_submit(request: Request):
    form = await _form_data(request)
    if form.get("step") == "recover":
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **_base_context(request),
            "page": "forgotpass",
            "recover": True,
            "forgot_username": form.get("Username", ""),
        },
    )


@app.post("/i/{route}/threads")
async def create_thread_form(request: Request, route: str) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    thread = create_thread(
        route=legacy_route,
        title=form.get("title", "").strip(),
        content=form.get("content", "").strip(),
        user_name=user["name"],
        user_id=user["sub"],
        filedata=_filedata_from_form(form.get("filedata", "")),
    )
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread.thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/edit")
async def edit_thread_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    thread = get_thread(legacy_route, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if thread.user_id != user["sub"]:
        raise HTTPException(status_code=403, detail="forbidden")
    form = await _form_data(request)
    update_thread_details(
        route=legacy_route,
        thread_id=thread_id,
        title=form.get("title", "").strip(),
        content=form.get("content", "").strip(),
        filedata=_filedata_from_form(form.get("filedata", "")),
    )
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/delete")
async def delete_thread_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    thread = get_thread(legacy_route, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    form = await _form_data(request)
    if thread.user_id == user["sub"] and _wants_delete(form):
        delete_thread(legacy_route, thread_id)
        return RedirectResponse(url=f"/i/{legacy_route.value}", status_code=303)
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/logs")
async def create_log_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    form = await _form_data(request)
    create_log(
        thread_id=thread_id,
        content=form.get("content", "").strip(),
        user_name=user["name"],
        user_id=user["sub"],
    )
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/logs/{log_id}/responses")
async def create_response_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    create_log(
        thread_id=thread_id,
        content=form.get("content", "").strip(),
        user_name=user["name"],
        user_id=user["sub"],
        response_to=log_id,
    )
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/logs/{log_id}/edit")
async def edit_log_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    log = list(filter(lambda item: item.log_id == log_id, list_logs(thread_id)))
    if not log:
        raise HTTPException(status_code=404, detail="log not found")
    if log[0].user_id != user["sub"]:
        raise HTTPException(status_code=403, detail="forbidden")
    form = await _form_data(request)
    update_log_details(thread_id, log_id, form.get("content", "").strip())
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/logs/{log_id}/delete")
async def delete_log_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    log = list(filter(lambda item: item.log_id == log_id, list_logs(thread_id)))
    form = await _form_data(request)
    if log and log[0].user_id == user["sub"] and _wants_delete(form):
        delete_log(thread_id, log_id)
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/like")
async def like_thread_form(request: Request, route: str, thread_id: str) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    if form.get("action") == "delete":
        delete_like(thread_id, user["sub"])
    else:
        create_like(thread_id, user["sub"], LikeType(form.get("type", "good")))
    next_url = form.get("next", "")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = f"/i/{legacy_route.value}/{thread_id}"
    return RedirectResponse(url=next_url, status_code=303)


@app.post("/i/{route}/{thread_id}/logs/{log_id}/like")
async def like_log_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    if form.get("action") == "delete":
        delete_like(log_id, user["sub"])
    else:
        create_like(log_id, user["sub"], LikeType(form.get("type", "good")))
    next_url = form.get("next", "")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = f"/i/{legacy_route.value}/{thread_id}"
    return RedirectResponse(url=next_url, status_code=303)


@app.get("/{path:path}", response_class=HTMLResponse)
def fallback() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=303)
