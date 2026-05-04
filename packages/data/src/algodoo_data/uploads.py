"""Server-side checks for thread attachments (SPEC §13 / §18)."""

from __future__ import annotations

import base64
import binascii
import io
import zipfile

from algodoo_domain.models import LegacyRoute

_JPEG_PREFIX = "data:image/jpeg;base64,"


def parse_data_url(value: str) -> tuple[str, bytes] | None:
    """Return (mime, raw_bytes) or None if not a data URL."""
    if not value.startswith("data:") or "," not in value:
        return None
    head, b64 = value.split(",", 1)
    mime = head.split(";", 1)[0].split(":", 1)[1].strip().lower()
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
            if not item or not item.startswith("data:"):
                continue
            if not item.lower().startswith(_JPEG_PREFIX.lower()):
                return "IMAGE filedata must use image/jpeg Data URLs"
            parsed = parse_data_url(item)
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
            if item.startswith("data:"):
                parsed = parse_data_url(item)
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
                    return "DATA uploads must be application/zip (PHZ) or text/plain (PHN) Data URLs"
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
