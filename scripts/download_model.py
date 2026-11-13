#!/usr/bin/env python3
"""Download an official MediaPipe Pose Landmarker model asset into ./models.

Model assets are published by Google at storage.googleapis.com/mediapipe-models
and documented at:
https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker#models

Variants (all float16, 33 landmarks):
  lite  - fastest, least accurate. Recommended starting point on Raspberry Pi.
  full  - balanced. Default for Apple Silicon development.
  heavy - most accurate, slowest.

Uses only the standard library so it can run before the venv exists.

Usage:
  backend/.venv/bin/python scripts/download_model.py          # downloads "full"
  backend/.venv/bin/python scripts/download_model.py lite heavy
"""

from __future__ import annotations

import hashlib
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path

# Pinned to model version "1" rather than "latest" so results are reproducible.
_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_{variant}/float16/1/pose_landmarker_{variant}.task"
)
VARIANTS = ("lite", "full", "heavy")
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS context.

    The python.org macOS installer ships without CA certificates until
    "Install Certificates.command" is run, so prefer certifi's bundle when it is
    importable (it is a mediapipe dependency, so it exists inside the venv).
    Verification is never disabled.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def download(variant: str) -> Path:
    if variant not in VARIANTS:
        raise SystemExit(f"Unknown variant {variant!r}; choose from {VARIANTS}")
    MODELS_DIR.mkdir(exist_ok=True)
    dest = MODELS_DIR / f"pose_landmarker_{variant}.task"
    if dest.exists():
        print(f"[skip] {dest} already exists")
        return dest

    url = _URL.format(variant=variant)
    print(f"[get ] {url}")
    # Write to a temp file first so an interrupted download never leaves a
    # truncated model in place.
    with urllib.request.urlopen(
        url, timeout=60, context=_ssl_context()
    ) as resp, tempfile.NamedTemporaryFile(
        dir=MODELS_DIR, delete=False, suffix=".part"
    ) as tmp:
        sha = hashlib.sha256()
        while chunk := resp.read(1 << 16):
            sha.update(chunk)
            tmp.write(chunk)
    Path(tmp.name).chmod(0o644)  # NamedTemporaryFile creates files as 0600
    Path(tmp.name).rename(dest)
    print(f"[done] {dest} ({dest.stat().st_size / 1e6:.1f} MB, sha256={sha.hexdigest()})")
    return dest


def main(argv: list[str]) -> None:
    for variant in argv or ["full"]:
        download(variant)


if __name__ == "__main__":
    main(sys.argv[1:])
