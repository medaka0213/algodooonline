"""SPEC.md §4 (layout/navbar) and §4.4 (home) screen coverage."""

from __future__ import annotations

from auth import login
from playwright.sync_api import Page, expect


def test_home_unauthenticated(page: Page) -> None:
    page.goto("/")

    expect(page.locator("h1.home-title")).to_have_text("AlgodooOnline")
    expect(page.locator(".home-status")).to_have_text("ログインしてください")

    nav = page.locator("nav.index-nav")
    expect(nav.get_by_role("link", name="BBS掲示板")).to_have_attribute("href", "/i/BBS")
    expect(nav.get_by_role("link", name="Wiki")).to_have_attribute("href", "/i/WIKI")
    expect(nav.get_by_role("link", name="画像掲示板")).to_have_attribute("href", "/i/IMAGE")
    expect(nav.get_by_role("link", name="Phz/Phnデータ掲示板")).to_have_attribute("href", "/i/DATA")

    # No breadcrumb on the home screen (SPEC §4.1).
    expect(page.locator("ol.breadcrumb")).to_have_count(0)


def test_navbar_brand_and_sitemap(page: Page) -> None:
    page.goto("/")

    expect(page.locator("a.navbar-brand")).to_have_text("AlgodooOnline [ver 2.0]")
    expect(page.locator("a.navbar-brand")).to_have_attribute("href", "/")

    sitemap = page.locator(".navbar-left details.dropdown")
    expect(sitemap.locator("summary")).to_contain_text("サイトマップ")
    sitemap.locator("summary").click()
    menu = sitemap.locator(".dropdown-menu")
    expect(menu.get_by_role("link", name="ホーム")).to_have_attribute("href", "/")
    expect(menu.get_by_role("link", name="掲示板")).to_have_attribute("href", "/i/BBS")
    expect(menu.get_by_role("link", name="Wiki")).to_have_attribute("href", "/i/WIKI")
    expect(menu.get_by_role("link", name="画像")).to_have_attribute("href", "/i/IMAGE")
    expect(menu.get_by_role("link", name="データ")).to_have_attribute("href", "/i/DATA")


def test_navbar_unauthenticated_shows_auth_link(page: Page) -> None:
    page.goto("/")
    auth_link = page.locator(".navbar-right").get_by_role("link", name="ユーザー認証")
    expect(auth_link).to_have_attribute("href", "/auth/login")


def test_home_and_navbar_after_login(page: Page, username: str) -> None:
    login(page, username)
    page.goto("/")

    expect(page.locator(".home-status")).to_contain_text(f"ユーザー: {username} (local-{username})")

    dropdown = page.locator(".navbar-right details.dropdown")
    expect(dropdown.locator("summary")).to_contain_text(f"Hello, {username}!")
    dropdown.locator("summary").click()
    menu = dropdown.locator(".dropdown-menu")
    expect(menu.get_by_role("link", name="ログアウト")).to_have_attribute("href", "/auth/logout")
    expect(menu.get_by_role("link", name="パスワードを変更")).to_have_attribute(
        "href", "/auth/changepass"
    )
