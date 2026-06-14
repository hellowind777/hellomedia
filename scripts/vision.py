#!/usr/bin/env python3
"""
HelloMultimodal — Vision analysis with multi-channel fallback.
Supports local image paths, image directories, and Windows clipboard screenshots.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

SKILL_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = SKILL_DIR / ".runtime"
SUPPORTED_GLOBS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff", "*.gif", "*.webp")
MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def load_channels():
    """Load vision-enabled channels from config.json, sorted by priority."""
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        raise RuntimeError(f"config.json not found at {cfg_path}")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    channels = [channel for channel in cfg.get("channels", []) if channel.get("vision")]
    channels.sort(key=lambda channel: channel.get("priority", 99))
    defaults = cfg.get("defaults", {})
    return channels, defaults


def encode_image(path: Path) -> str:
    with path.open("rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def guess_mime(path: Path) -> str:
    return MIME_MAP.get(path.suffix.lower(), "image/png")


def extract_assistant_text(payload: dict) -> str | None:
    """Best-effort extraction of text from common chat completion payloads."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                texts.append(str(item["text"]))
        return "\n".join(texts) if texts else None
    return None


def choose_powershell() -> str:
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("PowerShell not found. --clipboard requires pwsh or powershell on Windows.")


def export_clipboard_image() -> Path:
    """Export the current Windows clipboard image to a temporary PNG file."""
    if os.name != "nt":
        raise RuntimeError("--clipboard is currently supported only on Windows.")

    helper = SKILL_DIR / "scripts" / "export_clipboard_image.ps1"
    if not helper.exists():
        raise RuntimeError(f"Clipboard helper not found at {helper}")

    target_dir = RUNTIME_DIR / "clipboard"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"clipboard-{int(time.time())}-{uuid.uuid4().hex[:8]}.png"

    completed = subprocess.run(
        [
            choose_powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-Output",
            str(target),
        ],
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown clipboard export error").strip()
        raise RuntimeError(detail)
    if not target.exists():
        raise RuntimeError("Clipboard export reported success, but no image file was created.")
    return target


def collect_images(args: argparse.Namespace) -> list[Path]:
    sources = [bool(args.image), bool(args.image_dir), bool(args.clipboard)]
    if sum(sources) != 1:
        raise RuntimeError("Provide exactly one of --image, --image-dir, or --clipboard.")

    if args.image:
        image_path = Path(args.image).expanduser().resolve()
        if not image_path.is_file():
            raise RuntimeError(f"Image file not found: {image_path}")
        return [image_path]

    if args.image_dir:
        image_dir = Path(args.image_dir).expanduser().resolve()
        if not image_dir.is_dir():
            raise RuntimeError(f"Image directory not found: {image_dir}")

        images: list[Path] = []
        for pattern in SUPPORTED_GLOBS:
            images.extend(sorted(image_dir.glob(pattern)))
        if not images:
            raise RuntimeError(f"No supported images found in: {image_dir}")
        return images

    clipboard_image = export_clipboard_image()
    print(f"Exported clipboard image to {clipboard_image}", file=sys.stderr)
    return [clipboard_image]


def is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


def try_channel(channel: dict, images: list[Path], prompt: str, max_tokens: int, timeout: int):
    """Try a single channel. Returns (success, result, retryable)."""
    content = [{"type": "text", "text": prompt}]
    for image_path in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{guess_mime(image_path)};base64,{encode_image(image_path)}",
                    "detail": "high",
                },
            }
        )

    payload = json.dumps(
        {
            "model": channel["model"],
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    request = urlrequest.Request(
        url=f"{channel['base_url'].rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {channel['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            status_code = getattr(response, "status", response.getcode())
            body = response.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        return False, {"error": f"Timeout: {exc}"}, True
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        preview = body.strip().replace("\n", " ")[:500]
        return (
            False,
            {"error": f"HTTP {exc.code}: {preview}"},
            is_retryable_status(exc.code),
        )
    except urlerror.URLError as exc:
        return False, {"error": f"Request error: {exc}"}, True

    if status_code != 200:
        preview = body.strip().replace("\n", " ")[:500]
        return False, {"error": f"HTTP {status_code}: {preview}"}, is_retryable_status(status_code)

    try:
        payload = json.loads(body)
    except ValueError:
        preview = body.strip().replace("\n", " ")[:500]
        return False, {"error": f"HTTP 200 with non-JSON response: {preview}"}, False

    return True, payload, False


def write_result(result: dict, output_path: str):
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if output_path == "-":
        print(content)
        return

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"Saved to {output}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="HelloMultimodal Vision Analysis")
    parser.add_argument("--image", help="Single image path")
    parser.add_argument("--image-dir", help="Directory of images")
    parser.add_argument("--clipboard", action="store_true", help="Read a screenshot from the Windows clipboard")
    parser.add_argument("--prompt", required=True, help="Analysis prompt")
    parser.add_argument("--output", default="-", help="Output file (default: stdout)")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--channel", type=int, default=None, help="Force specific channel by priority")
    args = parser.parse_args()

    try:
        images = collect_images(args)
        channels, defaults = load_channels()
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    max_tokens = args.max_tokens or defaults.get("max_tokens", 4096)
    timeout = defaults.get("timeout_seconds", 300)
    retry_count = defaults.get("retry_count", 2)

    targets = [channel for channel in channels if args.channel is None or channel["priority"] == args.channel]
    if not targets:
        print(json.dumps({"error": "No matching channels"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    errors = []
    for channel in targets:
        label = f"{channel['name']} ({channel['model']})"
        for attempt in range(retry_count + 1):
            if attempt == 0:
                print(f"Trying {label}...", file=sys.stderr)
            else:
                print(f"Retry {attempt}/{retry_count} with {label}...", file=sys.stderr)
                time.sleep(min(2 * attempt, 5))

            ok, result, retryable = try_channel(channel, images, args.prompt, max_tokens, timeout)
            if ok:
                result["_channel"] = channel["name"]
                result["_model"] = channel["model"]
                result["_images"] = [str(image) for image in images]
                assistant_text = extract_assistant_text(result)
                if assistant_text:
                    result["_assistant_text"] = assistant_text
                write_result(result, args.output)
                return

            errors.append(f"{label}: {result.get('error', 'unknown')}")
            if not retryable or attempt >= retry_count:
                break

    print(json.dumps({"error": "All channels failed", "details": errors}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
