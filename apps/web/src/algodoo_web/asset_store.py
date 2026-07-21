"""Persist thread attachments: local media/ or optional S3 (SPEC §18 / §575)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import boto3
from algodoo_data.uploads import (
    parse_data_url,
    validate_jpeg_bytes,
    validate_phn_bytes,
    validate_phz_bytes,
    validate_storage_key,
)
from algodoo_domain.models import LegacyRoute

from algodoo_web.config import get_settings

# PHZ zip extraction caps (OWASP A04, issue #19): guard against zip bombs
# before reading entries out of an uploaded archive.
MAX_PHZ_ENTRIES = 200
MAX_PHZ_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


def media_root() -> Path:
    override = get_settings().media_root_override
    if override:
        return Path(override)
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
    # Unknown formats are not passed through verbatim (OWASP A03, issue #28):
    # only site-relative paths (single leading slash) survive; anything else
    # (javascript:, protocol-relative //host, backslash tricks, ...) renders
    # as an empty src, which the templates guard with {% if %} blocks.
    if k.startswith("/") and not k.startswith(("//", "/\\")):
        return k
    return ""


def asset_s3_client_kwargs() -> dict:
    settings = get_settings()
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.asset_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.asset_s3_endpoint_url
    if settings.asset_s3_access_key_id or settings.asset_s3_secret_access_key:
        if not settings.asset_s3_access_key_id or not settings.asset_s3_secret_access_key:
            raise RuntimeError(
                "ASSET_S3_ACCESS_KEY_ID and ASSET_S3_SECRET_ACCESS_KEY must be set together"
            )
        kwargs["aws_access_key_id"] = settings.asset_s3_access_key_id
        kwargs["aws_secret_access_key"] = settings.asset_s3_secret_access_key
    return kwargs


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
    client = boto3.client("s3", **asset_s3_client_kwargs())
    key = _s3_object_key(storage_key)
    extra: dict = {
        "Bucket": settings.asset_s3_bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
    }
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
    Existing IMAGE/… or DATA/… lines are kept (for integration fixtures and API keys).
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
            if err := validate_storage_key(route, item):
                return [], err
            out.append(item)
            continue
        try:
            parsed = parse_data_url(item)
        except ValueError as exc:  # oversize payload (MAX_UPLOAD_BYTES in uploads.py)
            return [], str(exc)
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
                # Zip-bomb guard (issue #19): check declared entry counts and
                # uncompressed sizes before anything (validate_phz_bytes
                # included) walks the archive's entries.
                try:
                    zf = zipfile.ZipFile(io.BytesIO(raw))
                    infos = zf.infolist()
                except (OSError, zipfile.BadZipFile):
                    return [], "PHZ is not a valid zip archive"
                if len(infos) > MAX_PHZ_ENTRIES:
                    return [], "PHZ contains too many entries"
                if sum(info.file_size for info in infos) > MAX_PHZ_TOTAL_UNCOMPRESSED_BYTES:
                    return [], "PHZ uncompressed size exceeds the limit"
                if err := validate_phz_bytes(raw):
                    return [], err
                try:
                    thumb_name = next(n for n in zf.namelist() if n.lower().endswith("thumb.png"))
                    thumb_bytes = zf.read(thumb_name)
                except (StopIteration, KeyError, OSError, zipfile.BadZipFile):
                    return [], "PHZ thumb.png could not be read"
                key = f"DATA/{thread_id}_{data_idx}.phz"
                if err := _persist_file_bytes(key, raw, "application/zip"):
                    return [], err
                out.append(key)
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
                msg = (
                    "DATA uploads must be application/zip (PHZ) "
                    "or text/plain (PHN) Data URLs"
                )
                return [], msg
        else:
            return [], "filedata is only supported for IMAGE and DATA routes"

    return out, None
