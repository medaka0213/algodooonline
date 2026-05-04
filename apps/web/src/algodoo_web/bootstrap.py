import io
import time
import zipfile
from pathlib import Path

from algodoo_data.config import get_data_settings
from algodoo_data.repository import init_table, seed_demo_data

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _ensure_static_media_samples() -> None:
    """Valid PHZ + thumb for local smoke (DATA/sample.phz, DATA/sample_thumb.png)."""
    base = Path(__file__).resolve().parent / "media" / "DATA"
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
    if settings.seed_demo_data:
        seed_demo_data()
    _ensure_static_media_samples()
