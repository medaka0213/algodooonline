"""SPEC.md §5: authentication screens (login/signup/logout/changepass/forgotpass)."""

from __future__ import annotations

import re

from auth import TEST_PASSWORD, generate_password, login
from playwright.sync_api import Page, expect


def test_login_screen_layout(page: Page) -> None:
    page.goto("/auth/login")
    card = page.locator("section.auth-card")
    expect(card.locator("h1")).to_have_text("ログインする")
    expect(card.get_by_label("ユーザー名")).to_be_visible()
    expect(card.get_by_label("パスワード", exact=True)).to_have_attribute("type", "password")
    expect(card.get_by_role("button", name="Log in")).to_be_visible()
    expect(card.get_by_role("link", name="アカウントを新規作成する")).to_have_attribute(
        "href", "/auth/signup"
    )
    expect(card.get_by_role("link", name="パスワードを忘れた場合")).to_have_attribute(
        "href", "/auth/forgotpass"
    )


def test_login_success_redirects_home(page: Page, username: str) -> None:
    login(page, username)
    assert re.sub(r"^https?://[^/]+", "", page.url) == "/"


def test_signup_screen_register_step(page: Page, username: str) -> None:
    page.goto("/auth/signup")
    card = page.locator("section.auth-card")
    expect(card.locator("h1")).to_have_text("アカウントを新規作成")
    card.get_by_label("ユーザー名").fill(username)
    card.get_by_label("メールアドレス").fill(f"{username}@example.com")
    password = generate_password()
    card.get_by_label("パスワード", exact=True).fill(password)
    card.get_by_label("パスワード(確認用)").fill(password)
    card.get_by_role("button", name="仮登録する(検証コード送信)").click()

    expect(card).to_contain_text(
        "メールアドレスに送信された検証コードを入力して、ユーザー登録を完了してください"
    )
    expect(card.get_by_label("ユーザー名")).to_have_value(username)
    # The field is `readonly`, not `disabled` (SPEC §5.3 fixes the username).
    expect(card.get_by_label("ユーザー名")).not_to_be_editable()
    # Fixed code "123456" only works against the local/moto test backends,
    # which accept any code; the BASE_URL allowlist guard in conftest.py
    # prevents this suite from ever running against a real deployment.
    card.get_by_label("確認コード").fill("123456")
    card.get_by_role("button", name="本登録").click()

    expect(page.locator("section.auth-card h1")).to_have_text("ログインする")


def test_signup_screen_with_fixed_username(page: Page, username: str) -> None:
    page.goto(f"/auth/signup/{username}")
    card = page.locator("section.auth-card")
    username_field = card.get_by_label("ユーザー名")
    expect(username_field).to_have_value(username)
    expect(username_field).not_to_be_editable()


def test_logout_screen_redirects_when_not_logged_in(page: Page) -> None:
    page.goto("/auth/logout")
    assert re.sub(r"^https?://[^/]+", "", page.url) == "/"


def test_logout_screen_and_flow(page: Page, username: str) -> None:
    login(page, username)
    page.goto("/auth/logout")
    card = page.locator("section.auth-card")
    expect(card.locator("h1")).to_have_text("ログアウトする")
    expect(card).to_contain_text("下のボタンを押すとログアウトします")
    button = card.get_by_role("button", name="Log Out")
    expect(button).to_have_class(re.compile("btn-danger"))
    button.click()

    page.wait_for_url("**/")
    expect(page.locator(".navbar-right").get_by_role("link", name="ユーザー認証")).to_be_visible()


def test_changepass_requires_login(page: Page) -> None:
    page.goto("/auth/changepass")
    assert re.sub(r"^https?://[^/]+", "", page.url) == "/"


def test_changepass_screen_success(page: Page, username: str) -> None:
    login(page, username)
    page.goto("/auth/changepass")
    card = page.locator("section.auth-card")
    expect(card.locator("h1")).to_have_text("パスワードを変更する")
    expect(card.get_by_label("ユーザー名")).to_have_value(username)
    new_password = generate_password()
    card.get_by_label("パスワード", exact=True).fill(TEST_PASSWORD)
    card.get_by_label("新しいパスワード", exact=True).fill(new_password)
    card.get_by_label("新しいパスワード (確認用)").fill(new_password)
    card.get_by_role("button", name="パスワードを変更").click()

    assert re.sub(r"^https?://[^/]+", "", page.url) == "/"


def test_changepass_mismatch_shows_form_error(page: Page, username: str) -> None:
    login(page, username)
    page.goto("/auth/changepass")
    card = page.locator("section.auth-card")
    card.get_by_label("パスワード", exact=True).fill(TEST_PASSWORD)
    card.get_by_label("新しいパスワード", exact=True).fill(generate_password())
    card.get_by_label("新しいパスワード (確認用)").fill("doesnotmatch")
    card.get_by_role("button", name="パスワードを変更").click()

    expect(card.locator(".form-error")).to_contain_text("新しいパスワードが一致しません")


def test_forgotpass_screen_flow(page: Page, username: str) -> None:
    page.goto("/auth/forgotpass")
    card = page.locator("section.auth-card")
    expect(card.locator("h1")).to_have_text("パスワードを忘れた場合")
    card.get_by_label("ユーザー名").fill(username)
    card.get_by_role("button", name="検証コードを送る").click()

    expect(card).to_contain_text(
        "メールアドレスに送信された検証コードを入力して、パスワードを回復してください"
    )
    # Fixed code: accepted only by the local/moto test backends (see the
    # signup test above); the conftest BASE_URL guard keeps this off real
    # deployments.
    card.get_by_label("検証コード").fill("123456")
    new_password = generate_password()
    card.get_by_label("新しいパスワード", exact=True).fill(new_password)
    card.get_by_label("新しいパスワード(確認用)").fill(new_password)
    card.get_by_role("button", name="パスワードを変更する").click()

    assert re.sub(r"^https?://[^/]+", "", page.url) == "/"


def test_forgotpass_recovery_mismatch_shows_form_error(page: Page, username: str) -> None:
    page.goto("/auth/forgotpass")
    card = page.locator("section.auth-card")
    card.get_by_label("ユーザー名").fill(username)
    card.get_by_role("button", name="検証コードを送る").click()

    card.get_by_label("検証コード").fill("123456")
    card.get_by_label("新しいパスワード", exact=True).fill(generate_password())
    card.get_by_label("新しいパスワード(確認用)").fill("doesnotmatch")
    card.get_by_role("button", name="パスワードを変更する").click()

    expect(card.locator(".form-error")).to_contain_text("新しいパスワードが一致しません")
