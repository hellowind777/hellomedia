#!/usr/bin/env python3
"""
HelloMedia — Vision analysis with multi-channel fallback.
Optional Pillow compression for large images; transient retries per channel.
Zero hard dependencies — stdlib only (Pillow optional).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Ensure UTF-8 on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    PERMANENT_4XX,
    RETRY_STATUS_CODES,
    SKILL_DIR,
    USER_AGENT,
    emit_json,
    fail,
    load_channels,
    normalize_base_url,
    normalize_path,
    safe_output_path,
)

_COMPRESS_MIN_BYTES = int(os.environ.get("HELLOMEDIA_COMPRESS_MIN_BYTES", str(50 * 1024)))
_COMPRESS_MAX_SIDE = int(os.environ.get("HELLOMEDIA_COMPRESS_MAX_SIDE", "1536"))
_COMPRESS_JPEG_QUALITY = int(os.environ.get("HELLOMEDIA_COMPRESS_JPEG_QUALITY", "75"))


def _mime_for_ext(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "bmp": "image/bmp", "tiff": "image/tiff",
        "webp": "image/webp", "gif": "image/gif",
    }.get(ext, "image/png")


def load_image_payload(path: str, *, compress: bool = True) -> tuple[str, str]:
    """Return (base64_str, mime). Compress large images when Pillow is available."""
    with open(path, "rb") as f:
        raw = f.read()
    mime = _mime_for_ext(path)
    if not compress or len(raw) <= _COMPRESS_MIN_BYTES:
        return base64.b64encode(raw).decode(), mime
    try:
        from io import BytesIO
        from PIL import Image  # optional
    except ImportError:
        return base64.b64encode(raw).decode(), mime

    try:
        im = Image.open(path)
        if getattr(im, "is_animated", False):
            im.seek(0)
        im = im.convert("RGB")
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        im.thumbnail((_COMPRESS_MAX_SIDE, _COMPRESS_MAX_SIDE), resample)
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=_COMPRESS_JPEG_QUALITY, optimize=True)
        compressed = buf.getvalue()
        if len(compressed) < len(raw):
            print(
                f"[vision] compressed {os.path.basename(path)}: "
                f"{len(raw)} -> {len(compressed)} bytes",
                file=sys.stderr,
            )
            return base64.b64encode(compressed).decode(), "image/jpeg"
    except Exception as exc:
        print(f"[vision] compress skipped for {path}: {exc}", file=sys.stderr)
    return base64.b64encode(raw).decode(), mime


def encode_image(path: str) -> str:
    """Encode image without compression."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _request_with_retries(url, body, headers, timeout, retries, label):
    last_err = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:300]
            last_err = {"error": f"HTTP {e.code}: {err_body}"}
            if e.code in PERMANENT_4XX:
                return False, last_err
            if e.code not in RETRY_STATUS_CODES or attempt >= retries + 1:
                return False, last_err
            delay = 2 ** (attempt - 1)
            if e.code == 429 and hasattr(e, "headers") and e.headers:
                ra = e.headers.get("Retry-After")
                if ra:
                    try:
                        delay = max(delay, int(ra))
                    except ValueError:
                        pass
            print(
                f"[vision] {label}: HTTP {e.code}, retry in {delay}s "
                f"({attempt}/{retries + 1})",
                file=sys.stderr,
            )
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            last_err = {"error": str(e)}
            if attempt >= retries + 1:
                return False, last_err
            delay = 2 ** (attempt - 1)
            print(
                f"[vision] {label}: network error, retry in {delay}s "
                f"({attempt}/{retries + 1})",
                file=sys.stderr,
            )
            time.sleep(delay)
    return False, last_err or {"error": "unknown"}


def _try_openai(channel, images, prompt, max_tokens, timeout, *, compress=True, retries=2):
    content = [{"type": "text", "text": prompt}]
    for img_path in images:
        b64, mime = load_image_payload(img_path, compress=compress)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
        })

    payload = {
        "model": channel["model"],
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {channel['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    base = normalize_base_url(channel["base_url"])
    label = channel.get("name", "openai")
    return _request_with_retries(
        f"{base}/v1/chat/completions", body, headers, timeout, retries, label
    )


def _try_anthropic(channel, images, prompt, max_tokens, timeout, *, compress=True, retries=2):
    content = []
    for img_path in images:
        b64, mime = load_image_payload(img_path, compress=compress)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": channel["model"],
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "x-api-key": channel["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    base = normalize_base_url(channel["base_url"])
    label = channel.get("name", "anthropic")
    ok, data = _request_with_retries(
        f"{base}/v1/messages", body, headers, timeout, retries, label
    )
    if not ok:
        return False, data
    text = ""
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    return True, {"choices": [{"message": {"content": text}}], "_anthropic_raw": data}


def try_channel(channel, images, prompt, max_tokens, timeout, *, compress=True, retries=2):
    fmt = channel.get("api_format", "openai")
    if fmt == "anthropic":
        return _try_anthropic(
            channel, images, prompt, max_tokens, timeout, compress=compress, retries=retries
        )
    return _try_openai(
        channel, images, prompt, max_tokens, timeout, compress=compress, retries=retries
    )


def main():
    parser = argparse.ArgumentParser(description="HelloMedia Vision Analysis")
    parser.add_argument("--image", help="Single image path")
    parser.add_argument("--image-dir", help="Directory of images")
    parser.add_argument("--prompt", required=True, help="Analysis prompt")
    parser.add_argument("--output", default="-", help="Output file (default: stdout)")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--channel", type=int, default=None, help="Force channel by priority")
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable optional image compression even if Pillow is installed",
    )
    args = parser.parse_args()

    try:
        channels, defaults = load_channels("vision")
    except FileNotFoundError as e:
        fail({"error": str(e)})

    max_tokens = args.max_tokens or defaults.get("max_tokens", 4096)
    timeout = defaults.get("timeout_seconds", 300)
    retries = int(defaults.get("retry_count", 2))
    compress = not args.no_compress

    images = []
    missing = []
    if args.image:
        p = normalize_path(args.image)
        if p and Path(p).exists():
            images.append(p)
        else:
            missing.append(p or args.image)
    if args.image_dir:
        dir_path = Path(normalize_path(args.image_dir) or args.image_dir)
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff", "*.webp", "*.gif"):
            images.extend(str(p).replace("\\", "/") for p in dir_path.glob(ext))
        images.sort()
    if missing:
        fail({"error": f"Image file(s) not found: {missing}"})
    if not images:
        fail({"error": "No images provided"})

    targets = [c for c in channels if args.channel is None or c.get("priority") == args.channel]
    if not targets:
        fail({"error": "No matching channels"})

    errors = []
    for channel in targets:
        label = f"{channel.get('name')} ({channel.get('model')})"
        print(f"Trying {label}...", file=sys.stderr)
        ok, result = try_channel(
            channel, images, args.prompt, max_tokens, timeout,
            compress=compress, retries=retries,
        )
        if ok:
            result["_channel"] = channel.get("name")
            result["_model"] = channel.get("model")
            if args.output == "-":
                emit_json(result, "-")
            else:
                safe, resolved = safe_output_path(args.output)
                if not safe or resolved is None:
                    fail({
                        "error": (
                            f"Unsafe output path rejected: {args.output}. "
                            "Output to stdout or a path within the project directory."
                        )
                    })
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"Saved to {resolved}", file=sys.stderr)
            return
        errors.append(f"{label}: {result.get('error', 'unknown')}")

    fail({"error": "All channels failed", "details": errors})


if __name__ == "__main__":
    main()
