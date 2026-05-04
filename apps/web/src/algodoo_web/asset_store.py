"""Persist thread attachments: local media/ or optional S3 (SPEC §18 / §575)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import boto3
from algodoo_domain.models import LegacyRoute
from algodoo_data.uploads import (
    parse_data_url,
    validate_jpeg_bytes,
    validate_phz_bytes,
    validate_phn_bytes,
)

from algodoo_web.config import get_settings


def media_root() -> Path:
    return Path(__file__).resolve().parent / "media"


def media_public_url(key: str) -> str:
    if not key:
        return ""
    k = key.strip()
    if k.startswith(("data:", "http://", "https://")):
        return k
    if k.startswith("/media/"):
        return k
    if k.startswith(("IMAGE/", "DATA/")):
        base = get_settings().asset_public_base_url
        if base:
            return f"{base}/{k}"
        return f"/media/{k}"
    return k


def _s3_object_key(storage_key: str) -> str:
    prefix = get_settings().asset_s3_prefix
    return f"{prefix}/{storage_key}" if prefix else storage_key


def _persist_file_bytes(storage_key: str, body: bytes, content_type: str) -> str | None:
    """Return error message or None on success."""
    settings = get_settings()
    if not settings.asset_s3_bucket:
        path = media_root() / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return None
    client = boto3.client("s3", region_name=settings.aws_region)
    key = _s3_object_key(storage_key)
    extra: dict = {"Bucket": settings.asset_s3_bucket, "Key": key, "Body": body, "ContentType": content_type}
    if settings.asset_s3_public_acl:
        extra["ACL"] = "public-read"
    try:
        client.put_object(**extra)
    except Exception as exc:  # noqa: BLE001 — surface to caller
        return str(exc)
    return None


def normalize_and_persist_filedata(
    *,
    route: LegacyRoute,
    thread_id: str,
    filedata: list[str],
) -> tuple[list[str], str | None]:
    """
    Replace Data URLs with on-disk keys under IMAGE/ or DATA/.
    Existing IMAGE/… or DATA/… lines are kept (for smoke fixtures and API keys).
    """
    if route not in (LegacyRoute.IMAGE, LegacyRoute.DATA):
        if any(line.strip() for line in filedata):
            return [], "filedata is not supported for this route"
        return [], None
    out: list[str] = []
    img_idx = 0
    data_idx = 0
    root = media_root()
    if not get_settings().asset_s3_bucket:
        (root / "IMAGE").mkdir(parents=True, exist_ok=True)
        (root / "DATA").mkdir(parents=True, exist_ok=True)

    for item in filedata:
        if not item:
            continue
        if not item.startswith("data:"):
            if item.startswith(("IMAGE/", "DATA/")):
                out.append(item)
            continue
        parsed = parse_data_url(item)
        if not parsed:
            return [], "invalid Data URL"
        mime, raw = parsed
        if route == LegacyRoute.IMAGE:
            if mime != "image/jpeg":
                return [], "IMAGE route requires JPEG Data URLs"
            if err := validate_jpeg_bytes(raw):
                return [], err
            key = f"IMAGE/{thread_id}_{img_idx}.jpg"
            img_idx += 1
            if err := _persist_file_bytes(key, raw, "image/jpeg"):
                return [], err
            out.append(key)
        elif route == LegacyRoute.DATA:
            if mime == "application/zip":
                if err := validate_phz_bytes(raw):
                    return [], err
                key = f"DATA/{thread_id}_{data_idx}.phz"
                if err := _persist_file_bytes(key, raw, "application/zip"):
                    return [], err
                out.append(key)
                try:
                    zf = zipfile.ZipFile(io.BytesIO(raw))
                    thumb_name = next(n for n in zf.namelist() if n.lower().endswith("thumb.png"))
                    thumb_bytes = zf.read(thumb_name)
                except (StopIteration, KeyError, OSError):
                    return [], "PHZ thumb.png could not be read"
                thumb_key = f"DATA/{thread_id}_{data_idx}_thumb.png"
                if err := _persist_file_bytes(thumb_key, thumb_bytes, "image/png"):
                    return [], err
                out.append(thumb_key)
                data_idx += 1
            elif mime == "text/plain":
                if err := validate_phn_bytes(raw):
                    return [], err
                key = f"DATA/{thread_id}_{data_idx}.phn"
                if err := _persist_file_bytes(key, raw, "text/plain; charset=utf-8"):
                    return [], err
                out.append(key)
                data_idx += 1
            else:
                return [], "DATA uploads must be application/zip (PHZ) or text/plain (PHN) Data URLs"
        else:
            return [], "filedata is only supported for IMAGE and DATA routes"

    return out, None
