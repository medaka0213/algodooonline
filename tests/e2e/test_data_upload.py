"""SPEC.md §13.2 (DATA attachments / PHZ) and the DATA-specific list/detail rendering."""

from __future__ import annotations

import os
import re

from auth import login
from board import (
    create_thread,
    fill_content,
    has_class,
    open_thread_edit_modal,
    strip_origin,
    submit_and_wait,
)
from files import make_phn, make_phz
from playwright.sync_api import Page, expect


def test_data_thread_shows_download_block_and_list_thumbnail(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    login(page, username)
    title = f"Data {unique_id}"
    phz = make_phz(tmp_path)
    thread_path = create_thread(page, "DATA", title, "data thread body", file_path=phz)

    article = page.locator("article.post-detail")
    download_block = article.locator(".download-phz-wrap")
    expect(download_block.locator("img.download-phz-hero-thumb")).to_be_visible()
    link = download_block.get_by_role("link", name="ダウンロード")
    expect(link).to_be_visible()
    href = link.get_attribute("href")
    assert href is not None and href.endswith(".phz")
    # Old DownloadPHZ/SlideShow render no raw attachment listing (SPEC §7.1).
    expect(article.locator(".attachment")).to_have_count(0)

    page.goto("/i/DATA")
    item = page.locator("div.thread-item").filter(has_text=title)
    expect(item).to_have_class(has_class("has-preview"))
    expect(item.locator("img.thread-preview")).to_be_visible()
    expect(item.locator("a.thread-link")).to_have_attribute("href", thread_path)


def test_migrated_thumbnail_only_data_thread_shows_download_link(
    page: Page, username: str, unique_id: str
) -> None:
    """Migrated Algon2 DATA threads store only `*_thumb.png`; the `.phz`
    download link is derived from it (SPEC §13.2)."""
    login(page, username)
    thumb_key = f"DATA/legacy{unique_id}_0_thumb.png"
    # Legacy JSON API (SPEC §11): session cookie from login() + x-api-key.
    response = page.request.post(
        "/threads/DATA",
        headers={"x-api-key": os.environ.get("LEGACY_X_API_KEY", "local-x-api-key")},
        data={
            "submition": {
                "user_name": username,
                # The local pseudo-session's subject (must match the cookie).
                "user_id": f"local-{username}",
                "title": f"Legacy data {unique_id}",
                "content": "thumbnail-only filedata",
                "filedata": [thumb_key],
            }
        },
    )
    assert response.ok, response.text()
    thread_id = response.json()["thread"]["thread_id"]

    page.goto(f"/i/DATA/{thread_id}")
    download_block = page.locator("article.post-detail .download-phz-wrap")
    thumb = download_block.locator("img.download-phz-hero-thumb")
    expect(thumb).to_have_attribute("src", re.compile(re.escape(thumb_key) + "$"))
    link = download_block.get_by_role("link", name="ダウンロード")
    expect(link).to_be_visible()
    expect(link).to_have_attribute(
        "href", re.compile(re.escape(f"DATA/legacy{unique_id}_0.phz") + "$")
    )


def test_oversized_attachment_is_stopped_before_posting(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    """Behind API Gateway + Lambda a body above ~4.7 MB gets a bare 413 from the
    gateway, so the form measures the post and explains the limit instead of
    sending it (SPEC §13.3). A smaller file afterwards posts normally."""
    login(page, username)
    title = f"Too big {unique_id}"
    big = tmp_path / "big.phn"
    big.write_bytes(b"a" * (5 * 1024 * 1024))  # base64 data URL alone is ~7 MB
    page.goto("/i/DATA")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    form.get_by_label("title").fill(title)
    fill_content(page, form, "DATA", "oversized attachment")
    file_input = form.locator('input[type="file"]')
    file_input.set_input_files(str(big))

    # Feedback appears as soon as the file is chosen, before any submit.
    error = form.locator(".form-error[data-size-error]")
    expect(error).to_contain_text("送信データが大きすぎます")
    expect(error).to_contain_text("MB 以上小さくするか")

    # Submit is blocked: the oversized post is never sent.
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    form.get_by_role("button", name="submit", exact=True).click()
    page.wait_for_timeout(500)
    expect(error).to_be_visible()
    assert strip_origin(page.url) == "/i/DATA"
    assert posts == []

    # Swapping in a small file clears the message and the post goes through.
    file_input.set_input_files(str(make_phn(tmp_path)))
    expect(error).to_have_count(0)
    submit_and_wait(page, form.get_by_role("button", name="submit", exact=True))
    assert strip_origin(page.url).startswith("/i/DATA/DATA_")


def test_data_form_shows_phz_thumbnail_preview(page: Page, username: str, tmp_path) -> None:
    login(page, username)
    page.goto("/i/DATA")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    expect(form).to_be_visible()
    expect(form.locator('textarea[name="filedata"]')).to_be_hidden()
    form.locator('input[type="file"]').set_input_files(str(make_phz(tmp_path)))
    thumb = form.locator(".file-preview img")
    expect(thumb).to_have_count(1)
    # thumb.png is pulled out of the .phz client-side into a blob: URL.
    expect(thumb).to_have_attribute("src", re.compile(r"^blob:"))
    page.wait_for_function(
        """() => { const el = document.querySelector("details.modal-toggle .file-preview img");
              return el && el.complete && el.naturalWidth > 0; }"""
    )


def test_data_edit_form_shows_phz_thumbnail(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    login(page, username)
    create_thread(
        page,
        "DATA",
        f"Data edit preview {unique_id}",
        "phz preview body",
        file_path=make_phz(tmp_path),
    )
    modal = open_thread_edit_modal(page)
    thumb = modal.locator(".file-preview img")
    expect(thumb).to_have_count(1)
    src = thumb.get_attribute("src")
    assert src is not None and src.endswith("_thumb.png")
