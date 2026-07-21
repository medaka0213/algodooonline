from __future__ import annotations

import base64
import itertools
import os
import pathlib
import secrets
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest
import pytest_html
from auth import login
from playwright.sync_api import Page
from slugify import slugify

_counter = itertools.count()
# Random per-process, not per-test: the DynamoDB-backed stack the app service
# runs against can be a persistent volume reused across manual/local runs
# (see docker-compose.yml), so a purely sequential id ("e2e0", "e2e1", ...)
# can collide with leftover data from an earlier run against the same store.
_run_id = secrets.token_hex(3)

_FFMPEG = shutil.which("ffmpeg")
_SCREENSHOT_KEY = pytest.StashKey[bytes]()

# [A07] Hosts this suite may ever be pointed at. The tests create users, log
# in with throwaway credentials and mutate data, so they must never run
# against a real deployment. "app"/"webapp" are the docker-compose service
# name and its network alias (see docker-compose.yml: Chromium force-upgrades
# a host literally named "app" to https, hence the "webapp" alias).
_ALLOWED_BASE_URL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "app", "webapp"})


def pytest_configure(config: pytest.Config) -> None:
    # Video recording is opt-in: pytest.ini defaults to retain-on-failure so
    # passing runs don't embed recordings of auth screens (typed usernames,
    # signup flows) into the self-contained report.html CI artifact. Set
    # E2E_VIDEO=on|off|retain-on-failure to override without editing
    # pytest.ini; an explicit --video on the CLI is clobbered only when the
    # env var is set.
    video = os.environ.get("E2E_VIDEO")
    if video:
        config.option.video = video

    _guard_base_url()


def _guard_base_url() -> None:
    """Fail fast unless BASE_URL points at a known local/compose host.

    Override hatches for intentional non-local runs:
    - E2E_ALLOW_HOST: comma-separated extra hostnames to allow.
    - E2E_ALLOW_UNSAFE_BASE_URL=1: skip the guard entirely.
    Public (e.g. https) domains are never allowed silently.
    """
    if os.environ.get("E2E_ALLOW_UNSAFE_BASE_URL") == "1":
        return
    raw = os.environ.get("BASE_URL")
    if not raw:
        # Unset means the base_url fixture's http://127.0.0.1:8080 default.
        return
    host = (urlsplit(raw).hostname or "").lower()
    allowed = set(_ALLOWED_BASE_URL_HOSTS)
    extra = os.environ.get("E2E_ALLOW_HOST")
    if extra:
        allowed.update(h.strip().lower() for h in extra.split(",") if h.strip())
    if host not in allowed:
        pytest.exit(
            f"Refusing to run e2e tests against BASE_URL={raw!r}: host {host!r} is not "
            f"in the local allowlist {sorted(_ALLOWED_BASE_URL_HOSTS)}. These tests "
            "create users and mutate data and must not target real deployments. "
            "For an intentional non-local run set E2E_ALLOW_HOST=<host> (comma-"
            "separated) or E2E_ALLOW_UNSAFE_BASE_URL=1.",
            returncode=2,
        )


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


def _video_path(item: pytest.Item) -> pathlib.Path | None:
    # Mirrors pytest-playwright's own artifact naming
    # (pytest_playwright.output_path / _build_artifact_test_folder) so we can
    # find the video it just wrote during context teardown, without needing
    # pytest-playwright to expose that path itself.
    output_dir = item.config.getoption("--output") or "test-results"
    video = pathlib.Path(output_dir) / slugify(item.nodeid) / "video.webm"
    return video if video.is_file() else None


def _mp4_data_uri(webm: pathlib.Path) -> str | None:
    """Transcode Playwright's WebM recording to H.264 MP4 and return it as a
    base64 data: URI.

    Playwright only records WebM (VP8). Safari can't play WebM at all, and
    pytest-html's built-in media viewer hardcodes `<source type="video/mp4">`
    (its JS never rewrites the type), so feeding it WebM makes stricter
    engines refuse to decode it. H.264 MP4 plays in every browser, so we
    self-author the <video> markup (below) against a real MP4. Playwright's
    bundled ffmpeg is encode-stripped (no MP4 muxer), hence the system ffmpeg
    installed by scripts/e2e-local.sh.
    """
    if not _FFMPEG:
        return None
    mp4 = webm.with_suffix(".mp4")
    try:
        subprocess.run(
            [
                _FFMPEG, "-y", "-loglevel", "error", "-i", str(webm),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(mp4),
            ],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    if not mp4.is_file():
        return None
    return "data:video/mp4;base64," + base64.b64encode(mp4.read_bytes()).decode()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Embed the screenshot and the run video directly into
    test-results/report.html so opening that one file is enough: expand a test
    row and both the final screenshot and a playable MP4 of the run are shown
    inline, no arrow-navigation and no digging through test-results/<test>/.

    We build our own <img>/<video> HTML (an "html" extra) instead of using
    extras.png/extras.video because pytest-html's media viewer shows only one
    asset at a time behind prev/next arrows and hardcodes a video/mp4 <source>
    type. Stacking our own markup makes both artifacts visible at once with a
    correct MP4 source.
    """
    outcome = yield
    report = outcome.get_result()

    # Screenshot must be taken during `call`, while the page still reflects the
    # final assertion state; by `teardown` the context is being closed.
    if report.when == "call":
        page: Page | None = item.funcargs.get("page")
        if page is not None and not page.is_closed():
            try:
                item.stash[_SCREENSHOT_KEY] = page.screenshot(full_page=True)
            except Exception:
                pass

    # The video file is only flushed when the browser context closes, which
    # happens in `teardown`, so assemble the combined artifact block there.
    if report.when == "teardown":
        blocks: list[str] = []
        shot = item.stash.get(_SCREENSHOT_KEY, None)
        if shot:
            uri = "data:image/png;base64," + base64.b64encode(shot).decode()
            blocks.append(
                '<figure style="margin:0 0 1rem">'
                '<figcaption style="font-weight:600">Final screenshot</figcaption>'
                f'<img style="max-width:100%;border:1px solid #dee2e6" src="{uri}"/>'
                "</figure>"
            )
        video = _video_path(item)
        if video is not None:
            uri = _mp4_data_uri(video)
            if uri is not None:
                blocks.append(
                    '<figure style="margin:0">'
                    '<figcaption style="font-weight:600">Run video</figcaption>'
                    '<video controls preload="metadata" '
                    f'style="max-width:100%;border:1px solid #dee2e6" src="{uri}"></video>'
                    "</figure>"
                )
            else:
                # ffmpeg unavailable: fall back to WebM with the correct type
                # (plays in Chromium/Firefox; the report is still self-contained).
                webm_uri = "data:video/webm;base64," + base64.b64encode(video.read_bytes()).decode()
                blocks.append(
                    '<figure style="margin:0">'
                    '<figcaption style="font-weight:600">Run video (WebM)</figcaption>'
                    '<video controls preload="metadata" '
                    'style="max-width:100%;border:1px solid #dee2e6">'
                    f'<source src="{webm_uri}" type="video/webm"></video>'
                    "</figure>"
                )
        if blocks:
            extra = getattr(report, "extras", [])
            extra.append(pytest_html.extras.html("".join(blocks)))
            report.extras = extra


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
