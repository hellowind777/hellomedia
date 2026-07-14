#!/usr/bin/env python3
"""
HelloMedia — capture an image from the OS clipboard to a safe temp path.

stdlib-first; optional Pillow / OS tools (PowerShell, pngpaste, xclip, wl-paste).
Does not dump image bytes into return payloads beyond path + metadata.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Allow running as sibling of _common.py
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import RUNTIME_DIR, SKILL_DIR, normalize_path  # noqa: E402

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_MAX_CLIP_BYTES = int(os.environ.get("HELLOMEDIA_CLIPBOARD_MAX_BYTES", str(40 * 1024 * 1024)))


def clipboard_dir() -> Path:
    """Writable directory for clipboard captures (skill .runtime, gitignored)."""
    d = RUNTIME_DIR / "clipboard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp_path(ext: str = ".png") -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return clipboard_dir() / f"clipboard_{ts}{ext}"


def _is_image_path(p: str | Path) -> bool:
    try:
        path = Path(str(p).strip().strip('"').strip("'"))
    except Exception:
        return False
    return path.suffix.lower() in _IMAGE_EXTS and path.is_file()


def _copy_to_runtime(src: Path) -> Path:
    dest = _stamp_path(src.suffix.lower() if src.suffix else ".png")
    shutil.copy2(src, dest)
    return dest


def _ok(path: Path, *, source: str, backend: str, note: str | None = None) -> dict[str, Any]:
    path = Path(path)
    size = path.stat().st_size if path.is_file() else 0
    out: dict[str, Any] = {
        "ok": True,
        "path": str(path).replace("\\", "/"),
        "source": source,
        "backend": backend,
        "bytes": size,
        "mime": {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(path.suffix.lower(), "application/octet-stream"),
    }
    if note:
        out["note"] = note
    return out


def _fail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "error_code": code,
        "error": message,
        "platform": sys.platform,
    }
    out.update(extra)
    return out


def _which(name: str) -> str | None:
    return shutil.which(name)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _is_clipboard_busy_error(msg: str) -> bool:
    m = (msg or "").lower()
    keys = (
        "open clipboard",
        "cannot open",
        "clipboard is empty",
        "access is denied",
        "被拒绝",
        "打开剪贴板",
        "剪贴板",
        "clipboard",
    )
    # Only treat as busy/empty when it looks like open/access, not generic
    busy_keys = ("open clipboard", "cannot open", "access is denied", "打开剪贴板", "failed to open")
    return any(k in m for k in busy_keys)


def _via_pillow() -> dict[str, Any] | None:
    try:
        from PIL import Image, ImageGrab  # type: ignore
    except ImportError:
        return None
    try:
        grabbed = ImageGrab.grabclipboard()
    except Exception as exc:
        # Busy/locked clipboard: try next backend instead of hard-failing
        if _is_clipboard_busy_error(str(exc)):
            return None
        return _fail("clipboard_backend_error", f"Pillow ImageGrab failed: {exc}", backend="pillow")
    if grabbed is None:
        return None
    # File list (Windows often returns list of paths when files are copied)
    if isinstance(grabbed, list):
        for item in grabbed:
            if _is_image_path(item):
                dest = _copy_to_runtime(Path(item))
                return _ok(dest, source="file_list", backend="pillow")
        return _fail(
            "clipboard_text_or_files",
            "Clipboard has files/items but no image file",
            backend="pillow",
        )
    if isinstance(grabbed, Image.Image):
        dest = _stamp_path(".png")
        img = grabbed
        if img.mode not in ("RGB", "RGBA", "L", "P"):
            img = img.convert("RGBA")
        img.save(dest, format="PNG")
        if dest.stat().st_size > _MAX_CLIP_BYTES:
            dest.unlink(missing_ok=True)
            return _fail("clipboard_too_large", f"Clipboard image exceeds {_MAX_CLIP_BYTES} bytes")
        return _ok(dest, source="image", backend="pillow")
    return None


def _via_powershell_windows() -> dict[str, Any] | None:
    if sys.platform != "win32":
        return None
    dest = _stamp_path(".png")
    # Escape for single-quoted PowerShell string
    dest_ps = str(dest).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$out = '{dest_ps}'
try {{
  $img = [System.Windows.Forms.Clipboard]::GetImage()
  if ($null -ne $img) {{
    $img.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
    Write-Output 'IMAGE'
    exit 0
  }}
}} catch {{
  # open/busy clipboard — fall through
}}
try {{
  $files = [System.Windows.Forms.Clipboard]::GetFileDropList()
  if ($files -and $files.Count -gt 0) {{
    foreach ($f in $files) {{
      if (Test-Path -LiteralPath $f) {{
        $ext = [System.IO.Path]::GetExtension($f).ToLowerInvariant()
        if ($ext -in @('.png','.jpg','.jpeg','.webp','.gif','.bmp','.tif','.tiff')) {{
          Write-Output ("FILE:" + $f)
          exit 0
        }}
      }}
    }}
    Write-Output 'NO_IMAGE_FILE'
    exit 2
  }}
}} catch {{ }}
try {{
  $t = [System.Windows.Forms.Clipboard]::GetText()
  if ($t) {{
    $t = $t.Trim().Trim('"')
    if (Test-Path -LiteralPath $t) {{
      $ext = [System.IO.Path]::GetExtension($t).ToLowerInvariant()
      if ($ext -in @('.png','.jpg','.jpeg','.webp','.gif','.bmp','.tif','.tiff')) {{
        Write-Output ("FILE:" + $t)
        exit 0
      }}
    }}
    Write-Output 'TEXT_ONLY'
    exit 3
  }}
}} catch {{ }}
Write-Output 'EMPTY'
exit 4
"""
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return _fail("clipboard_timeout", "PowerShell clipboard read timed out", backend="powershell")
    except Exception as exc:
        return _fail("clipboard_backend_error", f"PowerShell failed: {exc}", backend="powershell")

    line = (proc.stdout or "").strip().splitlines()
    token = line[-1].strip() if line else ""
    if proc.returncode == 0 and token == "IMAGE" and dest.is_file() and dest.stat().st_size > 0:
        if dest.stat().st_size > _MAX_CLIP_BYTES:
            dest.unlink(missing_ok=True)
            return _fail("clipboard_too_large", f"Clipboard image exceeds {_MAX_CLIP_BYTES} bytes")
        return _ok(dest, source="image", backend="powershell")
    if token.startswith("FILE:"):
        src = Path(token[5:].strip())
        if _is_image_path(src):
            dest.unlink(missing_ok=True)
            return _ok(_copy_to_runtime(src), source="file_list", backend="powershell")
    dest.unlink(missing_ok=True)
    if token == "TEXT_ONLY" or proc.returncode == 3:
        return _fail(
            "clipboard_text_only",
            "Clipboard has text, not an image. Re-copy the image (not a path string), or pass --image <path>.",
            backend="powershell",
        )
    if token == "NO_IMAGE_FILE" or proc.returncode == 2:
        return _fail(
            "clipboard_text_or_files",
            "Clipboard has files but none are images",
            backend="powershell",
        )
    if token == "EMPTY" or proc.returncode == 4:
        return None  # try next backend / empty
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:200]
        combined = f"{err} {token}"
        if _is_clipboard_busy_error(combined):
            return None
        return _fail(
            "clipboard_backend_error",
            f"PowerShell clipboard error (code {proc.returncode}): {err or token}",
            backend="powershell",
        )
    return None


def _via_pngpaste_macos() -> dict[str, Any] | None:
    if sys.platform != "darwin":
        return None
    if not _which("pngpaste"):
        return None
    dest = _stamp_path(".png")
    try:
        proc = subprocess.run(
            ["pngpaste", str(dest)],
            capture_output=True,
            timeout=15,
        )
    except Exception as exc:
        return _fail("clipboard_backend_error", f"pngpaste failed: {exc}", backend="pngpaste")
    if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
        if dest.stat().st_size > _MAX_CLIP_BYTES:
            dest.unlink(missing_ok=True)
            return _fail("clipboard_too_large", f"Clipboard image exceeds {_MAX_CLIP_BYTES} bytes")
        return _ok(dest, source="image", backend="pngpaste")
    dest.unlink(missing_ok=True)
    return None


def _via_osascript_macos() -> dict[str, Any] | None:
    if sys.platform != "darwin":
        return None
    # Write clipboard picture via AppleScript → PNG via sips if needed
    dest = _stamp_path(".png")
    dest_q = str(dest).replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
try
  set pngData to the clipboard as «class PNGf»
on error
  try
    set pngData to the clipboard as «class TIFF»
  on error
    return "EMPTY"
  end try
end try
set outPath to "{dest_q}"
set f to open for access POSIX file outPath with write permission
set eof f to 0
write pngData to f
close access f
return "OK"
'''
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        return _fail("clipboard_backend_error", f"osascript failed: {exc}", backend="osascript")
    token = (proc.stdout or "").strip()
    if token == "OK" and dest.is_file() and dest.stat().st_size > 0:
        # May be TIFF bytes saved as .png; try convert with sips if available
        if _which("sips"):
            try:
                subprocess.run(
                    ["sips", "-s", "format", "png", str(dest), "--out", str(dest)],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            except Exception:
                pass
        if dest.stat().st_size > _MAX_CLIP_BYTES:
            dest.unlink(missing_ok=True)
            return _fail("clipboard_too_large", f"Clipboard image exceeds {_MAX_CLIP_BYTES} bytes")
        return _ok(dest, source="image", backend="osascript")
    dest.unlink(missing_ok=True)
    return None


def _via_wl_paste() -> dict[str, Any] | None:
    if not _which("wl-paste"):
        return None
    mime_to_ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    for mime, ext in mime_to_ext.items():
        try:
            proc = subprocess.run(
                ["wl-paste", "-t", mime],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            continue
        if proc.returncode == 0 and proc.stdout:
            if len(proc.stdout) > _MAX_CLIP_BYTES:
                return _fail("clipboard_too_large", f"Clipboard image exceeds {_MAX_CLIP_BYTES} bytes")
            dest = _stamp_path(ext)
            dest.write_bytes(proc.stdout)
            return _ok(dest, source="image", backend="wl-paste")
    return None


def _via_xclip() -> dict[str, Any] | None:
    if not _which("xclip"):
        return None
    dest = _stamp_path(".png")
    for mime in ("image/png", "image/jpeg", "image/bmp"):
        try:
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", mime, "-o"],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            continue
        if proc.returncode == 0 and proc.stdout:
            if len(proc.stdout) > _MAX_CLIP_BYTES:
                return _fail("clipboard_too_large", f"Clipboard image exceeds {_MAX_CLIP_BYTES} bytes")
            ext = ".png" if "png" in mime else (".jpg" if "jpeg" in mime else ".bmp")
            dest = _stamp_path(ext)
            dest.write_bytes(proc.stdout)
            return _ok(dest, source="image", backend="xclip")
    return None


def _via_xsel() -> dict[str, Any] | None:
    # xsel rarely does images well; skip for images
    return None


def probe_clipboard_backends() -> dict[str, Any]:
    """Non-destructive capability report for doctor."""
    backends = {
        "pillow": False,
        "powershell": sys.platform == "win32" and bool(_which("powershell") or _which("pwsh")),
        "pngpaste": sys.platform == "darwin" and bool(_which("pngpaste")),
        "osascript": sys.platform == "darwin" and bool(_which("osascript")),
        "wl-paste": bool(_which("wl-paste")),
        "xclip": bool(_which("xclip")),
    }
    try:
        from PIL import ImageGrab  # noqa: F401

        backends["pillow"] = True
    except ImportError:
        pass
    return {
        "platform": sys.platform,
        "backends": backends,
        "any_backend": any(backends.values()),
        "clipboard_dir": str(clipboard_dir()).replace("\\", "/"),
        "hints": _platform_hints(),
    }


def _in_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        ver = Path("/proc/version")
        if ver.is_file() and "microsoft" in ver.read_text(encoding="utf-8", errors="ignore").lower():
            return True
    except OSError:
        pass
    return False


def _platform_hints() -> list[str]:
    hints = []
    if sys.platform == "win32":
        hints.append(
            "Windows Terminal may swallow image paste into the CLI (use Alt+V for Claude/Grok). "
            "For hellomedia, re-copy the image then run vision.py --from-clipboard."
        )
        hints.append("Pillow (pip install Pillow) improves grabclipboard reliability.")
    elif sys.platform == "darwin":
        hints.append("Optional: brew install pngpaste for reliable macOS clipboard images.")
    else:
        hints.append("Install wl-clipboard (Wayland) or xclip (X11) for clipboard images.")
        if _in_wsl():
            hints.append(
                "WSL: Linux clipboard is not the Windows clipboard. "
                "Save the image under /mnt/c/... and pass --image, or paste in a Windows-native host CLI."
            )
    return hints


def capture_clipboard_image(*, prefer_copy: bool = True) -> dict[str, Any]:
    """Capture current clipboard image (or image file list entry) to skill .runtime/clipboard.

    Returns:
      ok True: path, source, backend, bytes, mime
      ok False: error_code, error, platform, optional recovery hints
    """
    _ = prefer_copy
    order: list[Any]
    if sys.platform == "win32":
        order = [_via_pillow, _via_powershell_windows]
    elif sys.platform == "darwin":
        order = [_via_pillow, _via_pngpaste_macos, _via_osascript_macos]
    else:
        order = [_via_pillow, _via_wl_paste, _via_xclip]

    last_structured: dict[str, Any] | None = None
    for fn in order:
        try:
            result = fn()
        except Exception as exc:
            if _is_clipboard_busy_error(str(exc)):
                continue
            last_structured = _fail(
                "clipboard_backend_error",
                f"{fn.__name__}: {exc}",
                backend=getattr(fn, "__name__", "unknown"),
            )
            continue
        if result is None:
            continue
        if result.get("ok"):
            return result
        # Structured failure that is definitive (text-only, etc.)
        code = result.get("error_code")
        if code in (
            "clipboard_text_only",
            "clipboard_text_or_files",
            "clipboard_too_large",
            "clipboard_timeout",
        ):
            result.setdefault("recovery", recovery_hints(code))
            return result
        last_structured = result

    probe = probe_clipboard_backends()
    if not probe.get("any_backend"):
        return _fail(
            "clipboard_no_backend",
            "No clipboard image backend available. Install Pillow and/or platform tools "
            "(Windows: PowerShell; macOS: pngpaste; Linux: wl-paste/xclip).",
            backends=probe.get("backends"),
            recovery=recovery_hints("clipboard_no_backend"),
            hints=probe.get("hints"),
        )
    # Prefer empty/busy over opaque backend errors when nothing was captured
    if last_structured and last_structured.get("error_code") == "clipboard_backend_error":
        last_structured = None
    out = last_structured or _fail(
        "clipboard_empty",
        "No image found on the clipboard (or clipboard was busy/locked). "
        "Re-copy the image (screenshot / Copy Image), then retry --from-clipboard; "
        "or save the file and use --image <path>.",
        backends=probe.get("backends"),
    )
    out.setdefault("recovery", recovery_hints(out.get("error_code", "clipboard_empty")))
    out.setdefault("hints", probe.get("hints"))
    return out


def recovery_hints(code: str) -> list[str]:
    common = [
        "Re-copy the image itself (not only a file path string).",
        "Or save the paste to a file and run: python scripts/vision.py --image <path> --prompt '...'",
    ]
    if code == "clipboard_empty":
        return [
            "Clipboard is empty, busy, or was already consumed by the host UI.",
            "Copy the image again, then immediately run --from-clipboard.",
            "Close apps that lock the clipboard, then retry.",
            *common[1:],
        ]
    if code == "clipboard_text_only":
        return common
    if code == "clipboard_no_backend":
        return [
            "pip install Pillow",
            "Windows: ensure powershell is on PATH",
            "macOS: brew install pngpaste",
            "Linux: install wl-clipboard or xclip",
            *common[1:],
        ]
    return common


def resolve_image_inputs(
    *,
    images: list[str] | None = None,
    image_dir: str | None = None,
    from_clipboard: bool = False,
) -> dict[str, Any]:
    """Resolve --image / --image-dir / --from-clipboard into absolute image paths."""
    resolved: list[str] = []
    missing: list[str] = []
    clipboard_meta: dict[str, Any] | None = None

    for raw in images or []:
        p = normalize_path(raw)
        if p and Path(p).is_file():
            resolved.append(p)
        else:
            missing.append(raw)

    if image_dir:
        dir_path = Path(normalize_path(image_dir) or image_dir)
        if not dir_path.is_dir():
            return {
                "ok": False,
                "error_code": "image_dir_not_found",
                "error": f"Image directory not found: {image_dir}",
            }
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff", "*.tif", "*.webp", "*.gif"):
            resolved.extend(str(p).replace("\\", "/") for p in sorted(dir_path.glob(ext)))

    if from_clipboard:
        clipboard_meta = capture_clipboard_image()
        if not clipboard_meta.get("ok"):
            # If we already have other images, soft-fail clipboard only when mixed?
            # Prefer hard fail when --from-clipboard was explicit and no other images.
            if not resolved:
                return clipboard_meta
        else:
            resolved.append(clipboard_meta["path"])

    if missing and not resolved:
        return {
            "ok": False,
            "error_code": "image_not_found",
            "error": f"Image file(s) not found: {missing}",
            "missing": missing,
        }
    if not resolved:
        return {
            "ok": False,
            "error_code": "no_images",
            "error": "No images provided. Use --image, --image-dir, and/or --from-clipboard.",
            "recovery": recovery_hints("clipboard_empty"),
        }

    out: dict[str, Any] = {
        "ok": True,
        "paths": resolved,
        "missing": missing,
    }
    if clipboard_meta and clipboard_meta.get("ok"):
        out["clipboard"] = {
            "path": clipboard_meta.get("path"),
            "backend": clipboard_meta.get("backend"),
            "source": clipboard_meta.get("source"),
            "bytes": clipboard_meta.get("bytes"),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="HelloMedia clipboard image capture")
    parser.add_argument("--probe", action="store_true", help="List available backends only")
    parser.add_argument("--capture", action="store_true", help="Capture clipboard image to .runtime")
    args = parser.parse_args(argv)
    if args.probe or not args.capture:
        print(json.dumps(probe_clipboard_backends(), ensure_ascii=False, indent=2))
        return 0 if probe_clipboard_backends().get("any_backend") else 2
    result = capture_clipboard_image()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
