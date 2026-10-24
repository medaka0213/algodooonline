"""Server-side checks for thread attachments (SPEC §13 / §18)."""

from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from dataclasses import dataclass

from algodoo_domain.models import LegacyRoute

# Maximum decoded size of a single Data-URL payload (OWASP A04, issue #19).
# Data-URL contents are persisted to S3 (or an S3-compatible store) or the local media dir (only the
# storage key goes into DynamoDB), so a 10 MB cap comfortably covers PHZ scenes
# and JPEG uploads while bounding memory used by base64 decoding.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Base64 expands data 4:3; check the encoded length BEFORE decoding.
_MAX_BASE64_LEN = (MAX_UPLOAD_BYTES * 4) // 3 + 4

# Chunked uploads: a file larger than a form post can carry (see
# MAX_FORM_BODY_BYTES in algodoo_web.config) is sent as several PUTs of at most
# MAX_UPLOAD_CHUNK_BYTES, then referenced from filedata as
# `upload:{id}:{chunks}:{size}:{mime}` instead of an inline Data URL.
# 3 MiB per request stays well below the API Gateway + Lambda body ceiling
# (about 4.7 MB; the gateway base64-encodes the body, x4/3).
MAX_UPLOAD_CHUNK_BYTES = 3 * 1024 * 1024
# What the browser actually sends; leaves headroom under the server cap above.
CLIENT_UPLOAD_CHUNK_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_CHUNKS = 16

_JPEG_PREFIX = "data:image/jpeg;base64,"
_UPLOAD_ID = re.compile(r"[0-9a-f]{32}")
_UPLOAD_REF = re.compile(r"upload:([0-9a-f]{32}):(\d{1,2}):(\d{1,9}):([a-z]+/[a-z0-9.+-]+)")
_UPLOAD_MIMES = {
    LegacyRoute.IMAGE: frozenset({"image/jpeg"}),
    LegacyRoute.DATA: frozenset({"application/zip", "text/plain"}),
}

_IMAGE_KEY = re.compile(r"^IMAGE/[A-Za-z0-9_.-]+\.(?:jpe?g|png|gif|webp)$")
_DATA_KEY = re.compile(r"^DATA/[A-Za-z0-9_.-]+(?:\.(?:phz|phn)|_thumb\.png)$")


@dataclass(frozen=True)
class UploadRef:
    """A filedata line pointing at a file that was uploaded in chunks."""

    upload_id: str
    chunks: int
    size: int
    mime: str


def is_valid_upload_id(value: str) -> bool:
    return bool(_UPLOAD_ID.fullmatch(value))


def parse_upload_ref(value: str) -> UploadRef | None:
    """Parse `upload:{id}:{chunks}:{size}:{mime}`; None if malformed or out of range."""
    match = _UPLOAD_REF.fullmatch(value)
    if not match:
        return None
    upload_id, chunks, size, mime = match.groups()
    ref = UploadRef(upload_id, int(chunks), int(size), mime)
    if not 1 <= ref.chunks <= MAX_UPLOAD_CHUNKS or not 1 <= ref.size <= MAX_UPLOAD_BYTES:
        return None
    return ref


def validate_upload_ref(route: LegacyRoute, value: str) -> str | None:
    """Return an error message for a malformed or wrong-type upload reference."""
    ref = parse_upload_ref(value)
    if ref is None:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return f"invalid upload reference (files are limited to {limit_mb} MB)"
    if ref.mime not in _UPLOAD_MIMES.get(route, frozenset()):
        return f"upload type {ref.mime} is not supported for route {route.value}"
    return None


def validate_storage_key(route: LegacyRoute, key: str) -> str | None:
    """Reject pre-existing filedata keys that do not match the old S3 layout."""
    if route == LegacyRoute.IMAGE:
        pattern = _IMAGE_KEY
    elif route == LegacyRoute.DATA:
        pattern = _DATA_KEY
    else:
        return f"filedata keys are not supported for route {route.value}"
    if not pattern.fullmatch(key):
        return f"invalid filedata key: {key}"
    return None


def parse_data_url(value: str) -> tuple[str, bytes] | None:
    """Return (mime, raw_bytes) or None if not a data URL.

    Raises ValueError when the payload exceeds MAX_UPLOAD_BYTES; callers should
    map that to HTTP 400/413.
    """
    if not value.startswith("data:") or "," not in value:
        return None
    head, b64 = value.split(",", 1)
    mime = head.split(";", 1)[0].split(":", 1)[1].strip().lower()
    if len(b64) > _MAX_BASE64_LEN:
        raise ValueError(
            f"upload payload too large: exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
        )
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    return mime, raw


def validate_jpeg_bytes(raw: bytes) -> str | None:
    if len(raw) < 3 or raw[:3] != b"\xff\xd8\xff":
        return "IMAGE payload is not a valid JPEG"
    return None


def validate_thread_filedata(route: LegacyRoute, filedata: list[str]) -> str | None:
    """Return first validation error message, or None if OK (keys-only paths)."""
    if route == LegacyRoute.IMAGE:
        for item in filedata:
            if item.startswith("upload:"):
                if err := validate_upload_ref(route, item):
                    return err
                continue
            if not item or not item.startswith("data:"):
                continue
            if not item.lower().startswith(_JPEG_PREFIX.lower()):
                return "IMAGE filedata must use image/jpeg Data URLs"
            try:
                parsed = parse_data_url(item)
            except ValueError as exc:
                return str(exc)
            if not parsed:
                return "invalid IMAGE Data URL"
            _mime, raw = parsed
            if err := validate_jpeg_bytes(raw):
                return err
        return None
    if route == LegacyRoute.DATA:
        for item in filedata:
            if not item:
                continue
            if item.startswith("upload:"):
                if err := validate_upload_ref(route, item):
                    return err
                continue
            if item.startswith("data:"):
                try:
                    parsed = parse_data_url(item)
                except ValueError as exc:
                    return str(exc)
                if not parsed:
                    return "invalid DATA Data URL"
                mime, raw = parsed
                if mime == "application/zip":
                    if err := validate_phz_bytes(raw):
                        return err
                elif mime == "text/plain":
                    if err := validate_phn_bytes(raw):
                        return err
                else:
                    return (
                        "DATA uploads must be application/zip (PHZ) "
                        "or text/plain (PHN) Data URLs"
                    )
        return None
    return None


def validate_phz_bytes(raw: bytes) -> str | None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return "PHZ is not a valid zip archive"
    names = zf.namelist()
    lowered = [n.lower() for n in names]

    def has_file(suffix: str) -> bool:
        return any(n.endswith(suffix) for n in lowered)

    for need in ("scene.phn", "checksums.txt", "thumb.png"):
        if not has_file(need):
            return f"PHZ must contain {need}"
    for name in zf.namelist():
        if name.endswith("/") or name.lower().endswith(("scene.phn", "checksums.txt", "thumb.png")):
            continue
        with zf.open(name) as handle:
            head = handle.read(16)
        if not _looks_like_image_bytes(head):
            return f"non-image entry in PHZ: {name}"
    return None


def _looks_like_image_bytes(head: bytes) -> bool:
    if len(head) < 3:
        return False
    if head[:3] == b"\xff\xd8\xff":
        return True
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if head[:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"WEBP":
        return True
    return False


def validate_phn_bytes(raw: bytes) -> str | None:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "PHN must be UTF-8 text"
    return None
