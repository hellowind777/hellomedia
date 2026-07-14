#!/usr/bin/env python3
"""
HelloMedia — Vision analysis with multi-channel fallback.
Optional Pillow compression for large images; transient retries per channel.
Zero hard dependencies — stdlib only (Pillow optional).
"""

from __future__ import annotations

import argparse
import json
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
    configure_proxy_opener,
    PERMANENT_4XX,
    RETRY_STATUS_CODES,
    emit_json,
    fail,
    load_channels,
    load_image_payload,
    normalize_base_url,
    normalize_path,
    resolve_media_user_agent,
    safe_output_path,
)


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
        "Accept": "application/json",
        "User-Agent": resolve_media_user_agent(),
    }
    base = normalize_base_url(channel["base_url"])
    label = channel.get("name", "openai")
    # Prefer max_completion_tokens for newer models; keep max_tokens fallback
    # already in payload — some relays only accept one form.
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
        "User-Agent": resolve_media_user_agent(),
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
    try:
        from _common import configure_proxy_opener as _cpo
        _cpo()
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="HelloMedia Vision Analysis")
    parser.add_argument(
        "--image",
        action="append",
        default=None,
        help="Image path (repeatable). Can combine with --from-clipboard",
    )
    parser.add_argument("--image-dir", help="Directory of images")
    parser.add_argument(
        "--from-clipboard",
        action="store_true",
        help="Capture an image from the OS clipboard into skill .runtime and analyze it",
    )
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

    from _clipboard import resolve_image_inputs  # noqa: E402

    resolved = resolve_image_inputs(
        images=args.image,
        image_dir=args.image_dir,
        from_clipboard=args.from_clipboard,
    )
    if not resolved.get("ok"):
        fail(resolved)
    images = resolved["paths"]

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
            result["_images"] = images
            if resolved.get("clipboard"):
                result["_clipboard"] = resolved["clipboard"]
            if args.output == "-":
                emit_json(result, "-")
            else:
                safe, out_path = safe_output_path(args.output)
                if not safe or out_path is None:
                    fail({
                        "error": (
                            f"Unsafe output path rejected: {args.output}. "
                            "Output to stdout or a path within the project directory."
                        )
                    })
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"Saved to {out_path}", file=sys.stderr)
            return
        errors.append(f"{label}: {result.get('error', 'unknown')}")

    fail({"error": "All channels failed", "details": errors})


if __name__ == "__main__":
    main()
