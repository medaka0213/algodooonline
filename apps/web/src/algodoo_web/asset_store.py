"""Persist thread attachments: local media/ or optional S3 (SPEC §18 / §575)."""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path

import boto3
from algodoo_data.uploads import (
    MAX_UPLOAD_BYTES,
    UploadRef,
    parse_data_url,
    parse_upload_ref,
    validate_jpeg_bytes,
    validate_phn_bytes,
    validate_phz_bytes,
    validate_storage_key,
)
from algodoo_domain.models import LegacyRoute
from botocore.exceptions import ClientError

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


# --- Chunked uploads ---------------------------------------------------------
# A file too big for one form post is PUT in several chunks first (browser ->
# /uploads/{id}/{index}); the thread form then carries only an
# `upload:{id}:{chunks}:{size}:{mime}` reference. Chunks live in the asset
# bucket under a private prefix (no ACL, so never publicly readable; the S3
# lifecycle rule in infra/aws expires them) because Lambda invocations do not
# share a filesystem. Without a bucket (local dev) they go to a temp dir that is
# NOT under media_root(), which /media serves publicly.
UPLOAD_TMP_PREFIX = "UPLOAD-TMP"


@lru_cache
def _s3_client():
    return boto3.client("s3", **asset_s3_client_kwargs())


def _chunk_path(owner: str, upload_id: str, index: int) -> str:
    # Hash the owner so any session subject maps to a safe, fixed-length path part.
    namespace = hashlib.sha256(owner.encode()).hexdigest()[:32]
    return f"{namespace}/{upload_id}/{index:04d}"


def _local_upload_root() -> Path:
    return Path(tempfile.gettempdir()) / "algodoo-upload-tmp"


def put_upload_chunk(owner: str, upload_id: str, index: int, body: bytes) -> str | None:
    """Store one chunk; return an error message or None on success."""
    path = _chunk_path(owner, upload_id, index)
    settings = get_settings()
    if not settings.asset_s3_bucket:
        target = _local_upload_root() / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return None
    try:
        _s3_client().put_object(
            Bucket=settings.asset_s3_bucket,
            Key=_s3_object_key(f"{UPLOAD_TMP_PREFIX}/{path}"),
            Body=body,
            ContentType="application/octet-stream",
        )
    except Exception as exc:  # noqa: BLE001 — surface to caller
        return str(exc)
    return None


def _read_upload_chunk(owner: str, upload_id: str, index: int) -> bytes | None:
    path = _chunk_path(owner, upload_id, index)
    settings = get_settings()
    if not settings.asset_s3_bucket:
        try:
            return (_local_upload_root() / path).read_bytes()
        except FileNotFoundError:
            return None
    try:
        response = _s3_client().get_object(
            Bucket=settings.asset_s3_bucket,
            Key=_s3_object_key(f"{UPLOAD_TMP_PREFIX}/{path}"),
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        raise
    return response["Body"].read()


def load_upload(owner: str, ref: UploadRef) -> tuple[str, bytes] | str:
    """Reassemble a chunked upload into (mime, bytes), or return an error message."""
    parts: list[bytes] = []
    total = 0
    for index in range(ref.chunks):
        try:
            chunk = _read_upload_chunk(owner, ref.upload_id, index)
        except ClientError as exc:
            return f"could not read upload chunk {index + 1}/{ref.chunks}: {exc}"
        if chunk is None:
            return f"upload is incomplete: chunk {index + 1}/{ref.chunks} is missing"
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            return f"upload payload too large: exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
        parts.append(chunk)
    raw = b"".join(parts)
    if len(raw) != ref.size:
        return f"upload size mismatch: expected {ref.size} bytes, received {len(raw)}"
    return ref.mime, raw


def delete_upload(owner: str, ref: UploadRef) -> None:
    """Best-effort cleanup; the lifecycle rule expires whatever this misses."""
    settings = get_settings()
    paths = [_chunk_path(owner, ref.upload_id, index) for index in range(ref.chunks)]
    if not settings.asset_s3_bucket:
        shutil.rmtree(_local_upload_root() / paths[0].rsplit("/", 1)[0], ignore_errors=True)
        return
    try:
        _s3_client().delete_objects(
            Bucket=settings.asset_s3_bucket,
            Delete={
                "Objects": [
                    {"Key": _s3_object_key(f"{UPLOAD_TMP_PREFIX}/{path}")} for path in paths
                ],
                "Quiet": True,
            },
        )
    except Exception:  # noqa: BLE001 — cleanup must never fail a successful post
        pass


def normalize_and_persist_filedata(
    *,
    route: LegacyRoute,
    thread_id: str,
    filedata: list[str],
    owner: str | None = None,
) -> tuple[list[str], str | None]:
    """
    Replace Data URLs and chunked-upload references with keys under IMAGE/ or DATA/.
    Existing IMAGE/… or DATA/… lines are kept (for integration fixtures and API keys).
    `owner` (the session subject) scopes chunked uploads: only the user who uploaded
    the chunks can reference them.
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

    used_uploads: list[UploadRef] = []
    for item in filedata:
        if not item:
            continue
        if item.startswith("upload:"):
            if not owner:
                return [], "chunked uploads require a signed-in user"
            ref = parse_upload_ref(item)
            if ref is None:
                return [], "invalid upload reference"
            loaded = load_upload(owner, ref)
            if isinstance(loaded, str):
                return [], loaded
            mime, raw = loaded
            used_uploads.append(ref)
        elif not item.startswith("data:"):
            if err := validate_storage_key(route, item):
                return [], err
            out.append(item)
            continue
        else:
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

    if owner:
        for ref in used_uploads:
            delete_upload(owner, ref)
    return out, None
