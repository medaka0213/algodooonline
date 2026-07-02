"""UI helpers for driving the board screens (SPEC.md §6-§10) like a real user.

The templates render every recursive log/reply as the same `.log-item`
component (see `apps/web/src/algodoo_web/templates/index.html`'s
`render_log_item` macro), so nested replies duplicate their ancestors'
rendered text. Helpers here scope with `:scope > ...` child combinators so a
query for one log item's own controls never also matches a nested reply's.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Locator, Page, expect

MARKDOWN_ROUTES = {"WIKI", "IMAGE", "DATA"}


def has_class(css_class: str) -> re.Pattern[str]:
    """A regex matching a `class` attribute that includes `css_class` as one token."""
    return re.compile(rf"(^|\s){re.escape(css_class)}(\s|$)")


def sync_codemirror(editor: Locator) -> None:
    """Force CodeMirror to write its buffer back onto the source <textarea>.

    The plain-text `required` <textarea> the form actually submits is hidden
    once EasyMDE takes over, and browsers refuse to submit a form with a
    hidden, empty `required` field ("An invalid form control ... is not
    focusable"). CodeMirror exposes `.CodeMirror.save()` on its wrapper
    element (a standard CodeMirror 5 convention) to copy its buffer onto that
    textarea; without a real, focused blur this can otherwise lag behind
    Playwright's synthetic typing.
    """
    editor.evaluate("el => el.CodeMirror.save()")


def fill_content(page: Page, container: Locator, route: str, text: str) -> None:
    """Fill a `content` field the way a real user would.

    WIKI/IMAGE/DATA content fields are EasyMDE-enhanced: the raw <textarea>
    is hidden and a CodeMirror editor takes its place, kept in sync back onto
    the textarea (which the form actually submits) on every keystroke.
    """
    if route in MARKDOWN_ROUTES:
        editor = container.locator(".CodeMirror")
        editor.click()
        page.keyboard.insert_text(text)
        sync_codemirror(editor)
    else:
        container.get_by_label("content", exact=True).fill(text)


def strip_origin(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url)


def submit_and_wait(page: Page, button: Locator) -> None:
    """Click a submit control and wait for the resulting navigation.

    Nearly every action in this app redirects back to the *same* URL it was
    submitted from (edit/delete/reply/like all round-trip to the current
    page). `page.wait_for_url(same_url)` can return immediately in that case
    — the URL already "matches" before the POST/redirect/reload happens —
    so callers must wait on the navigation event itself, not the URL string.
    """
    with page.expect_navigation():
        button.click()


def create_thread(
    page: Page,
    route: str,
    title: str,
    content: str,
    *,
    file_path: Path | None = None,
) -> str:
    """Post a new thread through the `/i/{route}` list screen modal.

    Returns the resulting thread detail path, e.g. `/i/BBS/BBS_01...`.
    """
    page.goto(f"/i/{route}")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    expect(form).to_be_visible()
    form.get_by_label("title").fill(title)
    fill_content(page, form, route, content)
    if file_path is not None:
        form.locator('input[type="file"]').set_input_files(str(file_path))
        expect(form.locator('textarea[name="filedata"]')).to_have_value(re.compile("^data:"))
    submit_and_wait(page, form.get_by_role("button", name="submit", exact=True))
    return strip_origin(page.url)


def edit_thread(
    page: Page, route: str, *, title: str | None = None, content: str | None = None
) -> None:
    """Edit the currently displayed thread via its own-post "menu" dropdown."""
    dropdown = page.locator("article.post-detail details.dropdown")
    dropdown.locator("summary").click()
    dropdown.get_by_role("button", name="投稿を編集").click()
    modal = page.locator("#edit-thread")
    # `.modal-shell` itself collapses to zero height once unhidden (its only
    # child is `position: fixed`), so assert on the child that actually
    # renders with real dimensions rather than the wrapper.
    expect(modal.locator(".modal-body")).to_be_visible()
    if title is not None:
        modal.get_by_label("title").fill(title)
    if content is not None:
        if route in MARKDOWN_ROUTES:
            cm_editor = modal.locator(".CodeMirror")
            cm_editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(content)
            sync_codemirror(cm_editor)
        else:
            modal.locator("textarea[name='content']").fill(content)
    submit_and_wait(page, modal.get_by_role("button", name="submit", exact=True))


def open_thread_delete_modal(page: Page) -> Locator:
    dropdown = page.locator("article.post-detail details.dropdown")
    dropdown.locator("summary").click()
    dropdown.get_by_role("button", name="投稿を削除").click()
    modal = page.locator("#delete-thread")
    expect(modal.locator(".modal-body")).to_be_visible()
    return modal


def submit_deletepass(page: Page, modal: Locator, deletepass: str) -> None:
    modal.locator('input[name="deletepass"]').fill(deletepass)
    submit_and_wait(page, modal.get_by_role("button", name="Submit", exact=True))


def submit_deletepass_blocked(modal: Locator, deletepass: str) -> None:
    """Wrong confirmation text is blocked client-side (pattern) — no navigation."""
    field = modal.locator('input[name="deletepass"]')
    field.fill(deletepass)
    modal.get_by_role("button", name="Submit", exact=True).click()
    assert field.evaluate("el => el.validity.patternMismatch") is True
    expect(modal.locator(".modal-body")).to_be_visible()


def delete_thread(page: Page, deletepass: str) -> None:
    modal = open_thread_delete_modal(page)
    submit_deletepass(page, modal, deletepass)


def reply_to_thread(page: Page, route: str, content: str) -> None:
    """Reply to the currently open thread detail page ("このスレッドに返信する")."""
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    expect(form).to_be_visible()
    fill_content(page, form, route, content)
    submit_and_wait(page, form.get_by_role("button", name="Submit", exact=True))


def log_item_by_text(page: Page, text: str) -> Locator:
    """The innermost `.log-item` whose own body contains `text`.

    A nested reply's text also shows up inside every ancestor's rendered
    text, so `.filter(has_text=...)` alone is ambiguous; `.last` picks the
    deepest (most specific, and therefore correct) match.
    """
    return page.locator("article.log-item").filter(has_text=text).last


def _own_log_row(log_item: Locator, selector: str) -> Locator:
    return log_item.locator(f":scope > div.post-row > div > {selector}")


def log_reply_toggle(log_item: Locator) -> Locator:
    return _own_log_row(log_item, "details.log-reply-toggle")


def log_menu_dropdown(log_item: Locator) -> Locator:
    return _own_log_row(log_item, "div.post-head > details.dropdown")


def log_edit_modal(log_item: Locator) -> Locator:
    return _own_log_row(log_item, "div.modal-shell").filter(has_text="ログを編集する")


def log_delete_modal(log_item: Locator) -> Locator:
    return _own_log_row(log_item, "div.modal-shell").filter(has_text="ログを削除する")


def log_replies_disclosure(log_item: Locator) -> Locator:
    return _own_log_row(log_item, "details.reply-disclosure")


def log_like_button(log_item: Locator) -> Locator:
    return log_item.locator(":scope > div.post-row > div.like-box button.like-button")


def reply_to_log(page: Page, route: str, log_item: Locator, content: str) -> None:
    toggle = log_reply_toggle(log_item)
    toggle.locator("summary").click()
    form = toggle.locator("form")
    expect(form).to_be_visible()
    fill_content(page, form, route, content)
    submit_and_wait(page, form.get_by_role("button", name="Submit", exact=True))


def edit_log(page: Page, route: str, log_item: Locator, content: str) -> None:
    log_menu_dropdown(log_item).locator("summary").click()
    log_menu_dropdown(log_item).get_by_role("button", name="ログを編集").click()
    modal = log_edit_modal(log_item)
    expect(modal.locator(".modal-body")).to_be_visible()
    if route in MARKDOWN_ROUTES:
        cm_editor = modal.locator(".CodeMirror")
        cm_editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(content)
        sync_codemirror(cm_editor)
    else:
        modal.locator('textarea[name="content"]').fill(content)
    submit_and_wait(page, modal.get_by_role("button", name="Submit", exact=True))


def open_log_delete_modal(log_item: Locator) -> Locator:
    log_menu_dropdown(log_item).locator("summary").click()
    log_menu_dropdown(log_item).get_by_role("button", name="ログを削除").click()
    modal = log_delete_modal(log_item)
    expect(modal.locator(".modal-body")).to_be_visible()
    return modal


def delete_log(page: Page, log_item: Locator, deletepass: str) -> None:
    modal = open_log_delete_modal(log_item)
    submit_deletepass(page, modal, deletepass)


def like_and_wait(page: Page, like_button: Locator) -> None:
    """Click a thread/log like button and wait for the redirect back."""
    submit_and_wait(page, like_button)
