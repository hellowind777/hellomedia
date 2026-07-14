#!/usr/bin/env python3
"""
HelloMedia — Audio generation (TTS) and understanding (STT).

Aligned with xAI Voice API:
  TTS: POST /v1/tts  (JSON → audio bytes)
  STT: POST /v1/stt  (multipart file → JSON transcript)

Also supports OpenAI-compatible TTS/STT paths when channel is not xAI-native.
Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import random
import sys
import time
import urllib.error
import urllib.request
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
    http_bytes,
    http_json,
    load_channels,
    normalize_base_url,
    normalize_path,
    safe_output_path,
    ensure_parent,
)


def _multipart(fields: list[tuple[str, str]], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----hello-mm-{random.randint(100000, 999999)}-{int(time.time() * 1000)}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, path in files:
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), boundary


def tts_xai(creds: dict, args) -> dict:
    base = normalize_base_url(creds["base_url"])
    url = f"{base}/v1/tts"
    payload = {
        "text": args.text,
        "voice_id": args.voice or creds.get("voice_id") or "eve",
        "language": args.language or "auto",
    }
    if args.speed is not None:
        payload["speed"] = float(args.speed)
    if args.codec:
        of: dict = {"codec": args.codec}
        if args.sample_rate:
            of["sample_rate"] = int(args.sample_rate)
        if args.bit_rate and args.codec == "mp3":
            of["bit_rate"] = int(args.bit_rate)
        payload["output_format"] = of

    if args.dry_run:
        return {"ok": True, "dry_run": True, "mode": "tts", "url": url, "payload": {**payload, "text": payload["text"][:80]}}

    headers = {
        "Authorization": f"Bearer {creds['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    data = json.dumps(payload).encode("utf-8")
    ok, body, resp_headers = http_bytes(
        "POST", url, headers=headers, data=data,
        timeout=args.timeout, retries=args.retry_count, label="tts",
    )
    if not ok:
        return {"ok": False, "error": body if isinstance(body, dict) else {"error": str(body)}}

    # timestamps mode returns JSON
    ctype = (resp_headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            meta = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            meta = {"_raw": body[:200]}
        return {"ok": True, "mode": "tts", "channel": creds["name"], "json_response": meta}

    ext = ".mp3"
    if args.codec == "wav":
        ext = ".wav"
    elif args.codec in ("pcm", "mulaw", "alaw"):
        ext = f".{args.codec}"

    out_path = args.output or f"./output/speech{ext}"
    safe, resolved = safe_output_path(out_path)
    if not safe or resolved is None:
        return {"ok": False, "error": f"Unsafe output path: {out_path}"}
    ensure_parent(resolved)
    resolved.write_bytes(body)
    return {
        "ok": True,
        "mode": "tts",
        "channel": creds["name"],
        "voice_id": payload["voice_id"],
        "language": payload["language"],
        "bytes": len(body),
        "saved_to": str(resolved).replace("\\", "/"),
        "content_type": resp_headers.get("Content-Type"),
    }


def tts_openai_compat(creds: dict, args) -> dict:
    """OpenAI-style POST /v1/audio/speech."""
    base = normalize_base_url(creds["base_url"])
    url = f"{base}/v1/audio/speech"
    model = args.model or creds.get("model") or "tts-1"
    payload = {
        "model": model,
        "input": args.text,
        "voice": args.voice or creds.get("voice_id") or "alloy",
        "response_format": args.codec or "mp3",
    }
    if args.speed is not None:
        payload["speed"] = float(args.speed)
    if args.dry_run:
        return {"ok": True, "dry_run": True, "mode": "tts-openai", "url": url, "payload": payload}

    headers = {
        "Authorization": f"Bearer {creds['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    data = json.dumps(payload).encode("utf-8")
    ok, body, resp_headers = http_bytes(
        "POST", url, headers=headers, data=data,
        timeout=args.timeout, retries=args.retry_count, label="tts-openai",
    )
    if not ok:
        return {"ok": False, "error": body}

    out_path = args.output or f"./output/speech.{payload['response_format']}"
    safe, resolved = safe_output_path(out_path)
    if not safe or resolved is None:
        return {"ok": False, "error": f"Unsafe output path: {out_path}"}
    ensure_parent(resolved)
    resolved.write_bytes(body)
    return {
        "ok": True,
        "mode": "tts-openai",
        "channel": creds["name"],
        "model": model,
        "bytes": len(body),
        "saved_to": str(resolved).replace("\\", "/"),
    }


def stt_xai(creds: dict, args) -> dict:
    base = normalize_base_url(creds["base_url"])
    url = f"{base}/v1/stt"
    if args.dry_run:
        return {"ok": True, "dry_run": True, "mode": "stt", "url": url, "file": args.audio}

    fields: list[tuple[str, str]] = []
    if args.language:
        fields.append(("language", args.language))
    if args.format_text:
        fields.append(("format", "true"))
    if args.diarize:
        fields.append(("diarize", "true"))
    for kt in args.keyterm or []:
        fields.append(("keyterm", kt))

    headers = {
        "Authorization": f"Bearer {creds['api_key']}",
        "User-Agent": USER_AGENT,
    }

    if args.audio_url:
        fields.append(("url", args.audio_url))
        # multipart with only fields
        body, boundary = _multipart(fields, [])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        ok, raw, _ = http_bytes(
            "POST", url, headers=headers, data=body,
            timeout=args.timeout, retries=args.retry_count, label="stt",
        )
    else:
        path = normalize_path(args.audio)
        if not path or not Path(path).exists():
            return {"ok": False, "error": f"Audio file not found: {args.audio}"}
        # file must be last field per xAI docs
        body, boundary = _multipart(fields, [("file", Path(path))])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        ok, raw, _ = http_bytes(
            "POST", url, headers=headers, data=body,
            timeout=args.timeout, retries=args.retry_count, label="stt",
        )

    if not ok:
        return {"ok": False, "error": raw}

    try:
        result = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {"ok": False, "error": "Invalid JSON from STT", "raw": raw[:300]}

    out = {
        "ok": True,
        "mode": "stt",
        "channel": creds["name"],
        "text": result.get("text"),
        "language": result.get("language"),
        "duration": result.get("duration"),
        "words": result.get("words"),
        "channels": result.get("channels"),
    }
    if args.output and args.output != "-":
        emit_json(out, args.output)
        out["saved_to"] = args.output
    return out


def stt_openai_compat(creds: dict, args) -> dict:
    base = normalize_base_url(creds["base_url"])
    url = f"{base}/v1/audio/transcriptions"
    model = args.model or creds.get("model") or "whisper-1"
    if args.dry_run:
        return {"ok": True, "dry_run": True, "mode": "stt-openai", "url": url, "model": model}

    path = normalize_path(args.audio)
    if not path or not Path(path).exists():
        return {"ok": False, "error": f"Audio file not found: {args.audio}"}

    fields = [("model", model)]
    if args.language:
        fields.append(("language", args.language))
    body, boundary = _multipart(fields, [("file", Path(path))])
    headers = {
        "Authorization": f"Bearer {creds['api_key']}",
        "User-Agent": USER_AGENT,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    ok, raw, _ = http_bytes(
        "POST", url, headers=headers, data=body,
        timeout=args.timeout, retries=args.retry_count, label="stt-openai",
    )
    if not ok:
        return {"ok": False, "error": raw}
    try:
        result = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {"ok": False, "error": "Invalid JSON", "raw": raw[:300]}
    return {
        "ok": True,
        "mode": "stt-openai",
        "channel": creds["name"],
        "model": model,
        "text": result.get("text"),
        "raw": result,
    }


def list_voices(creds: dict, timeout: float) -> dict:
    base = normalize_base_url(creds["base_url"])
    url = f"{base}/v1/tts/voices"
    headers = {"Authorization": f"Bearer {creds['api_key']}", "User-Agent": USER_AGENT}
    ok, data = http_json("GET", url, headers=headers, timeout=timeout, retries=1, label="voices")
    if not ok:
        return {"ok": False, "error": data}
    return {"ok": True, "channel": creds["name"], "voices": data.get("voices") or data}


def pick_tts_backend(creds: dict) -> str:
    fmt = creds.get("api_format") or "openai"
    if fmt in ("xai", "grok"):
        return "xai"
    base = (creds.get("base_url") or "").lower()
    if "x.ai" in base:
        return "xai"
    return "openai"


def main():
    parser = argparse.ArgumentParser(description="HelloMedia Audio (TTS/STT)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tts = sub.add_parser("tts", help="Text to speech")
    p_tts.add_argument("--text", default=None)
    p_tts.add_argument("--text-file", default=None)
    p_tts.add_argument("--voice", default=None, help="voice_id (xAI) or voice name (OpenAI)")
    p_tts.add_argument("--language", default="auto")
    p_tts.add_argument("--speed", type=float, default=None)
    p_tts.add_argument("--codec", default="mp3", choices=("mp3", "wav", "pcm", "mulaw", "alaw"))
    p_tts.add_argument("--sample-rate", type=int, default=None)
    p_tts.add_argument("--bit-rate", type=int, default=None)
    p_tts.add_argument("--model", default=None)
    p_tts.add_argument("--output", default="./output/speech.mp3")
    p_tts.add_argument("--channel", type=int, default=None)
    p_tts.add_argument("--timeout", type=float, default=120)
    p_tts.add_argument("--retry-count", type=int, default=2)
    p_tts.add_argument("--dry-run", action="store_true")
    p_tts.add_argument("--backend", choices=("auto", "xai", "openai"), default="auto")

    p_stt = sub.add_parser("stt", help="Speech to text")
    p_stt.add_argument("--audio", default=None, help="Local audio file path")
    p_stt.add_argument("--audio-url", default=None, help="Remote audio URL (xAI)")
    p_stt.add_argument("--language", default=None)
    p_stt.add_argument("--format-text", action="store_true", help="Enable ITN formatting (xAI)")
    p_stt.add_argument("--diarize", action="store_true")
    p_stt.add_argument("--keyterm", action="append", default=None)
    p_stt.add_argument("--model", default=None)
    p_stt.add_argument("--output", default="-", help="JSON output path")
    p_stt.add_argument("--channel", type=int, default=None)
    p_stt.add_argument("--timeout", type=float, default=180)
    p_stt.add_argument("--retry-count", type=int, default=2)
    p_stt.add_argument("--dry-run", action="store_true")
    p_stt.add_argument("--backend", choices=("auto", "xai", "openai"), default="auto")

    p_voices = sub.add_parser("voices", help="List TTS voices (xAI)")
    p_voices.add_argument("--channel", type=int, default=None)
    p_voices.add_argument("--timeout", type=float, default=30)

    args = parser.parse_args()

    try:
        channels, defaults = load_channels("audio")
    except FileNotFoundError as e:
        fail({"error": str(e)})

    targets = [c for c in channels if args.channel is None or c.get("priority") == args.channel]
    if not targets:
        fail({"error": "No audio channels. Set audio:true on a channel in config.json"})

    if args.cmd == "tts":
        if args.text_file:
            args.text = Path(args.text_file).expanduser().read_text(encoding="utf-8").strip()
        if args.text == "-":
            args.text = sys.stdin.read().strip()
        if not args.text:
            fail({"error": "No text. Use --text, --text-file, or stdin."})
        if len(args.text) > 15000:
            fail({"error": "Text exceeds 15,000 characters (xAI unary TTS limit)"})

        errors = []
        for ch in targets:
            creds = channel_creds(ch, "audio")
            if not creds["base_url"]:
                errors.append(f"{creds['name']}: missing base_url")
                continue
            if not creds["api_key"] and not args.dry_run:
                errors.append(f"{creds['name']}: missing api_key")
                continue
            backend = args.backend
            if backend == "auto":
                backend = pick_tts_backend(creds)
            result = tts_xai(creds, args) if backend == "xai" else tts_openai_compat(creds, args)
            if result.get("ok"):
                emit_json(result)
                return
            errors.append(f"{creds['name']}: {result.get('error')}")
            # if xAI failed with 404, try openai-compat on same channel
            if backend == "xai" and args.backend == "auto" and not args.dry_run:
                eprint("[audio] xAI TTS failed, trying OpenAI-compatible /v1/audio/speech")
                result2 = tts_openai_compat(creds, args)
                if result2.get("ok"):
                    emit_json(result2)
                    return
                errors.append(f"{creds['name']}/openai: {result2.get('error')}")
        fail({"error": "All TTS channels failed", "details": errors})

    if args.cmd == "stt":
        if not args.audio and not args.audio_url:
            fail({"error": "Provide --audio or --audio-url"})
        errors = []
        for ch in targets:
            creds = channel_creds(ch, "audio")
            if not creds["base_url"]:
                errors.append(f"{creds['name']}: missing base_url")
                continue
            if not creds["api_key"] and not args.dry_run:
                errors.append(f"{creds['name']}: missing api_key")
                continue
            backend = args.backend
            if backend == "auto":
                backend = pick_tts_backend(creds)
            result = stt_xai(creds, args) if backend == "xai" else stt_openai_compat(creds, args)
            if result.get("ok"):
                if args.output == "-" or not result.get("saved_to"):
                    emit_json(result, args.output if args.output != "-" else "-")
                else:
                    emit_json(result)
                return
            errors.append(f"{creds['name']}: {result.get('error')}")
            if backend == "xai" and args.backend == "auto" and args.audio:
                eprint("[audio] xAI STT failed, trying OpenAI-compatible transcriptions")
                result2 = stt_openai_compat(creds, args)
                if result2.get("ok"):
                    emit_json(result2, args.output)
                    return
                errors.append(f"{creds['name']}/openai: {result2.get('error')}")
        fail({"error": "All STT channels failed", "details": errors})

    if args.cmd == "voices":
        errors = []
        for ch in targets:
            creds = channel_creds(ch, "audio")
            result = list_voices(creds, args.timeout)
            if result.get("ok"):
                emit_json(result)
                return
            errors.append(f"{creds['name']}: {result.get('error')}")
        fail({"error": "Could not list voices", "details": errors})


if __name__ == "__main__":
    main()
