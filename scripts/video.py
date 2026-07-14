#!/usr/bin/env python3
"""
HelloMedia — Video generation via xAI Grok Imagine REST API.

Grok Build host tool equivalents + edit/extend (gated by channel flags):

  image_to_video      POST /v1/videos/generations + image
  reference_to_video  POST /v1/videos/generations + reference_images
  text_to_video       POST /v1/videos/generations prompt-only
  edit / extend       POST /v1/videos/edits | /extensions (channel video_edit/video_extend)

Async: POST start → poll GET /v1/videos/{request_id} → download mp4.
Download failure preserves URL for GET-only recovery (--recover-url).
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
    check_xai_network,
    configure_proxy_opener,
    download_url,
    emit_json,
    eprint,
    fail,
    file_to_data_url,
    http_json,
    is_official_xai_host,
    is_xai_like_channel,
    load_channels,
    normalize_base_url,
    normalize_path,
    recover_media_url,
    resolve_media_user_agent,
    safe_output_path,
    video_image_url_field,
)
from media_caps import (  # noqa: E402
    ValidationError,
    default_video_model,
    validate_video_request,
)

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


def channel_video_flags(channel: dict) -> tuple[bool, bool]:
    # Default: allow edit/extend for xAI-like; others false unless set
    default_edit = is_xai_like_channel(channel)
    edit = channel.get("video_edit")
    extend = channel.get("video_extend")
    if edit is None:
        edit = default_edit
    if extend is None:
        extend = default_edit
    return bool(edit), bool(extend)


def build_payload(args, model: str, channel: dict) -> tuple[str, dict, dict]:
    """Return (tool_mode, payload, validate_meta)."""
    prompt = (args.prompt or "").strip()
    tool_mode = resolve_tool_mode(args)
    video_edit, video_extend = channel_video_flags(channel)

    # aspect: None means omit (I2V preserve source); CLI default may be unset
    aspect_explicit = bool(getattr(args, "aspect_ratio_explicit", False))
    aspect_value = args.aspect_ratio if aspect_explicit else (
        args.aspect_ratio if tool_mode != "image_to_video" else None
    )

    n_refs = len(args.reference or [])
    meta = validate_video_request(
        tool_mode=tool_mode,
        duration=int(args.duration),
        resolution=args.resolution,
        aspect_ratio=aspect_value,
        model=model,
        n_refs=n_refs,
        has_image=bool(args.image),
        has_video=bool(args.video),
        prompt=prompt,
        aspect_explicit=aspect_explicit or tool_mode != "image_to_video",
        video_edit=video_edit,
        video_extend=video_extend,
    )

    if tool_mode == "extend":
        return "extend", {
            "model": model,
            "prompt": prompt,
            "video": {"url": _media_url(args.video)},
        }, meta

    if tool_mode == "edit":
        return "edit", {
            "model": model,
            "prompt": prompt,
            "video": {"url": _media_url(args.video)},
        }, meta

    duration = int(meta["duration"])
    if args.build_compat and duration not in (6, 10):
        duration = 6 if duration < 8 else 10

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "resolution": meta["resolution"],
    }
    if not meta.get("omit_aspect_ratio") and meta.get("aspect_ratio"):
        payload["aspect_ratio"] = meta["aspect_ratio"]

    # Sub2API: image_url; official api.x.ai: url (see video_image_url_field)
    img_field = video_image_url_field(
        channel.get("video_base_url") or channel.get("base_url") or "",
        channel,
    )
    ref_field = str(channel.get("reference_url_field") or "url").strip() or "url"

    if tool_mode == "image_to_video":
        payload["image"] = {img_field: _media_url(args.image)}
        return "image_to_video", payload, meta

    if tool_mode == "reference_to_video":
        refs_in = args.reference or []
        payload["reference_images"] = [{ref_field: _media_url(r)} for r in refs_in]
        return "reference_to_video", payload, meta

    if tool_mode == "text_to_video":
        return "text_to_video", payload, meta

    raise ValueError(
        f"Unknown mode: {tool_mode}. "
        "Use auto|image_to_video|reference_to_video|text_to_video|edit|extend"
    )


def poll_video(base: str, api_key: str, request_id: str, *, timeout: float, interval: float) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": resolve_media_user_agent(),
    }
    deadline = time.time() + timeout
    url = f"{base}/v1/videos/{request_id}"
    last = {}
    while time.time() < deadline:
        ok, data = http_json("GET", url, headers=headers, payload=None, timeout=60, retries=1, label="video-poll")
        if not ok:
            last = data if isinstance(data, dict) else {"error": str(data)}
            status_code = last.get("status")
            eprint(f"[video] poll error: {last.get('error')}")
            # Permanent auth/client errors: fail fast instead of spinning until poll_timeout
            if isinstance(status_code, int) and status_code in (400, 401, 402, 403, 404, 405, 410, 422):
                return {
                    "status": "failed",
                    "error": last.get("error") or f"poll HTTP {status_code}",
                    "http_status": status_code,
                    "request_id": request_id,
                    "last": last,
                }
            time.sleep(interval)
            continue
        last = data
        status = (data.get("status") or "").lower()
        eprint(f"[video] status={status}")
        if status in ("done", "completed", "complete", "succeeded", "success"):
            return data
        if status in ("failed", "expired", "error", "cancelled", "canceled"):
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
    tool_mode_hint = resolve_tool_mode(args)
    model = default_video_model(tool_mode_hint, creds.get("model"), args.model)

    # Only official api.x.ai requires direct CDN preflight. Sub2API relays
    # (api_format=xai but base_url != api.x.ai) generate via the relay; blocking
    # on local api.x.ai reachability is a false negative (happy-loki/grok-media-skill).
    need_xai_preflight = getattr(args, "network_check", False) or (
        is_official_xai_host(base)
        and not args.dry_run
        and not getattr(args, "skip_network_check", False)
    )
    if need_xai_preflight:
        pre = check_xai_network(timeout=5.0, use_cache=not getattr(args, "network_check", False))
        if not pre.get("ok"):
            return {
                "ok": False,
                "error": "xAI network preflight failed; cannot reach required media domains",
                "network": pre,
                "channel": creds["name"],
                "hint": (
                    "Preflight only applies to official api.x.ai. "
                    "For Sub2API relays set base_url to the relay and skip with --skip-network-check if needed."
                ),
            }

    tool_mode, payload, meta = build_payload(args, model, channel)
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
        "Accept": "application/json",
        "User-Agent": resolve_media_user_agent(),
    }

    eprint(f"[video] tool={tool_mode} via {creds['name']} model={model}")
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "channel": creds["name"],
            "tool": tool_mode,
            "mode": tool_mode,
            "host_tool_equivalent": tool_mode if tool_mode in (
                "image_to_video", "reference_to_video"
            ) else None,
            "url": url,
            "has_api_key": bool(creds["api_key"]),
            "model": model,
            "video_edit": channel_video_flags(channel)[0],
            "video_extend": channel_video_flags(channel)[1],
            "payload_preview": {
                "prompt": (payload.get("prompt") or "")[:120],
                "duration": payload.get("duration"),
                "aspect_ratio": payload.get("aspect_ratio"),
                "aspect_ratio_omitted": "aspect_ratio" not in payload and tool_mode == "image_to_video",
                "resolution": payload.get("resolution"),
                "has_image": bool(payload.get("image")),
                "has_video": bool(payload.get("video")),
                "reference_images": len(payload.get("reference_images") or []),
            },
            "validation": meta,
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
                "Chat/vision may work while /v1/videos/* and /v1/images/* return 403."
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
        if data.get("video") or data.get("url"):
            return {
                "ok": True, "channel": creds["name"], "model": model,
                "tool": tool_mode, "mode": tool_mode, "status": "completed", "result": data,
            }
        return {"ok": False, "channel": creds["name"], "error": "No request_id in response", "detail": data}

    eprint(f"[video] request_id={request_id}, polling...")
    result = poll_video(
        base, creds["api_key"], request_id,
        timeout=float(args.poll_timeout), interval=float(args.poll_interval),
    )
    status = (result.get("status") or "").lower()
    if status not in ("done", "completed", "complete", "succeeded", "success"):
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
        "status": "completed",
        "channel": creds["name"],
        "model": result.get("model") or model,
        "tool": tool_mode,
        "mode": tool_mode,
        "request_id": request_id,
        "duration": video_info.get("duration"),
        "video_url": video_url,
        "urls": [video_url] if video_url else [],
        "respect_moderation": video_info.get("respect_moderation"),
    }

    if args.output and args.output != "-" and video_url:
        safe, resolved = safe_output_path(args.output)
        if not safe or resolved is None:
            out["download_error"] = f"Unsafe output path: {args.output}"
            out["saved_to"] = None
        else:
            if resolved.suffix.lower() not in (".mp4", ".webm", ".mov"):
                resolved = resolved.with_suffix(".mp4")
            eprint(f"[video] downloading -> {resolved}")
            try:
                download_url(
                    video_url,
                    resolved,
                    timeout=max(120, args.request_timeout),
                    api_key=creds.get("api_key"),
                    base_url=base,
                )
                path_s = str(resolved).replace("\\", "/")
                out["saved_to"] = path_s
                out["markdown_media"] = f"![video]({path_s})"
            except Exception as e:
                out["download_error"] = str(e)
                out["saved_to"] = None
                # generation still succeeded — caller may --recover-url
    elif video_url and (not args.output or args.output == "-"):
        out["saved_to"] = None

    return out


def main():
    configure_proxy_opener()
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
    parser.add_argument("--duration", type=int, default=6, help="Duration seconds 1-15 (reference max 10)")
    parser.add_argument(
        "--aspect-ratio",
        default=None,
        help="Video aspect ratio (omit for I2V to preserve source). Choices: 1:1,16:9,9:16,4:3,3:4,3:2,2:3",
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
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=None,
        help="Max seconds to wait (default: config defaults.video_poll_timeout or 600)",
    )
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--request-timeout", type=float, default=120)
    parser.add_argument("--retry-count", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--network-check", action="store_true", help="Force xAI CDN preflight")
    parser.add_argument("--skip-network-check", action="store_true", help="Skip xAI CDN preflight")
    parser.add_argument(
        "--recover-url",
        default=None,
        help="GET-only re-download a previously returned media URL (no generate POST)",
    )
    parser.add_argument("--json-meta", default="-", help="Where to write result JSON (default stdout)")
    args = parser.parse_args()

    # Recover path — no channel config required beyond output safety
    if args.recover_url:
        result = recover_media_url(
            args.recover_url,
            args.output or "./output/recovered.mp4",
            kind="video",
            timeout=max(120, float(args.request_timeout or 120)),
        )
        if result.get("ok"):
            emit_json(result, args.json_meta)
            return
        fail(result)

    # Track whether user explicitly set aspect-ratio
    args.aspect_ratio_explicit = args.aspect_ratio is not None
    if args.aspect_ratio is None:
        # non-I2V defaults to 16:9 for dry-run payload stability
        args.aspect_ratio = "16:9"

    if args.prompt_file:
        args.prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
    if args.prompt == "-":
        args.prompt = sys.stdin.read().strip()
    # I2V may allow empty prompt at API level; our validate still wants prompt for most modes
    if not args.prompt and not args.image:
        fail({"error": "No prompt. Use --prompt, --prompt-file, or stdin."})
    if not args.prompt:
        args.prompt = ""

    try:
        channels, defaults = load_channels("video")
    except FileNotFoundError as e:
        fail({"error": str(e)})

    if args.retry_count is None:
        args.retry_count = int(defaults.get("retry_count", 2))
    if args.poll_timeout is None:
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
        except ValidationError as e:
            fail(e.to_dict())
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
