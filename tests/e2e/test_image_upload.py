"""SPEC.md §13.1 (IMAGE attachments) and the IMAGE-specific list/detail rendering."""

from __future__ import annotations

from auth import login
from board import create_thread, has_class
from files import make_png
from playwright.sync_api import Page, expect


def test_image_thread_shows_preview_in_list_and_slideshow_in_detail(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    login(page, username)
    title = f"Image {unique_id}"
    image = make_png(tmp_path)
    thread_path = create_thread(page, "IMAGE", title, "image thread body", file_path=image)

    article = page.locator("article.post-detail")
    slideshow = article.locator("#image-slideshow")
    expect(slideshow).to_be_visible()
    expect(slideshow.locator("img.slide-main")).to_have_attribute("alt", "uploaded image")
    expect(slideshow.locator("button.slide-thumb")).to_have_count(1)
    expect(slideshow.locator("button.slide-thumb.is-active")).to_have_count(1)

    page.goto("/i/IMAGE")
    item = page.locator("div.thread-item").filter(has_text=title)
    expect(item).to_have_class(has_class("has-preview"))
    expect(item.locator("img.thread-preview")).to_be_visible()
    expect(item.locator("a.thread-link")).to_have_attribute("href", thread_path)
