"""The refreshed design keeps navigation and core forms usable at common widths."""

from __future__ import annotations

import re

import pytest
from auth import login
from board import create_thread
from playwright.sync_api import Page, expect


def assert_no_horizontal_scroll(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    ), f"Horizontal overflow on {page.url}"


@pytest.mark.parametrize("width", [360, 390, 768, 1440])
def test_navigation_and_cards_at_each_width(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/")
    assert_no_horizontal_scroll(page)

    for route, label in [
        ("BBS", "BBS掲示板"),
        ("WIKI", "Wiki"),
        ("IMAGE", "画像掲示板"),
        ("DATA", "Phz/Phnデータ掲示板"),
    ]:
        page.locator(".index-nav").get_by_role("link", name=label, exact=True).click()
        page.wait_for_url(f"**/i/{route}")
        expect(page.get_by_role("heading", name=label, exact=True)).to_be_visible()
        expect(page.locator(".nav-links a[aria-current='page']")).to_have_attribute(
            "href", f"/i/{route}"
        )
        assert_no_horizontal_scroll(page)
        page.locator("details.modal-toggle > summary").click()
        modal = page.locator("details.modal-toggle .modal-body")
        expect(modal.get_by_role("link", name="ログインしてください")).to_be_visible()
        assert_no_horizontal_scroll(page)
        modal.get_by_role("button", name="閉じる").click()
        page.locator("a.navbar-brand").click()
        expect(page.locator(".index-nav")).to_be_visible()


def test_skip_link_supports_keyboard_navigation(page: Page) -> None:
    page.goto("/")
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="本文へ移動")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/#main-content$"))


@pytest.mark.parametrize("width", [360, 768])
def test_auth_screens_fit_viewport(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    for path in ["/auth/login", "/auth/signup", "/auth/forgotpass"]:
        page.goto(path)
        expect(page.locator(".auth-card")).to_be_visible()
        expect(page.locator(".auth-card button[type='submit']")).to_be_visible()
        assert_no_horizontal_scroll(page)


def test_mobile_post_and_reply_forms(page: Page, username: str, unique_id: str) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    login(page, username)
    create_thread(page, "BBS", f"Mobile {unique_id}", "A small-screen conversation.")
    assert_no_horizontal_scroll(page)

    page.locator("details.modal-toggle > summary").click()
    modal = page.locator("details.modal-toggle .modal-body")
    expect(modal.get_by_role("button", name="Submit", exact=True)).to_be_visible()
    modal.locator("textarea[name='content']").fill("Posted from a narrow screen.")
    modal.get_by_role("button", name="Submit", exact=True).click()
    expect(page.locator(".log-item")).to_contain_text("Posted from a narrow screen.")
    assert_no_horizontal_scroll(page)
