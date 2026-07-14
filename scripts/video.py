#!/usr/bin/env python3
"""
HelloMedia — Video generation via xAI Grok Imagine REST API.

This is the HelloMedia skill wrapper around the *same* official
Imagine surface that Grok Build exposes as host tools:

  Grok Build host tool          REST equivalent (this script)
  -------------------------     ----------------------------------------------
  image_to_video                POST /v1/videos/generations + image
  reference_to_video            POST /v1/videos/generations + reference_images
  (no pure-T2V host tool)       POST /v1/videos/generations prompt-only
  (edit / extend)               POST /v1/videos/edits | /extensions

Host tools cannot be vendored as source; their API *is* this REST contract.
Any OpenAI/xAI-compatible relay that forwards Imagine works if the *group*
has image/video generation enabled (403 permission_error = billing/group flag).

Async: POST start → poll GET /v1/videos/{request_id} → download mp4.
Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    USER_AGENT,
    channel_creds,
    download_url,
    emit_json,
    eprint,
    fail,
    file_to_data_url,
    http_json,
    load_channels,
    normalize_base_url,
    normalize_path,
    safe_output_path,
)

# Data URL size guard for local media (~20MB)
_MAX_INLINE_BYTES = 20 * 1024 * 1024


def _media_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    p = normalize_path(path_or_url)
    if not p or not Path(p).exists():
        raise FileNotFoundError(f"Media not found: {path_or_url}")
    return file_to_data_url(p, max_bytes=_MAX_INLINE_BYTES)


def _start_endpoint(mode: str, base: str) -> str:
    if mode == "edit":
        return f"{base}/v1/videos/edits"
    if mode == "extend":
        return f"{base}/v1/videos/extensions"
    return f"{base}/v1/videos/generations"


def resolve_tool_mode(args) -> str:
    """Map CLI flags / --mode to a Grok-Build-aligned tool mode name."""
    explicit = (args.mode or "auto").replace("-", "_").lower()
    if explicit == "auto":
        if args.extend:
            return "extend"
        if args.video:
            return "edit"
        if args.image and args.reference:
            raise ValueError(
                "Cannot combine --image (image_to_video start frame) with "
                "--reference (reference_to_video). Use one mode."
            )
        if args.image:
            return "image_to_video"
        if args.reference:
            return "reference_to_video"
        return "text_to_video"
    aliases = {
        "i2v": "image_to_video",
        "image": "image_to_video",
        "r2v": "reference_to_video",
        "reference": "reference_to_video",
        "t2v": "text_to_video",
        "text": "text_to_video",
        "generate": "text_to_video",
        "edit_video": "edit",
        "extend_video": "extend",
    }
    return aliases.get(explicit, explicit)


def build_payload(args, model: str) -> tuple[str, dict]:
    """Return (tool_mode, payload) for Imagine REST."""
    prompt = (args.prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    tool_mode = resolve_tool_mode(args)

    if tool_mode == "extend":
        if not args.video:
            raise ValueError("extend mode requires --video")
        return "extend", {
            "model": model,
            "prompt": prompt,
            "video": {"url": _media_url(args.video)},
        }

    if tool_mode == "edit":
        if not args.video:
            raise ValueError("edit mode requires --video")
        return "edit", {
            "model": model,
            "prompt": prompt,
            "video": {"url": _media_url(args.video)},
        }

    # generation family → /v1/videos/generations
    duration = int(args.duration)
    # Grok Build host tools only expose 6/10; REST allows 1-15 — clamp only if flag set
    if args.build_compat and duration not in (6, 10):
        duration = 6 if duration < 8 else 10

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
    }

    if tool_mode == "image_to_video":
        if not args.image:
            raise ValueError("image_to_video requires --image (start frame)")
        if args.reference:
            raise ValueError("image_to_video cannot include --reference")
        payload["image"] = {"url": _media_url(args.image)}
        return "image_to_video", payload

    if tool_mode == "reference_to_video":
        refs_in = args.reference or []
        if len(refs_in) < 1:
            raise ValueError("reference_to_video requires at least 1 --reference image")
        if len(refs_in) > 7:
            raise ValueError("reference_to_video supports at most 7 reference images")
        # Official docs / Build tool: typically 2-7; allow 1 for flexibility
        payload["reference_images"] = [{"url": _media_url(r)} for r in refs_in]
        # reference-to-video is not supported on grok-imagine-video-1.5
        if "1.5" in (model or ""):
            raise ValueError(
                "reference_to_video requires model grok-imagine-video "
                "(not grok-imagine-video-1.5)"
            )
        return "reference_to_video", payload

    if tool_mode == "text_to_video":
        if args.image or args.reference:
            raise ValueError("text_to_video must not include --image/--reference")
        return "text_to_video", payload

    raise ValueError(
        f"Unknown mode: {tool_mode}. "
        "Use auto|image_to_video|reference_to_video|text_to_video|edit|extend"
    )


def poll_video(base: str, api_key: str, request_id: str, *, timeout: float, interval: float) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }
    deadline = time.time() + timeout
    url = f"{base}/v1/videos/{request_id}"
    last = {}
    while time.time() < deadline:
        ok, data = http_json("GET", url, headers=headers, payload=None, timeout=60, retries=1, label="video-poll")
        if not ok:
            last = data
            eprint(f"[video] poll error: {data.get('error')}")
            time.sleep(interval)
            continue
        last = data
        status = (data.get("status") or "").lower()
        eprint(f"[video] status={status}")
        if status == "done":
            return data
        if status in ("failed", "expired"):
            return data
        time.sleep(interval)
    return {"status": "timeout", "error": f"Timed out after {timeout}s", "last": last, "request_id": request_id}


def generate_on_channel(channel: dict, args) -> dict:
    creds = channel_creds(channel, "video")
    if not creds["base_url"]:
        return {"ok": False, "error": f"{creds['name']}: missing base_url"}
    if not creds["api_key"] and not args.dry_run:
        return {"ok": False, "error": f"{creds['name']}: missing api_key"}

    base = normalize_base_url(creds["base_url"])
    model = args.model or creds["model"] or "grok-imagine-video"
    tool_mode, payload = build_payload(args, model)
    # REST path family
    rest_family = {
        "extend": "extend",
        "edit": "edit",
        "image_to_video": "generate",
        "reference_to_video": "generate",
        "text_to_video": "generate",
    }[tool_mode]
    url = _start_endpoint(rest_family, base)
    headers = {
        "Authorization": f"Bearer {creds['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    eprint(f"[video] tool={tool_mode} via {creds['name']} model={model}")
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "channel": creds["name"],
            "tool": tool_mode,
            "mode": tool_mode,  # alias for older callers
            "host_tool_equivalent": tool_mode if tool_mode in (
                "image_to_video", "reference_to_video"
            ) else None,
            "url": url,
            "has_api_key": bool(creds["api_key"]),
            "model": model,
            "payload_preview": {
                "prompt": (payload.get("prompt") or "")[:120],
                "duration": payload.get("duration"),
                "aspect_ratio": payload.get("aspect_ratio"),
                "resolution": payload.get("resolution"),
                "has_image": bool(payload.get("image")),
                "has_video": bool(payload.get("video")),
                "reference_images": len(payload.get("reference_images") or []),
            },
        }

    retries = int(args.retry_count if args.retry_count is not None else 2)
    ok, data = http_json(
        "POST", url, headers=headers, payload=payload,
        timeout=args.request_timeout, retries=retries, label="video-start",
    )
    if not ok:
        err = data.get("error") if isinstance(data, dict) else data
        hint = None
        err_s = str(err)
        if "not enabled for this group" in err_s or "permission_error" in err_s:
            hint = (
                "Imagine (image/video generation) is disabled for this API group. "
                "Chat/vision may work while /v1/videos/* and /v1/images/* return 403. "
                "Ask the relay to enable Image/Video generation, or use an official "
                "xAI key with Imagine access. Grok Build host tools use a separate "
                "channel and can work even when this key cannot."
            )
        return {
            "ok": False,
            "channel": creds["name"],
            "tool": tool_mode,
            "error": err,
            "hint": hint,
            "detail": data,
        }

    request_id = data.get("request_id")
    if not request_id:
        # Some proxies return video inline
        if data.get("video") or data.get("url"):
            return {
                "ok": True, "channel": creds["name"], "model": model,
                "tool": tool_mode, "mode": tool_mode, "result": data,
            }
        return {"ok": False, "channel": creds["name"], "error": "No request_id in response", "detail": data}

    eprint(f"[video] request_id={request_id}, polling...")
    result = poll_video(
        base, creds["api_key"], request_id,
        timeout=float(args.poll_timeout), interval=float(args.poll_interval),
    )
    status = (result.get("status") or "").lower()
    if status != "done":
        return {
            "ok": False,
            "channel": creds["name"],
            "tool": tool_mode,
            "request_id": request_id,
            "status": status,
            "error": result.get("error") or result,
        }

    video_info = result.get("video") or {}
    video_url = video_info.get("url") or result.get("url")
    out = {
        "ok": True,
        "channel": creds["name"],
        "model": result.get("model") or model,
        "tool": tool_mode,
        "mode": tool_mode,
        "request_id": request_id,
        "duration": video_info.get("duration"),
        "video_url": video_url,
        "respect_moderation": video_info.get("respect_moderation"),
    }

    if args.output and args.output != "-" and video_url:
        safe, resolved = safe_output_path(args.output)
        if not safe or resolved is None:
            out["download_error"] = f"Unsafe output path: {args.output}"
        else:
            if resolved.suffix.lower() not in (".mp4", ".webm", ".mov"):
                resolved = resolved.with_suffix(".mp4")
            eprint(f"[video] downloading -> {resolved}")
            try:
                download_url(video_url, resolved, timeout=max(120, args.request_timeout))
                out["saved_to"] = str(resolved).replace("\\", "/")
            except Exception as e:
                out["download_error"] = str(e)

    return out


def main():
    parser = argparse.ArgumentParser(
        description=(
            "HelloMedia Video — Grok Imagine REST wrappers for "
            "image_to_video / reference_to_video (Build host-tool equivalents)"
        )
    )
    parser.add_argument("--prompt", default=None, help="Motion / scene prompt")
    parser.add_argument("--prompt-file", default=None, help="Read prompt from UTF-8 file")
    parser.add_argument(
        "--mode",
        default="auto",
        help=(
            "Tool mode: auto|image_to_video|reference_to_video|text_to_video|edit|extend "
            "(aliases: i2v, r2v, t2v). auto infers from --image/--reference/--video."
        ),
    )
    parser.add_argument("--image", default=None, help="Start-frame image path or URL (image_to_video)")
    parser.add_argument(
        "--reference", action="append", default=None,
        help="Reference image path/URL (repeatable; reference_to_video, 1-7 images)",
    )
    parser.add_argument("--video", default=None, help="Source video path/URL for edit or extend")
    parser.add_argument("--extend", action="store_true", help="Extend --video instead of edit")
    # Defaults match Grok Build host tools (6s / 480p); REST still accepts 1-15 / 720p/1080p
    parser.add_argument("--duration", type=int, default=6, help="Duration seconds 1-15 (Build tools: 6 or 10)")
    parser.add_argument(
        "--aspect-ratio", default="16:9",
        choices=("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"),
    )
    parser.add_argument("--resolution", default="480p", choices=("480p", "720p", "1080p"))
    parser.add_argument(
        "--build-compat",
        action="store_true",
        help="Clamp duration to 6 or 10 like Grok Build host tools",
    )
    parser.add_argument("--model", default=None, help="Override video model id")
    parser.add_argument("--channel", type=int, default=None, help="Force channel by priority")
    parser.add_argument("--output", default="./output/generated.mp4", help="Save path for mp4")
    parser.add_argument("--poll-timeout", type=float, default=600, help="Max seconds to wait")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--retry-count", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-meta", default="-", help="Where to write result JSON (default stdout)")
    args = parser.parse_args()

    if args.prompt_file:
        args.prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
    if args.prompt == "-":
        args.prompt = sys.stdin.read().strip()
    if not args.prompt:
        fail({"error": "No prompt. Use --prompt, --prompt-file, or stdin."})

    if args.duration < 1 or args.duration > 15:
        fail({"error": "duration must be 1-15 seconds"})

    try:
        channels, defaults = load_channels("video")
    except FileNotFoundError as e:
        fail({"error": str(e)})

    if args.retry_count is None:
        args.retry_count = int(defaults.get("retry_count", 2))
    if not args.poll_timeout:
        args.poll_timeout = float(defaults.get("video_poll_timeout", 600))

    targets = [c for c in channels if args.channel is None or c.get("priority") == args.channel]
    if not targets:
        fail({
            "error": "No video channels. Set video:true on a channel (e.g. xAI Grok Imagine) in config.json"
        })

    errors = []
    for ch in targets:
        try:
            result = generate_on_channel(ch, args)
        except (ValueError, FileNotFoundError) as e:
            fail({"error": str(e)})
        if result.get("ok"):
            emit_json(result, args.json_meta)
            return
        errors.append(f"{ch.get('name')}: {result.get('error') or result}")
        eprint(f"[video] channel failed: {errors[-1]}")

    fail({"error": "All video channels failed", "details": errors})


if __name__ == "__main__":
    main()
