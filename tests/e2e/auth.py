from __future__ import annotations

from playwright.sync_api import Page, expect


def login(page: Page, username: str, password: str = "password123") -> None:
    """Log in through the real /auth/login screen (local pseudo-session backend)."""
    page.goto("/auth/login")
    page.get_by_label("ユーザー名").fill(username)
    page.get_by_label("パスワード", exact=True).fill(password)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url("**/")
    expect(page.locator(".navbar-right")).to_contain_text(f"Hello, {username}!")
