"""Offline tests for clipboard resolve helpers (no real OS clipboard required)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def clipboard_mod(monkeypatch, tmp_path):
    import _common
    import _clipboard

    # Isolate runtime clipboard dir under tmp
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    monkeypatch.setattr(_common, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(_clipboard, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(_clipboard, "SKILL_DIR", tmp_path)
    return importlib.reload(_clipboard)


def test_resolve_image_path(clipboard_mod, tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    out = clipboard_mod.resolve_image_inputs(images=[str(img)])
    assert out["ok"] is True
    assert len(out["paths"]) == 1
    assert Path(out["paths"][0]).is_file()


def test_resolve_missing(clipboard_mod, tmp_path):
    out = clipboard_mod.resolve_image_inputs(images=[str(tmp_path / "nope.png")])
    assert out["ok"] is False
    assert out.get("error_code") == "image_not_found"


def test_resolve_no_inputs(clipboard_mod):
    out = clipboard_mod.resolve_image_inputs()
    assert out["ok"] is False
    assert out.get("error_code") == "no_images"


def test_resolve_image_dir(clipboard_mod, tmp_path):
    d = tmp_path / "imgs"
    d.mkdir()
    (d / "one.jpg").write_bytes(b"fake")
    (d / "two.PNG").write_bytes(b"fake")
    (d / "skip.txt").write_text("x", encoding="utf-8")
    out = clipboard_mod.resolve_image_inputs(image_dir=str(d))
    assert out["ok"] is True
    assert len(out["paths"]) == 2


def test_from_clipboard_uses_capture(clipboard_mod, tmp_path, monkeypatch):
    dest = tmp_path / ".runtime" / "clipboard" / "clip.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"pngdata")

    def fake_capture(**_kwargs):
        return {
            "ok": True,
            "path": str(dest).replace("\\", "/"),
            "source": "image",
            "backend": "test",
            "bytes": dest.stat().st_size,
            "mime": "image/png",
        }

    monkeypatch.setattr(clipboard_mod, "capture_clipboard_image", fake_capture)
    out = clipboard_mod.resolve_image_inputs(from_clipboard=True)
    assert out["ok"] is True
    assert out["paths"][0].endswith("clip.png")
    assert out["clipboard"]["backend"] == "test"


def test_from_clipboard_empty(clipboard_mod, monkeypatch):
    def fake_capture(**_kwargs):
        return {
            "ok": False,
            "error_code": "clipboard_empty",
            "error": "empty",
            "recovery": ["retry"],
        }

    monkeypatch.setattr(clipboard_mod, "capture_clipboard_image", fake_capture)
    out = clipboard_mod.resolve_image_inputs(from_clipboard=True)
    assert out["ok"] is False
    assert out["error_code"] == "clipboard_empty"


def test_probe_backends_shape(clipboard_mod):
    probe = clipboard_mod.probe_clipboard_backends()
    assert "platform" in probe
    assert "backends" in probe
    assert "any_backend" in probe
    assert isinstance(probe["backends"], dict)


def test_recovery_hints(clipboard_mod):
    h = clipboard_mod.recovery_hints("clipboard_empty")
    assert h
    assert any("clipboard" in x.lower() or "Copy" in x or "copy" in x or "image" in x.lower() for x in h)
