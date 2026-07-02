"""SPEC.md §7.2/§7.3 (log list, replies, edit, delete) and §8.2 (log/reply forms)."""

from __future__ import annotations

from auth import login
from board import (
    create_thread,
    delete_log,
    edit_log,
    log_item_by_text,
    log_menu_dropdown,
    log_replies_disclosure,
    log_reply_toggle,
    reply_to_log,
    reply_to_thread,
)
from playwright.sync_api import Page, expect


def test_reply_to_thread_creates_root_log(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Logs {unique_id}", "thread body")

    reply_to_thread(page, "BBS", f"root reply {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    log_item = log_item_by_text(page, f"root reply {unique_id}")
    expect(log_item).to_have_count(1)
    expect(log_item.locator(":scope > div.post-row > div.like-box")).to_be_visible()


def test_nested_reply_tree_and_disclosure(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Nested {unique_id}", "thread body")

    reply_to_thread(page, "BBS", f"parent {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    parent = log_item_by_text(page, f"parent {unique_id}")
    reply_to_log(page, "BBS", parent, f"child {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    parent = log_item_by_text(page, f"parent {unique_id}")
    disclosure = log_replies_disclosure(parent)
    # `:scope >` matters: without it this also matches summaries belonging
    # to the nested child log-item rendered inside this disclosure.
    expect(disclosure.locator(":scope > summary")).to_have_text("1件の返信")
    # A collapsed <details>'s content isn't rendered at all; the child log
    # also repeats its own content in its reply-modal preview and edit form,
    # so check the reply-list container itself rather than raw child text.
    reply_list = disclosure.locator(":scope > div.reply-list")
    expect(reply_list).not_to_be_visible()
    disclosure.locator(":scope > summary").click()
    expect(reply_list).to_be_visible()
    expect(reply_list.get_by_text(f"child {unique_id}").first).to_be_visible()

    child = log_item_by_text(page, f"child {unique_id}")
    reply_to_log(page, "BBS", child, f"grandchild {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    grandchild = log_item_by_text(page, f"grandchild {unique_id}")
    expect(grandchild).to_have_count(1)


def test_log_edit_and_delete_require_ownership_and_confirmation(
    page: Page, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Own {unique_id}", "thread body")
    reply_to_thread(page, "BBS", f"editable {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    log_item = log_item_by_text(page, f"editable {unique_id}")
    expect(log_menu_dropdown(log_item)).to_have_count(1)

    edit_log(page, "BBS", log_item, f"edited {unique_id}")
    page.wait_for_url(f"**{thread_path}")
    log_item = log_item_by_text(page, f"edited {unique_id}")
    expect(log_item.locator(":scope > div.post-row > div > div.post-head .meta")).to_contain_text(
        "編集済み"
    )

    delete_log(page, log_item, "wrong")
    page.wait_for_url(f"**{thread_path}")
    log_item = log_item_by_text(page, f"edited {unique_id}")
    expect(log_item).to_have_count(1)

    delete_log(page, log_item, "delete")
    page.wait_for_url(f"**{thread_path}")
    expect(page.get_by_text("この返信は削除されました")).to_have_count(1)
    expect(page.get_by_text(f"edited {unique_id}")).to_have_count(0)


def test_other_user_cannot_edit_or_delete_someone_elses_log(
    page: Page, browser, base_url: str, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"NotMine {unique_id}", "thread body")
    reply_to_thread(page, "BBS", f"someone else's log {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    other_context = browser.new_context(base_url=base_url)
    other_page = other_context.new_page()
    login(other_page, f"other{username}")
    other_page.goto(thread_path)

    log_item = log_item_by_text(other_page, f"someone else's log {unique_id}")
    expect(log_menu_dropdown(log_item)).to_have_count(0)
    other_context.close()


def test_log_reply_modal_shows_parent_preview(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    thread_path = create_thread(page, "BBS", f"Preview {unique_id}", "thread body")
    reply_to_thread(page, "BBS", f"preview target {unique_id}")
    page.wait_for_url(f"**{thread_path}")

    log_item = log_item_by_text(page, f"preview target {unique_id}")
    toggle = log_reply_toggle(log_item)
    toggle.locator("summary").click()
    preview = toggle.locator(".modal-log-preview")
    expect(preview).to_contain_text(f"preview target {unique_id}")
    expect(toggle.locator("h2")).to_contain_text("このログに返信する")
