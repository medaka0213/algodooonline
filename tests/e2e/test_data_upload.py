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
from files import make_big_phz, make_phn, make_phz
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


def test_large_phz_is_uploaded_in_chunks(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    """A file too big for one form post (API Gateway + Lambda carries ~4.7 MB per
    request) is split and PUT in pieces; the form then posts only a reference
    (SPEC §13.4). The thread ends up with the full archive and its thumbnail."""
    login(page, username)
    chunk_puts: list[str] = []
    page.on(
        "request",
        lambda r: chunk_puts.append(r.url) if r.method == "PUT" and "/uploads/" in r.url else None,
    )
    title = f"Chunked {unique_id}"
    big = make_big_phz(tmp_path, 5 * 1024 * 1024)
    page.goto("/i/DATA")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    form.get_by_label("title").fill(title)
    fill_content(page, form, "DATA", "chunked upload")
    form.locator('input[type="file"]').set_input_files(str(big))

    # Progress is shown while it uploads; afterwards the form carries a reference.
    expect(form.locator("#file-list-new")).to_contain_text("アップロード済み")
    expect(form.locator('textarea[name="filedata"]')).to_have_value(
        re.compile(r"^upload:[0-9a-f]{32}:3:\d+:application/zip$")
    )
    assert len(chunk_puts) == 3  # 5 MiB + a little, in 2 MiB pieces
    # The preview still comes from the file chosen in the browser.
    expect(form.locator(".file-preview img")).to_have_count(1)
    submit_button = form.get_by_role("button", name="submit", exact=True)
    expect(submit_button).to_be_enabled()

    submit_and_wait(page, submit_button)
    assert strip_origin(page.url).startswith("/i/DATA/DATA_")
    download_block = page.locator("article.post-detail .download-phz-wrap")
    expect(download_block.locator("img.download-phz-hero-thumb")).to_be_visible()
    link = download_block.get_by_role("link", name="ダウンロード")
    href = link.get_attribute("href")
    assert href is not None and href.endswith(".phz")


def test_file_over_the_per_file_limit_is_refused_before_uploading(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    """Even chunked, a file may not exceed the per-file limit (10 MB): the form
    says so right away and sends nothing."""
    login(page, username)
    requests: list[str] = []
    page.on(
        "request",
        lambda r: requests.append(r.url) if r.method in {"PUT", "POST"} else None,
    )
    too_big = tmp_path / "too-big.phn"
    too_big.write_bytes(b"a" * (11 * 1024 * 1024))
    page.goto("/i/DATA")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    form.locator('input[type="file"]').set_input_files(str(too_big))

    error = form.locator(".form-error[data-upload-error]")
    expect(error).to_contain_text("too-big.phn は大きすぎます")
    expect(error).to_contain_text("上限 10.0 MB")
    expect(form.locator('textarea[name="filedata"]')).to_have_value("")
    assert requests == []

    # Choosing an acceptable file afterwards clears the message.
    form.locator('input[type="file"]').set_input_files(str(make_phn(tmp_path)))
    expect(form.locator(".form-error[data-upload-error]")).to_have_count(0)
    expect(form.locator('textarea[name="filedata"]')).to_have_value(re.compile(r"^data:text/plain"))


def test_form_body_guard_blocks_a_post_that_would_get_a_gateway_413(
    page: Page, username: str, unique_id: str
) -> None:
    """Backstop: whatever ends up in the form, a post above the body ceiling is
    stopped with an explanation instead of reaching API Gateway's bare 413."""
    login(page, username)
    page.goto("/i/DATA")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    form.get_by_label("title").fill(f"Guard {unique_id}")
    fill_content(page, form, "DATA", "body guard")
    form.locator('textarea[name="filedata"]').evaluate("el => { el.value = 'x'.repeat(5000000); }")
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    form.get_by_role("button", name="submit", exact=True).click()
    error = form.locator(".form-error[data-size-error]")
    expect(error).to_contain_text("送信データが大きすぎます")
    page.wait_for_timeout(300)
    assert posts == []
    assert strip_origin(page.url) == "/i/DATA"


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
