import io
import time
import zipfile

import boto3
from algodoo_data.config import get_data_settings
from algodoo_data.repository import init_table, seed_demo_data

from algodoo_web.asset_store import asset_s3_client_kwargs, media_root
from algodoo_web.config import get_settings

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ensure_static_media_samples() -> None:
    """Valid PHZ + thumb for local integration tests."""
    base = media_root() / "DATA"
    base.mkdir(parents=True, exist_ok=True)
    sample_phz = base / "sample.phz"
    if not sample_phz.exists():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("scene.phn", "# sample scene\n")
            zf.writestr("checksums.txt", "sha256 placeholder\n")
            zf.writestr("thumb.png", _MIN_PNG)
        sample_phz.write_bytes(buf.getvalue())
    thumb = base / "sample_thumb.png"
    if not thumb.exists():
        with zipfile.ZipFile(sample_phz, "r") as zf:
            thumb.write_bytes(zf.read("thumb.png"))
    api_phn = base / "api.phn"
    if not api_phn.exists():
        api_phn.write_text("# api phn sample\n", encoding="utf-8")


def _ensure_local_s3_bucket() -> None:
    settings = get_settings()
    if not settings.asset_s3_auto_create:
        return
    if not settings.asset_s3_bucket or not settings.asset_s3_endpoint_url:
        return
    client = boto3.client("s3", **asset_s3_client_kwargs())
    last_error: Exception | None = None
    for _ in range(30):
        try:
            client.create_bucket(
                Bucket=settings.asset_s3_bucket,
                CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
            )
            return
        except client.exceptions.BucketAlreadyOwnedByYou:
            return
        except client.exceptions.BucketAlreadyExists:
            return
        except Exception as exc:  # noqa: BLE001 - local dependency may not be ready yet
            last_error = exc
            time.sleep(1)
    raise RuntimeError("failed to initialize local S3 bucket") from last_error


def bootstrap_data() -> None:
    settings = get_data_settings()
    last_error: Exception | None = None
    for _ in range(30):
        try:
            init_table()
            break
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    else:
        raise RuntimeError("failed to initialize DynamoDB table") from last_error
    _ensure_local_s3_bucket()
    if settings.seed_demo_data:
        seed_demo_data()
        _ensure_static_media_samples()
