"""SPEC.md §7 (thread detail) and §7.1 (thread info block) screen coverage."""

from __future__ import annotations

from auth import login
from board import create_thread, delete_thread, edit_thread
from playwright.sync_api import Page, expect

BBS_CONTENT = "line one\nline two with a very-long-unbreakable-word-" + ("x" * 40)


def test_thread_detail_layout_and_bbs_plain_text(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    title = f"Detail {unique_id}"
    thread_path = create_thread(page, "BBS", title, BBS_CONTENT)
    assert page.url.endswith(thread_path)

    breadcrumb = page.locator("ol.breadcrumb")
    expect(breadcrumb.get_by_role("link", name="ホーム")).to_have_attribute("href", "/")
    expect(breadcrumb.get_by_role("link", name="BBS")).to_have_attribute("href", "/i/BBS")
    expect(breadcrumb.locator("li.active")).to_have_text(title)

    article = page.locator("article.post-detail")
    expect(article.locator("h1")).to_have_text(title)
    # BBS content is plain text, not markdown (SPEC §7.1) — must not be parsed.
    plain = article.locator("div.content-plain")
    expect(plain).to_have_count(1)
    expect(plain).to_contain_text("line one")
    expect(plain).to_contain_text("line two")
    expect(article.locator(".markdown-body")).to_have_count(0)

    expect(page.locator("details.modal-toggle summary")).to_have_text("このスレッドに返信する")


def test_only_author_sees_thread_menu(
    page: Page, browser, base_url: str, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Owner {unique_id}", "owner-only content")

    expect(page.locator("article.post-detail details.dropdown")).to_have_count(1)

    # A genuinely separate cookie jar: `page.context.new_page()` would share
    # the just-created session cookie instead of acting as a different user.
    other_context = browser.new_context(base_url=base_url)
    other_page = other_context.new_page()
    login(other_page, f"other{username}")
    other_page.goto(thread_path)
    expect(other_page.locator("article.post-detail details.dropdown")).to_have_count(0)
    other_context.close()


def test_guest_sees_login_hint_instead_of_log_list(
    page: Page, browser, base_url: str, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Guest {unique_id}", "content for guest view")

    guest_context = browser.new_context(base_url=base_url)
    guest_page = guest_context.new_page()
    guest_page.goto(thread_path)

    expect(guest_page.locator("p.login-hint")).to_contain_text("ログインしてください")
    expect(guest_page.locator("p.login-hint")).to_contain_text("返信一覧はログイン後に表示されます")
    expect(guest_page.locator("form.search-form")).to_have_count(0)
    guest_context.close()


def test_guest_reply_button_shows_login_hint(
    page: Page, browser, base_url: str, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"GuestReply {unique_id}", "content")

    guest_context = browser.new_context(base_url=base_url)
    guest_page = guest_context.new_page()
    guest_page.goto(thread_path)

    toggle = guest_page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    login_link = toggle.get_by_role("link", name="ログインしてください")
    expect(login_link).to_be_visible()
    login_link.click()
    guest_page.wait_for_url("**/auth/login")
    guest_context.close()


def test_thread_edit_flow(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Before {unique_id}", "before body")

    edit_thread(page, "BBS", title=f"After {unique_id}", content="after body")

    page.wait_for_url(f"**{thread_path}")
    article = page.locator("article.post-detail")
    expect(article.locator("h1")).to_have_text(f"After {unique_id}")
    expect(article.locator("div.content-plain")).to_contain_text("after body")
    expect(article.locator(".meta")).to_contain_text("編集済み")


def test_thread_delete_requires_confirmation_text(
    page: Page, username: str, unique_id: str
) -> None:
    login(page, username)
    title = f"Delete {unique_id}"
    thread_path = create_thread(page, "BBS", title, "will be deleted")

    delete_thread(page, "wrong")
    page.wait_for_url(f"**{thread_path}")
    expect(page.locator("article.post-detail h1")).to_have_text(title)

    delete_thread(page, "削除")
    page.wait_for_url("**/i/BBS")

    page.goto(f"/i/BBS?q={title}")
    expect(page.locator("div.thread-item").filter(has_text=title)).to_have_count(0)
