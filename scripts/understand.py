#!/usr/bin/env python3
"""
HelloMedia — Media understanding (image / video / audio).

- image: multimodal chat (same as vision path)
- video: multimodal chat with video_url when supported; optional STT of soundtrack not required
- audio: STT first (via audio channels), then optional LLM summary with --prompt

Host model should try native media first; this script is the external fallback.
Pure stdlib.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    USER_AGENT,
    channel_creds,
    emit_json,
    eprint,
    fail,
    file_to_data_url,
    http_json,
    load_channels,
    mime_for_path,
    normalize_base_url,
    normalize_path,
)

# Keep video inline under ~15MB for chat payloads
_MAX_VIDEO_INLINE = 15 * 1024 * 1024
_MAX_AUDIO_INLINE = 10 * 1024 * 1024


def _to_url(path_or_url: str, max_bytes: int) -> str:
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    p = normalize_path(path_or_url)
    if not p or not Path(p).exists():
        raise FileNotFoundError(f"Not found: {path_or_url}")
    return file_to_data_url(p, max_bytes=max_bytes)


def _chat_openai(creds: dict, content: list, max_tokens: int, timeout: float, retries: int):
    base = normalize_base_url(creds["base_url"])
    url = f"{base}/v1/chat/completions"
    payload = {
        "model": creds["model"],
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {creds['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    return http_json(
        "POST", url, headers=headers, payload=payload,
        timeout=timeout, retries=retries, label="understand",
    )


def understand_image(channels, prompt, image, max_tokens, timeout, retries):
    # Prefer vision-capable channels
    for ch in channels:
        creds = channel_creds(ch, "vision")
        if not creds["model"] or not creds["api_key"]:
            continue
        try:
            url = _to_url(image, max_bytes=20 * 1024 * 1024)
        except Exception as e:
            return False, {"error": str(e)}
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url, "detail": "high"}},
        ]
        eprint(f"[understand] image via {creds['name']} ({creds['model']})")
        ok, data = _chat_openai(creds, content, max_tokens, timeout, retries)
        if ok:
            data["_channel"] = creds["name"]
            data["_model"] = creds["model"]
            data["_modality"] = "image"
            return True, data
        eprint(f"[understand] failed: {data.get('error')}")
    return False, {"error": "All image channels failed"}


def understand_video(channels, prompt, video, max_tokens, timeout, retries):
    for ch in channels:
        creds = channel_creds(ch, "vision")
        if not creds["model"] or not creds["api_key"]:
            continue
        try:
            url = _to_url(video, max_bytes=_MAX_VIDEO_INLINE)
        except ValueError as e:
            return False, {
                "error": str(e),
                "hint": "Use a public HTTPS URL for large videos, or compress the file.",
            }
        except Exception as e:
            return False, {"error": str(e)}

        # Try several content shapes used by multimodal providers
        shapes = [
            [
                {"type": "text", "text": prompt},
                {"type": "video_url", "video_url": {"url": url}},
            ],
            [
                {"type": "text", "text": prompt},
                {"type": "input_video", "video_url": url},
            ],
            # Some proxies accept image_url with video mime (fallback)
            [
                {"type": "text", "text": prompt + "\n(Analyze this video.)"},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        ]
        eprint(f"[understand] video via {creds['name']} ({creds['model']})")
        last_err = None
        for content in shapes:
            ok, data = _chat_openai(creds, content, max_tokens, timeout, retries)
            if ok:
                data["_channel"] = creds["name"]
                data["_model"] = creds["model"]
                data["_modality"] = "video"
                return True, data
            last_err = data
            # permanent shape mismatch → try next shape
            status = data.get("status")
            if status and status not in (400, 415, 422):
                break
        eprint(f"[understand] video failed: {(last_err or {}).get('error')}")
    return False, {
        "error": "All video understanding attempts failed",
        "hint": "Ensure the vision model supports video input (e.g. Grok multimodal). "
                "For audio track only, use: python scripts/audio.py stt --audio <file>",
    }


def understand_audio(audio_channels, vision_channels, prompt, audio, max_tokens, timeout, retries):
    """STT then optional LLM wrap with prompt."""
    # Import lazily to reuse audio helpers without circular import issues
    import audio as audio_mod  # noqa: WPS433

    class NS:
        pass

    stt_args = NS()
    stt_args.audio = audio
    stt_args.audio_url = None if not str(audio).startswith("http") else audio
    if stt_args.audio_url:
        stt_args.audio = None
    stt_args.language = None
    stt_args.format_text = True
    stt_args.diarize = False
    stt_args.keyterm = None
    stt_args.model = None
    stt_args.output = "-"
    stt_args.timeout = timeout
    stt_args.retry_count = retries
    stt_args.dry_run = False
    stt_args.backend = "auto"

    transcript = None
    stt_meta = None
    for ch in audio_channels:
        creds = channel_creds(ch, "audio")
        backend = audio_mod.pick_tts_backend(creds)
        if backend == "xai":
            result = audio_mod.stt_xai(creds, stt_args)
        else:
            if not stt_args.audio:
                continue
            result = audio_mod.stt_openai_compat(creds, stt_args)
        if result.get("ok"):
            transcript = result.get("text")
            stt_meta = result
            break
        eprint(f"[understand] STT failed on {creds['name']}: {result.get('error')}")

    if not transcript:
        return False, {"error": "STT failed on all audio channels"}

    # If no extra prompt or trivial, return transcript
    if not prompt or prompt.strip() in ("transcribe", "转录", "转写"):
        return True, {
            "ok": True,
            "_modality": "audio",
            "transcript": transcript,
            "stt": stt_meta,
            "choices": [{"message": {"content": transcript}}],
        }

    summary_prompt = (
        f"{prompt}\n\n--- Transcript ---\n{transcript}\n--- End ---"
    )
    for ch in vision_channels or audio_channels:
        # use vision/chat model for summarization
        model = ch.get("model") or ch.get("audio_model")
        if not model:
            continue
        creds = {
            "name": ch.get("name"),
            "base_url": ch.get("base_url", ""),
            "api_key": ch.get("api_key", ""),
            "model": model,
        }
        if not creds["api_key"]:
            continue
        content = [{"type": "text", "text": summary_prompt}]
        ok, data = _chat_openai(creds, content, max_tokens, timeout, retries)
        if ok:
            data["_modality"] = "audio"
            data["_channel"] = creds["name"]
            data["_model"] = model
            data["transcript"] = transcript
            data["stt"] = stt_meta
            return True, data

    # Fallback: transcript only
    return True, {
        "ok": True,
        "_modality": "audio",
        "transcript": transcript,
        "stt": stt_meta,
        "choices": [{"message": {"content": transcript}}],
        "note": "LLM summary skipped; returned transcript only",
    }


def main():
    parser = argparse.ArgumentParser(description="HelloMedia media understanding")
    parser.add_argument("--image", default=None)
    parser.add_argument("--video", default=None)
    parser.add_argument("--audio", default=None)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", default="-")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--channel", type=int, default=None)
    args = parser.parse_args()

    modalities = [m for m in (args.image, args.video, args.audio) if m]
    if len(modalities) != 1:
        fail({"error": "Provide exactly one of --image, --video, or --audio"})

    try:
        vision_chs, defaults = load_channels("vision")
    except FileNotFoundError:
        vision_chs, defaults = [], {}
    try:
        audio_chs, defaults_a = load_channels("audio")
        if not defaults:
            defaults = defaults_a
    except FileNotFoundError:
        audio_chs = []

    max_tokens = args.max_tokens or defaults.get("max_tokens", 4096)
    timeout = float(defaults.get("timeout_seconds", 300))
    retries = int(defaults.get("retry_count", 2))

    if args.channel is not None:
        vision_chs = [c for c in vision_chs if c.get("priority") == args.channel]
        audio_chs = [c for c in audio_chs if c.get("priority") == args.channel]

    try:
        if args.image:
            if not vision_chs:
                fail({"error": "No vision channels configured"})
            ok, result = understand_image(
                vision_chs, args.prompt, args.image, max_tokens, timeout, retries
            )
        elif args.video:
            if not vision_chs:
                fail({"error": "No vision channels configured for video understanding"})
            ok, result = understand_video(
                vision_chs, args.prompt, args.video, max_tokens, timeout, retries
            )
        else:
            if not audio_chs:
                fail({"error": "No audio channels configured for STT"})
            ok, result = understand_audio(
                audio_chs, vision_chs, args.prompt, args.audio, max_tokens, timeout, retries
            )
    except FileNotFoundError as e:
        fail({"error": str(e)})

    if not ok:
        fail(result)
    emit_json(result, args.output)


if __name__ == "__main__":
    main()
