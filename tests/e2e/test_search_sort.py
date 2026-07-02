"""SPEC.md §9: search (highlight/filter) and sort on the board list screen."""

from __future__ import annotations

from auth import login
from board import create_thread
from playwright.sync_api import Page, expect


def test_search_matches_title_and_highlights(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    marker = f"Findme{unique_id}"
    create_thread(page, "BBS", f"{marker} in title", "unrelated body")
    create_thread(page, "BBS", "unrelated title", "unrelated body")

    page.goto(f"/i/BBS?q={marker}")
    items = page.locator("div.thread-item")
    expect(items).to_have_count(1)
    expect(items.locator("h3.thread-title span.bg-warning")).to_have_text(marker)


def test_search_matches_content_only(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    marker = f"BodyFind{unique_id}"
    thread_path = create_thread(page, "BBS", "plain title", f"body contains {marker} inside")
    create_thread(page, "BBS", "another plain title", "irrelevant body")

    page.goto(f"/i/BBS?q={marker}")
    item = page.locator("div.thread-item")
    expect(item).to_have_count(1)
    expect(item.locator("a.thread-link")).to_have_attribute("href", thread_path)
    expect(item.locator(".excerpt span.bg-warning")).to_have_text(marker)


def test_search_requires_all_space_separated_keywords(
    page: Page, username: str, unique_id: str
) -> None:
    login(page, username)
    marker = f"Multi{unique_id}"
    create_thread(page, "BBS", f"{marker} alpha beta", "content")
    create_thread(page, "BBS", f"{marker} only", "content")

    page.goto(f"/i/BBS?q={marker}%20alpha")
    items = page.locator("div.thread-item")
    expect(items).to_have_count(1)
    expect(items.locator("h3.thread-title")).to_contain_text("alpha beta")


def test_sort_newest_vs_oldest_created(page: Page, username: str, unique_id: str) -> None:
    login(page, username)
    older_title = f"Older{unique_id}"
    newer_title = f"Newer{unique_id}"
    create_thread(page, "BBS", older_title, "content")
    create_thread(page, "BBS", newer_title, "content")

    page.goto("/i/BBS?sort=NEWEST_CREATED")
    titles = page.locator("h3.thread-title").all_inner_texts()
    assert titles.index(newer_title) < titles.index(older_title)

    page.goto("/i/BBS?sort=OLDEST_CREATED")
    titles = page.locator("h3.thread-title").all_inner_texts()
    assert titles.index(older_title) < titles.index(newer_title)


def test_sort_select_ui_navigates_with_selected_value(page: Page) -> None:
    page.goto("/i/BBS")
    select = page.locator("select.sort-select")
    select.select_option("BEST")
    page.wait_for_url("**sort=BEST**")
    expect(select).to_have_value("BEST")
