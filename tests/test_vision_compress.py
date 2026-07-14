"""Offline tests for clarity-preserving vision compression."""

from __future__ import annotations

import base64
import importlib
import io
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _reload_common(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    import _common

    return importlib.reload(_common)


def _make_png(path: Path, size: tuple[int, int], color=(30, 120, 200)) -> None:
    from PIL import Image

    Image.new("RGB", size, color).save(path, format="PNG")


@pytest.fixture(scope="module")
def pillow_available():
    try:
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        return False


def test_small_file_not_compressed(tmp_path, monkeypatch, pillow_available):
    if not pillow_available:
        pytest.skip("Pillow not installed")
    common = _reload_common(
        monkeypatch,
        HELLOMEDIA_COMPRESS_MIN_BYTES=256 * 1024,
        HELLOMEDIA_COMPRESS_MAX_SIDE=2048,
        HELLOMEDIA_COMPRESS_JPEG_QUALITY=90,
        HELLOMEDIA_COMPRESS_REENCODE_MIN_BYTES=2 * 1024 * 1024,
    )
    p = tmp_path / "tiny.png"
    _make_png(p, (64, 64))
    assert p.stat().st_size < 256 * 1024
    raw = p.read_bytes()
    b64, mime = common.load_image_payload(str(p), compress=True)
    assert mime == "image/png"
    assert base64.b64decode(b64) == raw


def test_large_side_resized(tmp_path, monkeypatch, pillow_available):
    if not pillow_available:
        pytest.skip("Pillow not installed")
    common = _reload_common(
        monkeypatch,
        HELLOMEDIA_COMPRESS_MIN_BYTES=1024,  # force eligibility by size
        HELLOMEDIA_COMPRESS_MAX_SIDE=512,
        HELLOMEDIA_COMPRESS_JPEG_QUALITY=90,
        HELLOMEDIA_COMPRESS_REENCODE_MIN_BYTES=10 * 1024 * 1024,
    )
    p = tmp_path / "wide.png"
    _make_png(p, (1200, 400))
    # ensure over min bytes after solid PNG (may still be small — pad if needed)
    if p.stat().st_size <= 1024:
        p.write_bytes(p.read_bytes() + b"\x00" * 2048)
        # re-save a real image so PIL can open
        _make_png(p, (1200, 400))
        # min bytes low enough for any PNG of 1200x400
        common = _reload_common(
            monkeypatch,
            HELLOMEDIA_COMPRESS_MIN_BYTES=100,
            HELLOMEDIA_COMPRESS_MAX_SIDE=512,
            HELLOMEDIA_COMPRESS_JPEG_QUALITY=90,
            HELLOMEDIA_COMPRESS_REENCODE_MIN_BYTES=50 * 1024 * 1024,
        )
    b64, mime = common.load_image_payload(str(p), compress=True)
    assert mime == "image/jpeg"
    from PIL import Image

    im = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert max(im.size) <= 512


def test_no_compress_flag_keeps_original(tmp_path, monkeypatch, pillow_available):
    if not pillow_available:
        pytest.skip("Pillow not installed")
    common = _reload_common(
        monkeypatch,
        HELLOMEDIA_COMPRESS_MIN_BYTES=100,
        HELLOMEDIA_COMPRESS_MAX_SIDE=64,
        HELLOMEDIA_COMPRESS_JPEG_QUALITY=50,
    )
    p = tmp_path / "orig.png"
    _make_png(p, (200, 200))
    raw = p.read_bytes()
    b64, mime = common.load_image_payload(str(p), compress=False)
    assert mime == "image/png"
    assert base64.b64decode(b64) == raw


def test_defaults_are_clarity_first(monkeypatch):
    common = _reload_common(
        monkeypatch,
        HELLOMEDIA_COMPRESS_MIN_BYTES=None,
        HELLOMEDIA_COMPRESS_MAX_SIDE=None,
        HELLOMEDIA_COMPRESS_JPEG_QUALITY=None,
        HELLOMEDIA_COMPRESS_REENCODE_MIN_BYTES=None,
    )
    assert common._COMPRESS_MIN_BYTES == 256 * 1024
    assert common._COMPRESS_MAX_SIDE == 2048
    assert common._COMPRESS_JPEG_QUALITY == 90
    assert common._COMPRESS_REENCODE_MIN_BYTES == 2 * 1024 * 1024


def test_rgba_composites_on_white(tmp_path, monkeypatch, pillow_available):
    if not pillow_available:
        pytest.skip("Pillow not installed")
    from PIL import Image
    import random

    common = _reload_common(
        monkeypatch,
        HELLOMEDIA_COMPRESS_MIN_BYTES=100,
        HELLOMEDIA_COMPRESS_MAX_SIDE=128,
        HELLOMEDIA_COMPRESS_JPEG_QUALITY=90,
        HELLOMEDIA_COMPRESS_REENCODE_MIN_BYTES=50 * 1024 * 1024,
    )
    p = tmp_path / "alpha.png"
    # Noisy large RGBA so JPEG shrinks below PNG (compression only applies when smaller)
    rng = random.Random(0)
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    px = im.load()
    for x in range(400):
        for y in range(400):
            if 100 <= x < 300 and 100 <= y < 300:
                px[x, y] = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), 255)
            else:
                px[x, y] = (0, 0, 0, 0)
    im.save(p, format="PNG")
    b64, mime = common.load_image_payload(str(p), compress=True)
    assert mime == "image/jpeg", "expected re-encode to win on large noisy PNG"
    out = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    # corner was transparent → should be near white after composite
    corner = out.getpixel((0, 0))
    assert min(corner) >= 240, corner
