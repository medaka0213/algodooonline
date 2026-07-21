from __future__ import annotations

import secrets

from playwright.sync_api import Page, expect


def generate_password() -> str:
    """Strong random throwaway password for test-created users.

    Satisfies the pool policy (8+ chars; the "E2e!" prefix guarantees upper,
    lower, digit and symbol classes even if Cognito-style rules are enabled).
    Random per call so no fixed credential ever lands in the repo, logs or
    report artifacts.
    """
    return "E2e!" + secrets.token_urlsafe(12)


# One password per test process: the local pseudo-session backend ignores it,
# and each test uses a unique per-run username, so sharing within a process is
# safe and keeps login() call sites simple.
TEST_PASSWORD = generate_password()


def login(page: Page, username: str, password: str = TEST_PASSWORD) -> None:
    """Log in through the real /auth/login screen (local pseudo-session backend)."""
    page.goto("/auth/login")
    page.get_by_label("ユーザー名").fill(username)
    page.get_by_label("パスワード", exact=True).fill(password)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url("**/")
    expect(page.locator(".navbar-right")).to_contain_text(f"Hello, {username}!")
