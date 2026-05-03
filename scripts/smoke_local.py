from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = "http://127.0.0.1:8000"
OPENER = build_opener(HTTPCookieProcessor(CookieJar()))


class ThreadLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.thread_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.thread_href or tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        class_name = attr_map.get("class")
        if href and class_name == "thread-link":
            self.thread_href = href


def fetch(path: str) -> str:
    with OPENER.open(BASE_URL + path, timeout=10) as response:
        return response.read().decode()


def post(path: str, payload: dict[str, str]) -> str:
    data = urlencode(payload).encode()
    request = Request(
        BASE_URL + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with OPENER.open(request, timeout=10) as response:
        return response.geturl().removeprefix(BASE_URL)


def api(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode() if payload is not None else None
    request = Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with OPENER.open(request, timeout=10) as response:
        return json.loads(response.read().decode())


def first_thread_path(route: str = "BBS") -> str:
    parser = ThreadLinkParser()
    parser.feed(fetch(f"/{route}"))
    if not parser.thread_href:
        raise AssertionError("thread list did not render a thread link")
    return parser.thread_href


def main() -> None:
    html = fetch("/BBS")
    assert "Algodoo Online" in html
    assert "Access Patterns" not in html
    assert "single-table" not in html
    assert "Post response" in html
    assert "New thread" in html

    post("/session", {"user_name": "smoke"})

    created_path = post(
        "/BBS/threads",
        {
            "title": "Smoke thread",
            "content": "created by local smoke test",
            "file_keys": "https://example.com/sample.phz",
        },
    )
    assert created_path.startswith("/BBS/BBS_")

    thread_html = fetch(created_path)
    assert "Smoke thread" in thread_html
    assert "created by local smoke test" in thread_html
    assert "https://example.com/sample.phz" in thread_html
    assert "smoke" in thread_html

    assert "Smoke thread" in fetch("/BBS?q=Smoke")

    edit_path = post(
        f"{created_path}/edit",
        {
            "title": "Edited smoke thread",
            "content": "edited by local smoke test",
            "file_keys": "https://example.com/edited.phz",
        },
    )
    assert edit_path == created_path
    edited_html = fetch(created_path)
    assert "Edited smoke thread" in edited_html
    assert "edited by local smoke test" in edited_html
    assert "https://example.com/edited.phz" in edited_html

    log_path = post(
        f"{created_path}/logs",
        {"content": "smoke response"},
    )
    assert log_path == created_path
    log_html = fetch(created_path)
    assert "smoke response" in log_html

    parser = ThreadLinkParser()
    parser.feed(log_html)

    like_path = post(f"{created_path}/like", {})
    assert like_path == created_path
    assert "good" in fetch(created_path)

    delete_path = post(f"{created_path}/delete", {})
    assert delete_path == "/BBS"
    assert "Edited smoke thread" not in fetch("/BBS?q=Edited")

    api_thread = api(
        "POST",
        "/api/threads/DATA",
        {
            "user_name": "api-smoke",
            "title": "API smoke thread",
            "content": "created through JSON API",
            "file_keys": ["https://example.com/api.phz"],
        },
    )["thread"]
    api_thread_id = api_thread["thread_id"]
    assert api_thread_id.startswith("DATA_")

    api_log = api(
        "POST",
        f"/api/bbslogs/{api_thread_id}",
        {"user_name": "api-smoke", "content": "api log"},
    )["log"]
    assert api_log["thread_id"] == api_thread_id

    updated = api(
        "PUT",
        f"/api/threads/DATA/{api_thread_id}",
        {
            "title": "API smoke edited",
            "content": "updated through JSON API",
            "file_keys": ["https://example.com/api-edited.phz"],
        },
    )["thread_info"]
    assert updated["title"] == "API smoke edited"

    assert api("DELETE", f"/api/bbslogs/{api_thread_id}/{api_log['log_id']}")["result"]
    assert api("DELETE", f"/api/threads/DATA/{api_thread_id}")["result"]

    print("smoke ok")


if __name__ == "__main__":
    main()
