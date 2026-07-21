"""SPEC.md §13.1 (IMAGE attachments) and the IMAGE-specific list/detail rendering."""

from __future__ import annotations

from auth import login
from board import create_thread, has_class, open_thread_edit_modal
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


def test_image_form_shows_thumbnail_preview_instead_of_raw_data_url(
    page: Page, username: str, tmp_path
) -> None:
    login(page, username)
    page.goto("/i/IMAGE")
    toggle = page.locator("details.modal-toggle")
    toggle.locator("summary").click()
    form = toggle.locator("form")
    expect(form).to_be_visible()
    # The filedata textarea is only a Data URL transport on upload boards;
    # the drop zone shows thumbnails instead.
    expect(form.locator('textarea[name="filedata"]')).to_be_hidden()
    form.locator('input[type="file"]').set_input_files(
        [str(make_png(tmp_path)), str(make_png(tmp_path, "second.png"))]
    )
    expect(form.locator(".file-preview img")).to_have_count(2)
    page.wait_for_function(
        """() => [...document.querySelectorAll("details.modal-toggle .file-preview img")]
              .every(el => el.complete && el.naturalWidth > 0)"""
    )


def test_image_edit_form_shows_existing_images_as_thumbnails(
    page: Page, username: str, unique_id: str, tmp_path
) -> None:
    login(page, username)
    create_thread(
        page,
        "IMAGE",
        f"Image edit preview {unique_id}",
        "image preview body",
        file_path=make_png(tmp_path),
    )
    modal = open_thread_edit_modal(page)
    thumb = modal.locator(".file-preview img")
    expect(thumb).to_have_count(1)
    src = thumb.get_attribute("src")
    assert src is not None and src.endswith(".jpg")
