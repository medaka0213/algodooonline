"""SPEC.md §3 (routes), §4.3 (breadcrumb) and §6 (board list) screen coverage."""

from __future__ import annotations

import pytest
from auth import login
from board import create_thread
from playwright.sync_api import Page, expect

ROUTES = [
    ("BBS", "BBS掲示板"),
    ("WIKI", "Wiki"),
    ("IMAGE", "画像掲示板"),
    ("DATA", "Phz/Phnデータ掲示板"),
]

SORT_OPTIONS = [
    ("", "並べ替え"),
    ("NEWEST_UPDATED", "新着 (更新日時)"),
    ("NEWEST_CREATED", "新着 (投稿日時)"),
    ("OLDEST_UPDATED", "古い順 (更新日時)"),
    ("OLDEST_CREATED", "古い順 (投稿日時)"),
    ("BEST", "高評価"),
    ("MOST_RESPONSED", "コメント数"),
]


@pytest.mark.parametrize(("route", "_label"), ROUTES)
def test_board_list_layout(page: Page, route: str, _label: str) -> None:
    page.goto(f"/i/{route}")

    breadcrumb = page.locator("ol.breadcrumb")
    expect(breadcrumb.get_by_role("link", name="ホーム")).to_have_attribute("href", "/")
    expect(breadcrumb.locator("li.active")).to_have_text(route)

    expect(page.locator("details.modal-toggle summary")).to_have_text("スレッドを投稿する")

    search_form = page.locator("form.search-form")
    expect(search_form.get_by_placeholder("返信を検索する")).to_be_visible()
    expect(search_form.get_by_role("button", name="Submit")).to_be_visible()

    select = search_form.locator("select.sort-select")
    options = select.locator("option").all_inner_texts()
    values = select.locator("option").evaluate_all("els => els.map(e => e.value)")
    assert values == [value for value, _ in SORT_OPTIONS]
    assert options == [label for _, label in SORT_OPTIONS]


@pytest.mark.parametrize(("route", "_label"), ROUTES)
def test_board_list_guest_post_form_shows_login_hint(page: Page, route: str, _label: str) -> None:
    page.goto(f"/i/{route}")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    login_link = toggle.get_by_role("link", name="ログインしてください")
    expect(login_link).to_be_visible()
    login_link.click()
    page.wait_for_url("**/auth/login")


@pytest.mark.parametrize(("route", "_label"), ROUTES)
def test_create_thread_appears_in_list(
    page: Page, username: str, unique_id: str, route: str, _label: str
) -> None:
    login(page, username)
    title = f"List {unique_id}"
    thread_path = create_thread(page, route, title, f"body for {unique_id}")

    page.goto(f"/i/{route}")
    item = page.locator("div.thread-item").filter(has_text=title)
    expect(item).to_have_count(1)
    expect(item.locator("h3.thread-title")).to_have_text(title)
    expect(item.locator("a.thread-link")).to_have_attribute("href", thread_path)
    expect(item.locator("form")).to_have_attribute("action", f"{thread_path}/like")
    expect(item.locator("button.like-button")).to_have_attribute("aria-label", "like")
    expect(item.locator(".meta")).to_contain_text(username)
    expect(item.locator(".meta")).to_contain_text("返信: 0件")
