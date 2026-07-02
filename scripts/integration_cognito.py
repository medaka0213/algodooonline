"""Cognito auth backend integration test against a moto cognito-idp server.

Drives the real screens over HTTP: signup + verification code, login, wrong
password rejection, pre-handler token refresh, password change, forgot
password, logout, and tampered-cookie rejection. moto accepts any confirmation
code, so the UI verification step can be exercised end to end.
"""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
JAR = CookieJar()
OPENER = build_opener(HTTPCookieProcessor(JAR))


def fetch(path: str) -> str:
    with OPENER.open(BASE_URL + path, timeout=10) as response:
        return response.read().decode()


def post(path: str, payload: dict[str, str], *, expect_error: int | None = None) -> str:
    data = urlencode(payload).encode()
    request = Request(
        BASE_URL + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with OPENER.open(request, timeout=10) as response:
            assert expect_error is None, f"expected HTTP {expect_error} for {path}"
            return response.read().decode()
    except HTTPError as exc:
        assert expect_error == exc.code, f"{path} returned {exc.code}, expected {expect_error}"
        return exc.read().decode()


def cookie_value(name: str) -> str:
    for cookie in JAR:
        if cookie.name == name:
            return cookie.value or ""
    return ""


def set_cookie_value(name: str, value: str) -> None:
    for cookie in JAR:
        if cookie.name == name:
            cookie.value = value
            return
    raise AssertionError(f"cookie {name} not present")


def get_json(path: str) -> dict:
    request = Request(BASE_URL + path, method="GET", headers={"Accept": "application/json"})
    with OPENER.open(request, timeout=10) as response:
        return json.loads(response.read().decode())


def main() -> None:
    suffix = str(int(time.time()))
    username = f"cog-{suffix}"
    password = "Password#123"
    new_password = "Changed#1234"
    reset_password = "Reset#12345"

    # Signup: register -> verification form -> confirm (moto accepts any code).
    register_html = post(
        "/auth/signup",
        {
            "step": "register",
            "Username": username,
            "email": f"{username}@example.invalid",
            "password": password,
            "password_confirm": password,
        },
    )
    assert "検証コードを入力して" in register_html
    post(
        "/auth/signup",
        {"step": "verify", "Username": username, "email": "", "actKey": "000000"},
    )

    # Duplicate signup shows a form error.
    dup_html = post(
        "/auth/signup",
        {
            "step": "register",
            "Username": username,
            "email": f"{username}@example.invalid",
            "password": password,
            "password_confirm": password,
        },
        expect_error=422,
    )
    assert "既に使われています" in dup_html

    # Wrong password is rejected with the mapped message.
    error_html = post(
        "/auth/login",
        {"Username": username, "password": "Wrongpass#1"},
        expect_error=401,
    )
    assert "ユーザー名またはパスワードが違います" in error_html

    post("/auth/login", {"Username": username, "password": password})
    home = fetch("/")
    assert f"Hello, {username}!" in home
    token_payload = json.loads(get_json("/")["message"])
    assert token_payload["sub"]
    id_token = cookie_value("algodoo_idtoken")
    assert id_token.count(".") == 2, "expected a real JWT in the session cookie"

    # Pre-handler refresh: expire the access window and confirm the session
    # survives with a rotated JWT.
    set_cookie_value(
        "algodoo_access_exp", (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    )
    assert f"Hello, {username}!" in fetch("/")
    refreshed_token = cookie_value("algodoo_idtoken")
    assert refreshed_token.count(".") == 2
    assert refreshed_token != id_token, "id token should rotate via REFRESH_TOKEN_AUTH"

    # Tampered token must not authenticate.
    set_cookie_value("algodoo_idtoken", refreshed_token[:-2] + "xx")
    assert "ログインしてください" in fetch("/")
    set_cookie_value("algodoo_idtoken", refreshed_token)

    # Change password, re-login with the new one.
    post(
        "/auth/changepass",
        {
            "Username": username,
            "password": password,
            "new_password": new_password,
            "new_password_confirm": new_password,
        },
    )
    post("/auth/logout", {})
    assert "ログインしてください" in fetch("/")
    post("/auth/login", {"Username": username, "password": new_password})
    assert f"Hello, {username}!" in fetch("/")
    post("/auth/logout", {})

    # Forgot password: send code -> recover form -> reset -> login.
    recover_html = post("/auth/forgotpass", {"step": "send", "Username": username})
    assert "パスワードを回復してください" in recover_html
    post(
        "/auth/forgotpass",
        {
            "step": "recover",
            "Username": username,
            "actKey": "000000",
            "password": reset_password,
            "password_confirm": reset_password,
        },
    )
    post("/auth/login", {"Username": username, "password": reset_password})
    assert f"Hello, {username}!" in fetch("/")

    print("cognito integration ok")


if __name__ == "__main__":
    main()
