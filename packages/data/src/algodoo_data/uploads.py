"""Server-side checks for thread attachments (SPEC §13 / §18)."""

from __future__ import annotations

import base64
import binascii

from algodoo_domain.models import LegacyRoute

_JPEG_PREFIX = "data:image/jpeg;base64,"


def validate_thread_filedata(route: LegacyRoute, filedata: list[str]) -> str | None:
    """Return first validation error message, or None if OK."""
    if route == LegacyRoute.IMAGE:
        for item in filedata:
            if not item or not item.startswith("data:"):
                continue
            if not item.lower().startswith(_JPEG_PREFIX.lower()):
                return "IMAGE filedata must use image/jpeg Data URLs"
            try:
                b64 = item.split(",", 1)[1]
                raw = base64.b64decode(b64, validate=True)
            except (binascii.Error, IndexError):
                return "invalid base64 in IMAGE Data URL"
            if len(raw) < 3 or raw[:3] != b"\xff\xd8\xff":
                return "IMAGE Data URL is not a valid JPEG"
        return None
    if route == LegacyRoute.DATA:
        for item in filedata:
            if not item or item.startswith("data:"):
                return "DATA filedata must be storage keys, not inline Data URLs"
            if item.lower().endswith(".phz"):
                err = _validate_phz_zip_placeholder(item)
                if err:
                    return err
        return None
    return None


def _validate_phz_zip_placeholder(key: str) -> str | None:
    """When running with local fixtures, accept keys only. Full zip bytes check is for uploaded blobs."""
    if key.startswith("DATA/") and "sample" in key:
        return None
    return None
