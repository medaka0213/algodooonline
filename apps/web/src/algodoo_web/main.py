import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import bleach
import markdown
from algodoo_data.repository import (
    create_like,
    create_log,
    create_thread,
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
    upsert_user_from_claims,
)
from algodoo_data.uploads import validate_thread_filedata
from algodoo_domain.models import LegacyRoute, LikeType
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.staticfiles import StaticFiles

from algodoo_web.api import router as api_router
from algodoo_web.asset_store import media_public_url, media_root, normalize_and_persist_filedata
from algodoo_web.auth import AuthError, get_auth_backend
from algodoo_web.auth.cookies import (
    apply_session_cookies,
    parse_session_expiry,
    strip_auth_cookies,
)
from algodoo_web.bootstrap import bootstrap_data
from algodoo_web.config import get_settings, validate_production_settings
from algodoo_web.session_refresh import SessionRefreshMiddleware

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
    validate_production_settings(get_settings())
    bootstrap_data()
    yield


# --- Request body size limit (OWASP A04, issue #19) -------------------------
# `_form_data` and the JSON API read the whole body into memory; cap it so a
# single request cannot exhaust RAM. Configurable via MAX_REQUEST_BODY_BYTES.
MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(20 * 1024 * 1024)))


class _BodyTooLargeError(Exception):
    """Raised while streaming a request body that exceeds the configured cap."""


class BodySizeLimitMiddleware:
    """Pure-ASGI middleware: reject oversized bodies with 413.

    Checks Content-Length up front and additionally counts streamed chunks so
    chunked uploads without a Content-Length header are capped too.
    """

    def __init__(self, app, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                if declared is not None and declared > self.max_bytes:
                    await self._reject(send)
                    return
        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body") or b"")
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if response_started:
                raise
            await self._reject(send)

    @staticmethod
    async def _reject(send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"detail":"request body too large"}',
            }
        )


app = FastAPI(title="algodooonline", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionRefreshMiddleware)
app.add_middleware(BodySizeLimitMiddleware)


# --- CSRF: Origin/Referer validation (OWASP A01, issue #14) ------------------
# Session cookies are SameSite=Lax; this middleware adds a second layer for
# unsafe methods. Deliberate multi-layer tradeoff: requests that carry NO
# Origin/Referer header at all (curl, integration test scripts, legacy JSON
# API clients) are allowed through — browsers always attach Origin to
# cross-origin form POSTs, so cookie-riding CSRF from a browser is still
# blocked, while header-less same-host tooling keeps working. Requests that
# carry an x-api-key header are exempt: that custom header cannot be attached
# by a cross-site form post without a CORS preflight, so those calls are not
# CSRF-able via cookies.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _is_cross_origin(request: Request) -> bool:
    source = request.headers.get("origin")
    if source is None:
        source = request.headers.get("referer")
    if source is None:
        return False  # documented tradeoff: header-less clients are allowed
    parsed = urlparse(source)
    if not parsed.scheme or not parsed.netloc:
        return True  # "null" or malformed Origin: treat as cross-origin
    host = request.headers.get("host", "")
    return parsed.netloc.lower() != host.strip().lower()


@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    if (
        request.method in _UNSAFE_METHODS
        and "x-api-key" not in request.headers
        and _is_cross_origin(request)
    ):
        return JSONResponse({"detail": "cross-origin request rejected"}, status_code=403)
    return await call_next(request)


# --- Security response headers (OWASP A05, issue #16) ------------------------
# CSP matches what the app actually uses: EasyMDE from cdn.jsdelivr.net plus
# inline <script>/<style> blocks in index.html; user markdown may embed
# remote http(s) images and media files can live on an external asset host
# (ASSET_PUBLIC_BASE_URL), hence the permissive img-src.
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: blob: http: https:; "
    "media-src 'self' blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
    # HSTS only when the request actually arrived over https (directly or via
    # a TLS-terminating proxy) so plain-http local dev is unaffected.
    if (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").strip().lower() == "https"
    ):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


app.include_router(api_router)
app.include_router(api_router, prefix="/api")
MEDIA_DIR = media_root()
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "app": "algodooonline"}


def _accept_prefers_json(request: Request) -> bool:
    accept = request.headers.get("accept", "").strip()
    if not accept:
        return False
    first = accept.split(",", maxsplit=1)[0].strip().split(";", maxsplit=1)[0].strip().lower()
    return first == "application/json"


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


def _resolve_current_user(request: Request) -> dict[str, str] | None:
    token = request.cookies.get("algodoo_idtoken")
    if not token:
        return None
    refresh_deadline = parse_session_expiry(request.cookies.get("algodoo_refresh_exp", ""))
    if refresh_deadline is not None and refresh_deadline < datetime.now(UTC):
        return None
    claims = get_auth_backend().verify_id_token(token)
    if claims is None:
        return None
    return {
        "name": str(claims.get("name") or "anonymous"),
        "sub": str(claims.get("sub") or ""),
        "idToken": token,
        "refreshToken": request.cookies.get("algodoo_refresh", ""),
        "refreshTokenExp": request.cookies.get("algodoo_refresh_exp", ""),
        "status": "authenticated",
    }


def _current_user(request: Request) -> dict[str, str] | None:
    # Token verification can hit JWKS/DB; resolve once per request.
    if not hasattr(request.state, "auth_user"):
        request.state.auth_user = _resolve_current_user(request)
    return request.state.auth_user


def _require_user(request: Request) -> dict[str, str]:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return user


def _filedata_from_form(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _server_side_error_message(errors: dict[str, str]) -> str:
    lines = ["Server-side Error"] + [f"{k}: {v}" for k, v in errors.items()]
    return "\n".join(lines)


def _validate_thread_form_fields(title: str, content: str) -> dict[str, str] | None:
    errs: dict[str, str] = {}
    if not title.strip():
        errs["title"] = "required"
    if len(title) > 32:
        errs["title"] = "max length is 32"
    if not content.strip():
        errs["content"] = "required"
    if len(content) > 32000:
        errs["content"] = "max length is 32000"
    return errs or None


def _data_download_context(filedata: list[str] | None) -> dict[str, str]:
    files = filedata or []
    primary = next((f for f in files if f.lower().endswith(".phz")), "")
    thumb = next((f for f in files if _is_thumb(f)), "")
    if not thumb and primary:
        cand = f"{primary[:-4]}_thumb.png"
        if cand in files:
            thumb = cand
    return {
        "data_primary_phz": primary,
        "data_primary_phz_url": media_public_url(primary) if primary else "",
        "data_primary_thumb": thumb,
        "data_primary_thumb_url": media_public_url(thumb) if thumb else "",
    }


def _safe_next_url(next_url: str, fallback: str) -> str:
    """Only allow site-relative redirect targets (OWASP A01, issue #13).

    Browsers treat backslashes as slashes, so `/\\evil.com` would otherwise be
    an open redirect; normalize them first, then require a single leading `/`
    with no scheme/netloc.
    """
    candidate = (next_url or "").strip().replace("\\", "/")
    if not candidate.startswith("/") or candidate.startswith("//"):
        return fallback
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return fallback
    return candidate


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


# Declaration-like tokens (`<!...`, `<?...`, `<\...`) are dropped token-wise;
# the old sanitizer nulled them but the rest of the body must survive (SPEC §15).
_MARKDOWN_DECLARATION_TOKEN = re.compile(r"<[!?\\][^>\n]*>?")


def _markdown(value: str) -> Markup:
    if not value:
        return Markup("")
    value = _MARKDOWN_DECLARATION_TOKEN.sub("", value)
    raw_html = markdown.markdown(
        value,
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    )
    allowed_tags = frozenset(
        bleach.sanitizer.ALLOWED_TAGS
        | {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "pre",
            "code",
            "p",
            "br",
            "blockquote",
            "hr",
            "ul",
            "ol",
            "li",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "img",
        }
    )
    allowed_attrs = {
        "a": ["href", "title", "rel"],
        "img": ["src", "alt", "title", "loading"],
        "code": ["class"],
        "th": ["align"],
        "td": ["align"],
    }
    cleaned = bleach.clean(
        raw_html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=["http", "https"],
        strip=True,
        strip_comments=True,
    )
    return Markup(cleaned)


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
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("data:image/"):
        return True
    if lowered.startswith("image/"):
        return True
    return lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))


def _is_thumb(value: str) -> bool:
    return "_thumb." in value.lower() or value.lower().endswith("thumb.png")


def _first_image(values: list[str] | None) -> str:
    for value in values or []:
        if _is_image(value):
            return media_public_url(value)
    return ""


def _first_data_thumb(values: list[str] | None) -> str:
    vals = values or []
    for value in vals:
        if _is_thumb(value):
            return media_public_url(value)
    for value in vals:
        if value.lower().endswith(".phz"):
            candidate = f"{value[:-4]}_thumb.png"
            if candidate in vals:
                return media_public_url(candidate)
            return media_public_url(candidate)
    return ""


templates.env.filters["highlight"] = _highlight
templates.env.filters["snippet"] = _snippet
templates.env.filters["markdown"] = _markdown
templates.env.filters["relative"] = _relative
templates.env.filters["is_image"] = _is_image
templates.env.filters["is_thumb"] = _is_thumb
templates.env.filters["first_image"] = _first_image
templates.env.filters["first_data_thumb"] = _first_data_thumb
templates.env.filters["media_url"] = media_public_url


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
    # Logs have both `log_id` and `thread_id`; check `log_id` first or every
    # log's "own like" would be looked up under its parent thread's id.
    post_ids = [item.log_id if hasattr(item, "log_id") else item.thread_id for item in items]
    return get_own_likes_batch(post_ids, current_user["sub"])


def _board_context(
    request: Request,
    route: LegacyRoute,
    thread_id: str | None = None,
    *,
    form_error: str | None = None,
) -> dict[str, object]:
    search_query = request.query_params.get("q", "").strip()
    sort = request.query_params.get("sort", "")
    threads = list_threads(route, search_query or None, sort or None)
    selected_thread = get_thread(route, thread_id) if thread_id else None
    if thread_id and selected_thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    current = _current_user(request)
    logs = (
        list_logs(selected_thread.thread_id, search_query or None, sort or None)
        if selected_thread and current
        else []
    )
    top_level_logs = [log for log in logs if not log.response_to]
    responses_by_log: dict[str, list] = {}
    for reply in logs:
        parent = reply.response_to
        if parent:
            responses_by_log.setdefault(parent, []).append(reply)
    current_user = _current_user(request)
    data_ctx = (
        _data_download_context(selected_thread.filedata)
        if selected_thread and route == LegacyRoute.DATA
        else {
            "data_primary_phz": "",
            "data_primary_phz_url": "",
            "data_primary_thumb": "",
            "data_primary_thumb_url": "",
        }
    )
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
        "thread_own_likes": (_build_own_likes(threads, current_user)),
        "selected_thread_own_like": (
            get_own_like(selected_thread.thread_id, current_user["sub"])
            if selected_thread and current_user
            else {}
        ),
        "log_own_likes": (_build_own_likes(logs, current_user)),
        "form_error": form_error,
        "image_slide_urls": (
            [media_public_url(f) for f in (selected_thread.filedata or []) if _is_image(f)]
            if selected_thread and route == LegacyRoute.IMAGE
            else []
        ),
        **data_ctx,
    }


@app.get("/", response_model=None)
def home(request: Request) -> HTMLResponse | JSONResponse:
    if _accept_prefers_json(request):
        user = _current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="authentication required")
        payload = {"sub": user["sub"], "name": user["name"], "token_use": "id"}
        return JSONResponse({"message": json.dumps(payload, ensure_ascii=False)})
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


# Registered before thread_page so a reload after a POST /i/{route}/threads
# validation error lands back on the board instead of a 404 ("threads" would
# otherwise be parsed as a thread_id).
@app.get("/i/{route}/threads", response_class=HTMLResponse)
def thread_post_url_redirect(route: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    return RedirectResponse(url=f"/i/{legacy_route.value}", status_code=303)


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
    password = form.get("password", "")
    user = get_user(username)
    if user and user.version == "1":
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={**_base_context(request), "page": "login", "v1_username": username},
        )
    backend = get_auth_backend()
    try:
        tokens = backend.sign_in(username, password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                **_base_context(request),
                "page": "login",
                "v1_username": "",
                "form_error": exc.message,
            },
            status_code=401,
        )
    claims = backend.verify_id_token(tokens.id_token)
    if claims is None:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                **_base_context(request),
                "page": "login",
                "v1_username": "",
                "form_error": "IDトークンを検証できませんでした",
            },
            status_code=401,
        )
    upsert_user_from_claims(claims)
    response = RedirectResponse(url="/", status_code=303)
    return apply_session_cookies(response, tokens)


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
    backend = get_auth_backend()

    def _render(verify: bool, form_error: str | None = None, status_code: int = 200):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                **_base_context(request),
                "page": "signup",
                "fixed_username": selected_username,
                "email": form.get("email", ""),
                "verify": verify,
                "form_error": form_error,
            },
            status_code=status_code,
        )

    if step == "verify":
        try:
            backend.confirm_sign_up(selected_username, form.get("actKey", "").strip())
        except AuthError as exc:
            return _render(verify=True, form_error=exc.message, status_code=422)
        return RedirectResponse(url="/auth/login", status_code=303)
    password = form.get("password", "")
    if password != form.get("password_confirm", ""):
        return _render(verify=False, form_error="パスワードが一致しません", status_code=422)
    try:
        backend.sign_up(selected_username, form.get("email", "").strip(), password)
    except AuthError as exc:
        return _render(verify=False, form_error=exc.message, status_code=422)
    return _render(verify=True)


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
    return strip_auth_cookies(response)


@app.get("/auth/changepass", response_class=HTMLResponse)
def changepass_page(request: Request):
    if _current_user(request) is None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_base_context(request), "page": "changepass"},
    )


@app.post("/auth/changepass", response_model=None)
async def changepass_submit(request: Request) -> RedirectResponse | HTMLResponse:
    user = _require_user(request)
    form = await _form_data(request)
    username = form.get("Username", "").strip() or user["name"]
    new_password = form.get("new_password", "")

    def _render(form_error: str):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={**_base_context(request), "page": "changepass", "form_error": form_error},
            status_code=422,
        )

    if new_password != form.get("new_password_confirm", ""):
        return _render("新しいパスワードが一致しません")
    try:
        get_auth_backend().change_password(username, form.get("password", ""), new_password)
    except AuthError as exc:
        return _render(exc.message)
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
    username = form.get("Username", "").strip()
    backend = get_auth_backend()

    def _render(recover: bool, form_error: str | None = None, status_code: int = 200):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                **_base_context(request),
                "page": "forgotpass",
                "recover": recover,
                "forgot_username": username,
                "form_error": form_error,
            },
            status_code=status_code,
        )

    if form.get("step") == "recover":
        password = form.get("password", "")
        if password != form.get("password_confirm", ""):
            return _render(
                recover=True, form_error="新しいパスワードが一致しません", status_code=422
            )
        try:
            backend.confirm_forgot_password(username, form.get("actKey", "").strip(), password)
        except AuthError as exc:
            return _render(recover=True, form_error=exc.message, status_code=422)
        return RedirectResponse(url="/", status_code=303)
    try:
        backend.forgot_password(username)
    except AuthError as exc:
        return _render(recover=False, form_error=exc.message, status_code=422)
    return _render(recover=True)


def _thread_form_error_response(
    request: Request,
    route: LegacyRoute,
    errors: dict[str, str],
    form: dict[str, str],
    open_modal: str,
    thread_id: str | None = None,
) -> HTMLResponse:
    """Re-render the board with the failed modal reopened and the input kept."""
    ctx = _board_context(
        request,
        route,
        thread_id,
        form_error=_server_side_error_message(errors),
    )
    ctx.update(
        {
            "open_modal": open_modal,
            "form_title": form.get("title", ""),
            "form_content": form.get("content", ""),
            "form_filedata": form.get("filedata", ""),
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=ctx,
        status_code=422,
    )


@app.post("/i/{route}/threads", response_model=None)
async def create_thread_form(request: Request, route: str) -> RedirectResponse | HTMLResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    title = form.get("title", "").strip()
    content = form.get("content", "").strip()
    raw_files = _filedata_from_form(form.get("filedata", ""))
    if errs := _validate_thread_form_fields(title, content):
        return _thread_form_error_response(request, legacy_route, errs, form, "new-thread")
    if err := validate_thread_filedata(legacy_route, raw_files):
        return _thread_form_error_response(
            request, legacy_route, {"filedata": err}, form, "new-thread"
        )
    thread = create_thread(
        route=legacy_route,
        title=title,
        content=content,
        user_name=user["name"],
        user_id=user["sub"],
        filedata=[],
    )
    keys, nerr = normalize_and_persist_filedata(
        route=legacy_route,
        thread_id=thread.thread_id,
        filedata=raw_files,
    )
    if nerr:
        delete_thread(legacy_route, thread.thread_id)
        return _thread_form_error_response(
            request, legacy_route, {"filedata": nerr}, form, "new-thread"
        )
    if keys or raw_files:
        update_thread_details(legacy_route, thread.thread_id, title, content, keys)
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread.thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/edit", response_model=None)
async def edit_thread_form(
    request: Request,
    route: str,
    thread_id: str,
) -> RedirectResponse | HTMLResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    thread = get_thread(legacy_route, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if thread.user_id != user["sub"]:
        raise HTTPException(status_code=403, detail="forbidden")
    form = await _form_data(request)
    title = form.get("title", "").strip()
    content = form.get("content", "").strip()
    raw_files = _filedata_from_form(form.get("filedata", ""))
    if errs := _validate_thread_form_fields(title, content):
        return _thread_form_error_response(
            request, legacy_route, errs, form, "edit-thread", thread_id
        )
    if err := validate_thread_filedata(legacy_route, raw_files):
        return _thread_form_error_response(
            request, legacy_route, {"filedata": err}, form, "edit-thread", thread_id
        )
    keys, nerr = normalize_and_persist_filedata(
        route=legacy_route,
        thread_id=thread_id,
        filedata=raw_files,
    )
    if nerr:
        return _thread_form_error_response(
            request, legacy_route, {"filedata": nerr}, form, "edit-thread", thread_id
        )
    update_thread_details(
        route=legacy_route,
        thread_id=thread_id,
        title=title,
        content=content,
        filedata=keys,
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


@app.post("/i/{route}/{thread_id}/logs", response_model=None)
async def create_log_form(
    request: Request,
    route: str,
    thread_id: str,
) -> RedirectResponse | HTMLResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    if get_thread(legacy_route, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    form = await _form_data(request)
    content = form.get("content", "").strip()
    if not content:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_board_context(
                request,
                legacy_route,
                thread_id,
                form_error=_server_side_error_message({"content": "required"}),
            ),
            status_code=422,
        )
    if len(content) > 32000:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_board_context(
                request,
                legacy_route,
                thread_id,
                form_error=_server_side_error_message({"content": "max length is 32000"}),
            ),
            status_code=422,
        )
    create_log(
        thread_id=thread_id,
        content=content,
        user_name=user["name"],
        user_id=user["sub"],
    )
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/logs/{log_id}/responses", response_model=None)
async def create_response_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse | HTMLResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    form = await _form_data(request)
    content = form.get("content", "").strip()
    if not content:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_board_context(
                request,
                legacy_route,
                thread_id,
                form_error=_server_side_error_message({"content": "required"}),
            ),
            status_code=422,
        )
    if len(content) > 32000:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_board_context(
                request,
                legacy_route,
                thread_id,
                form_error=_server_side_error_message({"content": "max length is 32000"}),
            ),
            status_code=422,
        )
    create_log(
        thread_id=thread_id,
        content=content,
        user_name=user["name"],
        user_id=user["sub"],
        response_to=log_id,
    )
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.post("/i/{route}/{thread_id}/logs/{log_id}/edit", response_model=None)
async def edit_log_form(
    request: Request,
    route: str,
    thread_id: str,
    log_id: str,
) -> RedirectResponse | HTMLResponse:
    user = _require_user(request)
    legacy_route = _route_or_404(route)
    log = list(filter(lambda item: item.log_id == log_id, list_logs(thread_id)))
    if not log:
        raise HTTPException(status_code=404, detail="log not found")
    if log[0].user_id != user["sub"]:
        raise HTTPException(status_code=403, detail="forbidden")
    form = await _form_data(request)
    content = form.get("content", "").strip()
    if not content:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_board_context(
                request,
                legacy_route,
                thread_id,
                form_error=_server_side_error_message({"content": "required"}),
            ),
            status_code=422,
        )
    if len(content) > 32000:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=_board_context(
                request,
                legacy_route,
                thread_id,
                form_error=_server_side_error_message({"content": "max length is 32000"}),
            ),
            status_code=422,
        )
    update_log_details(thread_id, log_id, content)
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
    next_url = _safe_next_url(form.get("next", ""), f"/i/{legacy_route.value}/{thread_id}")
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
    next_url = _safe_next_url(form.get("next", ""), f"/i/{legacy_route.value}/{thread_id}")
    return RedirectResponse(url=next_url, status_code=303)


# Reloading after a POST to an action URL (/edit, /delete, /logs, /like, ...)
# replays it as GET; send the user back to the thread page instead of home.
@app.get("/i/{route}/{thread_id}/{rest:path}", response_class=HTMLResponse)
def thread_action_url_redirect(route: str, thread_id: str, rest: str) -> RedirectResponse:
    legacy_route = _route_or_404(route)
    return RedirectResponse(url=f"/i/{legacy_route.value}/{thread_id}", status_code=303)


@app.get("/{path:path}", response_class=HTMLResponse)
def fallback() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=303)
