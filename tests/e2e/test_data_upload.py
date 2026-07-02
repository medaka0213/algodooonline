"""SPEC.md §13.2 (DATA attachments / PHZ) and the DATA-specific list/detail rendering."""

from __future__ import annotations

from auth import login
from board import create_thread, has_class
from files import make_phz
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
