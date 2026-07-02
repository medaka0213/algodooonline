"""SPEC.md §3: broken legacy Navbar links must redirect to the canonical /i/ routes."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page


@pytest.mark.parametrize(
    ("legacy_path", "canonical_path"),
    [
        ("/BBS", "/i/BBS"),
        ("/Wiki", "/i/WIKI"),
        ("/Image", "/i/IMAGE"),
        ("/Data", "/i/DATA"),
    ],
)
def test_legacy_display_alias_redirects(page: Page, legacy_path: str, canonical_path: str) -> None:
    page.goto(legacy_path)
    assert re.sub(r"^https?://[^/]+", "", page.url) == canonical_path


def test_unknown_url_falls_back_to_home(page: Page) -> None:
    page.goto("/this/path/does/not/exist")
    assert re.sub(r"^https?://[^/]+", "", page.url) == "/"
