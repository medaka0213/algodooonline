import base64
import io
import json
import os
import time
import zipfile
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
S3_INTERNAL_BASE_URL = os.environ.get("S3_INTERNAL_BASE_URL", "").rstrip("/")
ASSET_PUBLIC_BASE_URL = os.environ.get(
    "ASSET_PUBLIC_BASE_URL", "http://localhost:8002/algodoo-assets-local"
).rstrip("/")
OPENER = build_opener(HTTPCookieProcessor(CookieJar()))
GUEST_API_OPENER = build_opener(HTTPCookieProcessor(CookieJar()))

MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class ThreadLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.thread_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.thread_href or tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        class_tokens = (attr_map.get("class") or "").split()
        if href and "thread-link" in class_tokens:
            self.thread_href = href


def fetch(path: str) -> str:
    with OPENER.open(BASE_URL + path, timeout=10) as response:
        return response.read().decode()


def fetch_guest(path: str) -> str:
    guest = build_opener(HTTPCookieProcessor(CookieJar()))
    with guest.open(BASE_URL + path, timeout=10) as response:
        return response.read().decode()


def assert_s3_object_url_rendered(html: str, storage_prefix: str) -> None:
    public_prefix = f"{ASSET_PUBLIC_BASE_URL}/"
    marker = f"{public_prefix}{storage_prefix}"
    assert marker in html
    if not S3_INTERNAL_BASE_URL:
        return
    start = html.index(marker)
    candidate_ends = [
        html.find('"', start),
        html.find("'", start),
        html.find("<", start),
    ]
    valid_ends = [pos for pos in candidate_ends if pos > start]
    if not valid_ends:
        raise AssertionError(f"could not find end delimiter for S3 URL at offset {start}")
    end = min(valid_ends)
    public_url = html[start:end]
    object_path = public_url.removeprefix(public_prefix)
    with OPENER.open(f"{S3_INTERNAL_BASE_URL}/{object_path}", timeout=10) as response:
        assert response.status == 200
        assert response.read()


def phz_data_url() -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scene.phn", "# integration scene\n")
        zf.writestr("checksums.txt", "sha256 placeholder\n")
        zf.writestr("thumb.png", MIN_PNG)
    encoded = base64.b64encode(buf.getvalue()).decode()
    return f"data:application/zip;base64,{encoded}"


def get_json(path: str, opener=OPENER) -> dict:
    request = Request(
        BASE_URL + path,
        method="GET",
        headers={"Accept": "application/json"},
    )
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read().decode())


def final_url(path: str) -> str:
    with OPENER.open(BASE_URL + path, timeout=10) as response:
        response.read()
        return response.geturl().removeprefix(BASE_URL)


def post(path: str, payload: dict[str, str]) -> str:
    data = urlencode(payload).encode()
    request = Request(
        BASE_URL + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with OPENER.open(request, timeout=10) as response:
        response.read()
        return response.geturl().removeprefix(BASE_URL)


def api(method: str, path: str, payload: dict | None = None, *, opener=None) -> dict:
    api_key = (os.environ.get("LEGACY_X_API_KEY") or "local-x-api-key").strip()
    if method.upper() == "GET":
        data = None
        headers = {"x-api-key": api_key}
    else:
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "x-api-key": api_key}
    request = Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers=headers,
    )
    use_opener = opener or OPENER
    with use_opener.open(request, timeout=10) as response:
        return json.loads(response.read().decode())


def first_thread_path(route: str) -> str:
    parser = ThreadLinkParser()
    parser.feed(fetch(f"/i/{route}"))
    if not parser.thread_href:
        raise AssertionError(f"{route} thread list did not render a thread link")
    return parser.thread_href


def assert_thread_list_layout(route: str, thread_path: str, *, expect_preview: bool) -> None:
    html = fetch(f"/i/{route}")
    assert '<a class="thread-item"' not in html
    assert '<div class="thread-item' in html
    assert 'class="thread-link thread-item-body"' in html
    assert f'href="{thread_path}"' in html
    assert f'action="{thread_path}/like"' in html
    assert 'class="like-icon"' in html
    assert "like-symbol" not in html
    if expect_preview:
        assert 'class="thread-preview"' in html
        assert 'class="thread-item has-preview"' in html
    else:
        assert 'class="thread-preview"' not in html
        assert 'class="thread-item has-preview"' not in html


def main() -> None:
    suffix = str(int(time.time()))

    home = fetch("/")
    assert "AlgodooOnline" in home
    assert "ログインしてください" in home
    assert "BBS掲示板" in home
    assert "Phz/Phnデータ掲示板" in home
    assert "AlgodooOnline [ver 2.0]" in home
    assert "サイトマップ" in home
    assert "ユーザー認証" in home
    assert "migration" not in home.lower()
    assert "single-table" not in home

    for path, target in [
        ("/BBS", "/i/BBS"),
        ("/Wiki", "/i/WIKI"),
        ("/Image", "/i/IMAGE"),
        ("/Data", "/i/DATA"),
    ]:
        assert final_url(path) == target
    assert final_url("/unknown") == "/"

    for path, marker in [
        ("/auth/login", "ログインする"),
        ("/auth/signup", "アカウントを新規作成"),
        ("/auth/forgotpass", "パスワードを忘れた場合"),
    ]:
        assert marker in fetch(path)

    assert "ログインしてください" in fetch("/i/BBS")

    integration_user = f"integration-{suffix}"
    integration_sub = f"local-{integration_user}"
    post("/auth/login", {"Username": integration_user, "password": "password123"})
    assert f"Hello, {integration_user}!" in fetch("/")
    home_api = get_json("/")
    token_payload = json.loads(home_api["message"])
    assert token_payload["sub"]
    try:
        get_json("/", build_opener(HTTPCookieProcessor(CookieJar())))
    except HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("unauthenticated JSON GET / should return 401")
    assert "パスワードを変更する" in fetch("/auth/changepass")
    assert "ログアウトする" in fetch("/auth/logout")

    created_path = post(
        "/i/BBS/threads",
        {
            "title": f"Integration {suffix}",
            "content": "created by local integration test",
            "filedata": "",
        },
    )
    assert created_path.startswith("/i/BBS/BBS_")
    thread_html = fetch(created_path)
    assert f"Integration {suffix}" in thread_html
    assert "created by local integration test" in thread_html
    assert "このスレッドに返信する" in thread_html
    assert_thread_list_layout("BBS", created_path, expect_preview=False)
    try:
        api(
            "GET",
            f"/bbslogs/{created_path.rsplit('/', 1)[-1]}",
            opener=GUEST_API_OPENER,
        )
    except HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("legacy GET /bbslogs without session must return 401")
    assert post(f"{created_path}/like", {"type": "good", "next": "/i/BBS"}) == "/i/BBS"

    assert f'<span class="bg-warning">Integration</span> {suffix}' in fetch(
        "/i/BBS?q=Integration&sort=BEST"
    )

    assert post(
        f"{created_path}/edit",
        {"title": f"Edited {suffix}", "content": "edited body", "filedata": ""},
    ) == created_path
    assert "編集済み" in fetch(created_path)

    assert post(f"{created_path}/logs", {"content": "integration response"}) == created_path
    logs = api("GET", f"/bbslogs/{created_path.rsplit('/', 1)[-1]}")["submitions"]
    log_id = next(item["log_id"] for item in logs if item["content"] == "integration response")
    thread_html = fetch(created_path)
    assert "integration response" in thread_html
    assert "log-reply-toggle" in thread_html
    assert "modal-log-preview" in thread_html
    assert 'data-modal-close aria-label="閉じる"' in thread_html
    assert "<summary>ログを編集</summary>" not in thread_html
    assert "<summary>ログを削除</summary>" not in thread_html
    assert 'class="modal-shell" hidden' in thread_html
    guest_thread = fetch_guest(created_path)
    assert "integration response" not in guest_thread
    assert "返信一覧はログイン後" in guest_thread

    assert (
        post(f"{created_path}/logs/{log_id}/responses", {"content": "child integration response"})
        == created_path
    )
    logs = api("GET", f"/bbslogs/{created_path.rsplit('/', 1)[-1]}")["submitions"]
    child_log_id = next(
        item["log_id"] for item in logs if item["content"] == "child integration response"
    )
    thread_html = fetch(created_path)
    assert "1件の返信" in thread_html
    assert f'action="{created_path}/logs/{child_log_id}/like"' in thread_html
    assert f'action="{created_path}/logs/{child_log_id}/responses"' in thread_html
    assert (
        post(
            f"{created_path}/logs/{child_log_id}/responses",
            {"content": "grandchild integration response"},
        )
        == created_path
    )
    logs = api("GET", f"/bbslogs/{created_path.rsplit('/', 1)[-1]}")["submitions"]
    grandchild = next(item for item in logs if item["content"] == "grandchild integration response")
    assert grandchild["response_to"] == child_log_id
    thread_html = fetch(created_path)
    assert "grandchild integration response" in thread_html
    assert f'action="{created_path}/logs/{grandchild["log_id"]}/like"' in thread_html
    assert f'action="{created_path}/logs/{grandchild["log_id"]}/responses"' in thread_html
    assert "<summary>ログを編集</summary>" not in thread_html
    assert "<summary>ログを削除</summary>" not in thread_html

    assert (
        post(f"{created_path}/logs/{log_id}/edit", {"content": "edited integration response"})
        == created_path
    )
    assert "edited integration response" in fetch(created_path)

    assert post(f"{created_path}/logs/{log_id}/delete", {"deletepass": "wrong"}) == created_path
    assert "edited integration response" in fetch(created_path)
    assert post(f"{created_path}/logs/{log_id}/delete", {"deletepass": "delete"}) == created_path
    assert "この返信は削除されました" in fetch(created_path)

    post(f"{created_path}/like", {"type": "good"})
    thread_id = created_path.rsplit("/", 1)[-1]
    likes = api("GET", f"/like/{thread_id}")["likes"]
    assert likes["n_good"] >= 1
    assert api("GET", f"/like/{thread_id}/own")["like"]["type"] == "good"
    post(f"{created_path}/like", {"action": "delete"})
    assert api("POST", "/like/own/batch", {"post_ids": [thread_id]})["result"]

    assert post(f"{created_path}/delete", {"deletepass": "削除"}) == "/i/BBS"
    assert f'<h3 class="thread-title">Edited {suffix}</h3>' not in fetch(
        f"/i/BBS?q=Edited%20{suffix}"
    )

    wiki_path = post(
        "/i/WIKI/threads",
        {
            "title": f"Wiki {suffix}",
            "content": "## Markdown integration\n\n**bold**",
            "filedata": "",
        },
    )
    assert_thread_list_layout("WIKI", wiki_path, expect_preview=False)
    assert "<h2>Markdown integration</h2>" in fetch(wiki_path)

    sanitizer_path = post(
        "/i/WIKI/threads",
        {
            "title": f"Sanitize {suffix}",
            "content": "<!-- secretcomment123 -->visible text [evil](javascript:alert(1))",
            "filedata": "",
        },
    )
    sanitizer_html = fetch(sanitizer_path)
    # Rendered markdown keeps the body, drops the declaration token and the
    # javascript: href. The raw text also sits (escaped) in the edit textarea,
    # so assert on the unescaped rendered forms only.
    assert "<p>visible text <a>evil</a></p>" in sanitizer_html
    assert "<!-- secretcomment123" not in sanitizer_html
    assert 'href="javascript' not in sanitizer_html

    image_data_url = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2w=="
    image_path = post(
        "/i/IMAGE/threads",
        {"title": f"Image {suffix}", "content": "image content", "filedata": image_data_url},
    )
    image_html = fetch(image_path)
    assert "uploaded image" in image_html
    assert "slide-image" in image_html
    assert_s3_object_url_rendered(image_html, "IMAGE/")
    assert_thread_list_layout("IMAGE", image_path, expect_preview=True)

    data_path = post(
        "/i/DATA/threads",
        {
            "title": f"Data {suffix}",
            "content": "data content",
            "filedata": phz_data_url(),
        },
    )
    data_html = fetch(data_path)
    assert "ダウンロード" in data_html
    assert ".phz" in data_html
    assert_s3_object_url_rendered(data_html, "DATA/")
    assert_thread_list_layout("DATA", data_path, expect_preview=True)
    # Old DownloadPHZ/SlideShow have no raw attachment listing (SPEC §7.1).
    assert 'class="attachment"' not in data_html
    assert 'class="attachment"' not in image_html

    bad_key = api(
        "POST",
        "/threads/DATA",
        {
            "submition": {
                "user_name": integration_user,
                "user_id": integration_sub,
                "title": f"Bad key {suffix}",
                "content": "must be rejected",
                "filedata": ["../etc/passwd"],
            }
        },
    )
    assert bad_key["result"] is False
    assert "filedata" in bad_key["errors"]

    api_thread = api(
        "POST",
        "/threads/DATA",
        {
            "submition": {
                "user_name": integration_user,
                "user_id": integration_sub,
                "title": f"API {suffix}",
                "content": "created through legacy JSON API",
                "filedata": ["DATA/api.phn"],
            }
        },
    )["thread"]
    api_thread_id = api_thread["thread_id"]
    assert api_thread["nRes"] == 0
    assert api_thread["filedata"] == ["DATA/api.phn"]

    content_only_update = api(
        "PUT",
        f"/threads/DATA/{api_thread_id}",
        {"submition": {"title": f"API content edit {suffix}", "content": "content-only update"}},
    )["thread_info"]
    assert content_only_update["filedata"] == ["DATA/api.phn"]

    api_log = api(
        "POST",
        f"/bbslogs/{api_thread_id}",
        {
            "submition": {
                "user_name": integration_user,
                "user_id": integration_sub,
                "content": "api log",
            }
        },
    )["log"]
    assert (
        api("GET", f"/bbslogs/{api_thread_id}/{api_log['log_id']}")["log_info"]["content"]
        == "api log"
    )
    api_response = api(
        "POST",
        f"/bbslogs/{api_thread_id}/{api_log['log_id']}",
        {
            "submition": {
                "user_name": integration_user,
                "user_id": integration_sub,
                "content": "api child",
            }
        },
    )["log"]
    assert api_response["response_to"] == api_log["log_id"]
    assert api("GET", f"/bbslogs/{api_thread_id}/{api_log['log_id']}/responses")["responses"]

    assert api(
        "PUT",
        f"/threads/DATA/{api_thread_id}",
        {"submition": {"title": f"API edited {suffix}", "content": "updated", "filedata": []}},
    )["thread_info"]["isEdited"]
    assert api(
        "PUT",
        f"/bbslogs/{api_thread_id}/{api_log['log_id']}",
        {"submition": {"content": "api log edited"}},
    )["log"]["isEdited"]
    assert api(
        "POST",
        "/like",
        {"post_id": api_thread_id, "type": "bad", "user_id": integration_sub},
    )["result"]
    assert api(
        "DELETE",
        "/like",
        {"post_id": api_thread_id, "type": "bad", "user_id": integration_sub},
    )["result"]
    assert api("DELETE", f"/bbslogs/{api_thread_id}/{api_log['log_id']}")["result"]
    assert api("DELETE", f"/threads/DATA/{api_thread_id}")["result"]
    assert api(
        "POST",
        "/user/signin",
        {"submition": {"Username": "new-local", "v1_password": "x"}},
    )["isV2"]
    # Local id tokens embed a unix expiry (`-e{ts}`); expired/legacy ones are rejected.
    fresh_token = f"local-token-api-user-e{int(time.time()) + 300}"
    assert api("POST", "/user/update", {"submition": {"idToken": fresh_token}})["result"]
    try:
        api("POST", "/user/update", {"submition": {"idToken": "local-token-api-user-e1"}})
        raise AssertionError("expired local token must be rejected")
    except HTTPError as exc:
        assert exc.code == 401, f"expected 401 for expired token, got {exc.code}"
    try:
        api("POST", "/user/update", {"submition": {"idToken": "local-token-api-user"}})
        raise AssertionError("legacy no-expiry local token must be rejected")
    except HTTPError as exc:
        assert exc.code == 401, f"expected 401 for legacy token, got {exc.code}"

    print("integration ok")


if __name__ == "__main__":
    main()
