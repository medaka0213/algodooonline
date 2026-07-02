"""Sample attachment files for the IMAGE/DATA board upload flows (SPEC.md §13).

Bytes are generated on the fly so no binary fixtures are committed to git.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

# A minimal, real, browser-decodable 1x1 PNG (valid IHDR/IDAT/IEND + CRCs).
MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_png(tmp_path: Path, name: str = "upload.png") -> Path:
    path = tmp_path / name
    path.write_bytes(MIN_PNG)
    return path


def make_phz(tmp_path: Path, name: str = "scene.phz") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scene.phn", "# e2e scene\n")
        zf.writestr("checksums.txt", "sha256 placeholder\n")
        zf.writestr("thumb.png", MIN_PNG)
    return path


def make_phn(tmp_path: Path, name: str = "scene.phn") -> Path:
    path = tmp_path / name
    path.write_text("# e2e phn scene\n", encoding="utf-8")
    return path
