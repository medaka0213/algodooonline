from __future__ import annotations

import itertools
import os
import pathlib
import secrets

import pytest
from auth import login
from playwright.sync_api import Page

_counter = itertools.count()
# Random per-process, not per-test: the DynamoDB-backed stack the app service
# runs against can be a persistent volume reused across manual/local runs
# (see docker-compose.yml), so a purely sequential id ("e2e0", "e2e1", ...)
# can collide with leftover data from an earlier run against the same store.
_run_id = secrets.token_hex(3)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    # pytest.ini's --html=test-results/report.html needs the directory to
    # exist right before pytest-html writes it. Creating it in
    # pytest_configure isn't enough: pytest-playwright wipes its --output
    # dir (also "test-results" by default) at session start to drop stale
    # artifacts from a previous run, and recreates it only when a
    # screenshot/video/trace is actually written for a failing test — so an
    # all-passing run would otherwise leave nothing for pytest-html to write
    # into. `tryfirst=True` runs this before pytest-html's own
    # pytest_sessionfinish, which is where it actually writes the report.
    pathlib.Path("test-results").mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("BASE_URL", "http://127.0.0.1:8080")


@pytest.fixture
def unique_id() -> str:
    """A per-test id that is unique within a single test session run.

    Demo data is always seeded (SEED_DEMO_DATA=true), so every test that
    creates data must use its own marker to avoid colliding with seeded
    threads/logs or with other tests running in the same session.
    """
    return f"e2e{_run_id}{next(_counter)}"


@pytest.fixture
def username(unique_id: str) -> str:
    return f"e2euser{unique_id}"


@pytest.fixture
def logged_in_page(page: Page, username: str) -> Page:
    login(page, username)
    return page
