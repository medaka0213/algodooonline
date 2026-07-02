"""SPEC.md §15 (Markdown + sanitizer) and §16 (server-side error display)."""

from __future__ import annotations

from auth import login
from board import create_thread, reply_to_thread
from playwright.sync_api import Page, expect


def test_wiki_thread_renders_markdown(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    content = f"## Heading {unique_id}\n\n**bold {unique_id}**\n\n[a link](https://example.com)"
    create_thread(page, "WIKI", f"Markdown {unique_id}", content)

    body = page.locator("article.post-detail .markdown-body")
    expect(body.locator("h2")).to_have_text(f"Heading {unique_id}")
    expect(body.locator("strong")).to_have_text(f"bold {unique_id}")
    expect(body.get_by_role("link", name="a link")).to_have_attribute(
        "href", "https://example.com"
    )


def test_log_reply_renders_markdown_for_non_bbs_routes(
    page: Page, username: str, unique_id: str
) -> None:
    login(page, username)
    thread_path = create_thread(page, "WIKI", f"LogMarkdown {unique_id}", "thread body")
    reply_to_thread(page, "WIKI", f"**log bold {unique_id}**")
    page.wait_for_url(f"**{thread_path}")

    log_body = page.locator("article.log-item .log-body.markdown-body").first
    expect(log_body.locator("strong")).to_have_text(f"log bold {unique_id}")


def test_sanitizer_strips_script_and_javascript_links(
    page: Page, username: str, unique_id: str
) -> None:
    fired_dialogs = []
    page.on("dialog", lambda dialog: (fired_dialogs.append(dialog.message), dialog.dismiss()))

    login(page, username)
    marker = f"safe{unique_id}"
    content = (
        f"<!-- secret {unique_id} -->visible {marker} text "
        f"[evil](javascript:alert('{unique_id}'))"
        f"<script>window.__e2e_xss_{unique_id} = true;</script>"
    )
    create_thread(page, "WIKI", f"Sanitize {unique_id}", content)

    body = page.locator("article.post-detail .markdown-body")
    expect(body).to_contain_text(f"visible {marker} text")
    expect(body.locator("script")).to_have_count(0)
    html = body.inner_html()
    assert f"secret {unique_id}" not in html
    assert "javascript:" not in html
    assert page.evaluate(f"window.__e2e_xss_{unique_id}") is None
    assert fired_dialogs == []


def test_server_side_validation_error_is_displayed(
    page: Page, username: str, unique_id: str
) -> None:
    login(page, username)
    page.goto("/i/BBS")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")

    # `.fill()` goes through the same value-sanitization path as real typing
    # and is clamped by `maxlength="32"`, so it can't exceed the limit.
    # Setting `.value` via script is not subject to that sanitization (only
    # user-driven input is), which is what actually exercises the server-side
    # length validation (SPEC §14) and its `.form-error` rendering (§16).
    long_title = f"too-long-{unique_id}-" + ("x" * 32)
    title_field = form.get_by_label("title")
    title_field.evaluate(
        "(el, value) => { el.value = value; "
        "el.dispatchEvent(new Event('input', {bubbles: true})); }",
        long_title,
    )
    expect(title_field).to_have_value(long_title)
    form.get_by_label("content", exact=True).fill("content")
    form.get_by_role("button", name="submit", exact=True).click()

    error = page.locator(".form-error")
    expect(error).to_contain_text("Server-side Error")
    expect(error).to_contain_text("title")
