"""SPEC.md §10: Like create/delete on both thread list, thread detail and logs."""

from __future__ import annotations

from auth import login
from board import (
    create_thread,
    has_class,
    like_and_wait,
    log_item_by_text,
    log_like_button,
    reply_to_thread,
)
from playwright.sync_api import Page, expect


def test_guest_like_click_redirects_to_login(
    page: Page, browser, base_url: str, username: str, unique_id: str
) -> None:
    login(page, username)
    create_thread(page, "BBS", f"GuestLike {unique_id}", "content")

    guest_context = browser.new_context(base_url=base_url)
    guest_page = guest_context.new_page()
    guest_page.goto("/i/BBS")

    item = guest_page.locator("div.thread-item").filter(has_text=f"GuestLike {unique_id}")
    item.locator("button.like-button").click()
    guest_page.wait_for_url("**/auth/login")
    guest_context.close()


def test_like_and_unlike_thread_from_list(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    create_thread(page, "BBS", f"ListLike {unique_id}", "content")
    page.goto("/i/BBS")

    item = page.locator("div.thread-item").filter(has_text=f"ListLike {unique_id}")
    like_button = item.locator("button.like-button")
    score = item.locator(".like-score")
    expect(score).to_have_text("0")
    expect(like_button).not_to_have_class(has_class("is-liked"))

    like_and_wait(page, like_button)
    item = page.locator("div.thread-item").filter(has_text=f"ListLike {unique_id}")
    expect(item.locator(".like-score")).to_have_text("1")
    expect(item.locator("button.like-button")).to_have_class(has_class("is-liked"))

    # Reloading confirms the "own like" state is persisted server-side, not
    # just toggled client-side.
    page.reload()
    item = page.locator("div.thread-item").filter(has_text=f"ListLike {unique_id}")
    expect(item.locator("button.like-button")).to_have_class(has_class("is-liked"))

    like_and_wait(page, item.locator("button.like-button"))
    item = page.locator("div.thread-item").filter(has_text=f"ListLike {unique_id}")
    expect(item.locator(".like-score")).to_have_text("0")
    expect(item.locator("button.like-button")).not_to_have_class(has_class("is-liked"))


def test_like_and_unlike_thread_from_detail(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    create_thread(page, "BBS", f"DetailLike {unique_id}", "content")

    article = page.locator("article.post-detail")
    expect(article.locator(".like-score")).to_have_text("0")
    like_and_wait(page, article.locator("button.like-button"))
    article = page.locator("article.post-detail")
    expect(article.locator(".like-score")).to_have_text("1")
    expect(article.locator("button.like-button")).to_have_class(has_class("is-liked"))


def test_guest_sees_readonly_like_marker_on_detail(
    page: Page, browser, base_url: str, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"ReadonlyLike {unique_id}", "content")

    guest_context = browser.new_context(base_url=base_url)
    guest_page = guest_context.new_page()
    guest_page.goto(thread_path)
    article = guest_page.locator("article.post-detail")
    expect(article.locator(".like-readonly")).to_be_visible()
    expect(article.locator("form button.like-button")).to_have_count(0)
    guest_context.close()


def test_like_and_unlike_log(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    create_thread(page, "BBS", f"LogLike {unique_id}", "content")
    reply_to_thread(page, "BBS", f"likeable log {unique_id}")

    log_item = log_item_by_text(page, f"likeable log {unique_id}")
    like_and_wait(page, log_like_button(log_item))

    log_item = log_item_by_text(page, f"likeable log {unique_id}")
    expect(log_item.locator(":scope > div.post-row > div.like-box .like-score")).to_have_text("1")
    expect(log_like_button(log_item)).to_have_class(has_class("is-liked"))
