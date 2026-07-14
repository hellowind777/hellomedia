#!/usr/bin/env python3
"""HelloMedia — channel connectivity doctor (read-only probes)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    SKILL_DIR,
    USER_AGENT,
    check_xai_network,
    configure_proxy_opener,
    eprint,
    load_config,
    normalize_base_url,
    proxy_summary,
    skill_version,
)
from media_caps import capabilities_dict  # noqa: E402


def _pillow_installed() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def probe_models(base_url: str, api_key: str, timeout: float) -> dict:
    base = normalize_base_url(base_url)
    url = f"{base}/v1/models"
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            ids = [
                m.get("id", "")
                for m in (data.get("data") or [])
                if isinstance(m, dict)
            ]
            return {
                "ok": True,
                "http_status": getattr(resp, "status", 200),
                "model_count": len(ids),
                "sample_models": ids[:15],
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "http_status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def probe_chat_openai(base_url: str, api_key: str, model: str, timeout: float) -> dict:
    if not model:
        return {"ok": False, "error": "empty model"}
    base = normalize_base_url(base_url)
    url = f"{base}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 5,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return {"ok": True, "reply_preview": str(text)[:80]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "http_status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def probe_anthropic(base_url: str, api_key: str, model: str, timeout: float) -> dict:
    if not model:
        return {"ok": False, "error": "empty model"}
    base = normalize_base_url(base_url)
    url = f"{base}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            texts = [
                b.get("text", "")
                for b in data.get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return {"ok": True, "reply_preview": "".join(texts)[:80]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "http_status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def diagnose_channel(ch: dict, timeout: float, *, probe_live: bool) -> dict:
    name = ch.get("name", "?")
    api_format = ch.get("api_format", "openai")
    base_url = ch.get("base_url", "")
    api_key = ch.get("api_key", "")
    report = {
        "name": name,
        "priority": ch.get("priority"),
        "api_format": api_format,
        "base_url": base_url,
        "api_key_set": bool(api_key),
        "vision_enabled": bool(ch.get("vision")),
        "generate_enabled": bool(ch.get("generate")),
        "video_enabled": bool(ch.get("video")),
        "audio_enabled": bool(ch.get("audio")),
        "model": ch.get("model") or "",
        "image_model": ch.get("image_model") or "",
        "video_model": ch.get("video_model") or "",
    }
    if not base_url:
        report["status"] = "skip"
        report["error"] = "missing base_url"
        return report
    if not api_key and api_format != "sd-webui":
        report["status"] = "warn"
        report["error"] = "api_key empty"
    if not probe_live:
        report["status"] = report.get("status") or "dry"
        return report

    if api_format == "sd-webui":
        try:
            req = urllib.request.Request(
                base_url.rstrip("/") + "/", headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                report["sd_webui"] = {
                    "ok": True,
                    "http_status": getattr(resp, "status", 200),
                }
                report["status"] = "ok"
        except Exception as e:
            report["sd_webui"] = {"ok": False, "error": str(e)}
            report["status"] = "fail"
        return report

    report["models_endpoint"] = probe_models(base_url, api_key, timeout)

    if ch.get("vision") and ch.get("model"):
        if api_format == "anthropic":
            report["vision_probe"] = probe_anthropic(
                base_url, api_key, ch["model"], timeout
            )
        else:
            report["vision_probe"] = probe_chat_openai(
                base_url, api_key, ch["model"], timeout
            )

    if ch.get("video"):
        vbase = ch.get("video_base_url") or base_url
        vkey = ch.get("video_api_key") or api_key
        report["video_models_endpoint"] = probe_models(vbase, vkey, timeout)
        report["video_probe_note"] = (
            "skipped live video generation (cost); models_endpoint only"
        )

    if ch.get("audio"):
        abase = ch.get("audio_base_url") or base_url
        akey = ch.get("audio_api_key") or api_key
        # Light probe: list TTS voices if xAI-style
        voices_url = f"{normalize_base_url(abase)}/v1/tts/voices"
        try:
            req = urllib.request.Request(
                voices_url,
                headers={"Authorization": f"Bearer {akey}", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                voices = data.get("voices") or []
                report["audio_voices"] = {
                    "ok": True,
                    "count": len(voices),
                    "sample": [v.get("voice_id") for v in voices[:8] if isinstance(v, dict)],
                }
        except Exception as e:
            report["audio_voices"] = {"ok": False, "error": str(e)[:200]}

    if ch.get("generate"):
        report["generate_probe_note"] = (
            "skipped live image generation (cost); models_endpoint + vision_probe only"
        )

    vision_ok = report.get("vision_probe", {}).get("ok")
    models_ok = report.get("models_endpoint", {}).get("ok")
    if vision_ok is True or models_ok is True:
        report["status"] = "ok" if vision_ok is not False else "degraded"
    elif vision_ok is False or models_ok is False:
        report["status"] = "fail"
    else:
        report["status"] = report.get("status") or "unknown"
    return report


def main():
    configure_proxy_opener()
    parser = argparse.ArgumentParser(description="HelloMedia connectivity doctor")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print channel config summary without network calls",
    )
    parser.add_argument(
        "--vision-only",
        action="store_true",
        help="Only diagnose channels with vision:true",
    )
    parser.add_argument(
        "--video-only",
        action="store_true",
        help="Only diagnose channels with video:true",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Only diagnose channels with audio:true",
    )
    parser.add_argument(
        "--capabilities",
        action="store_true",
        help="Print machine-readable media parameter capabilities (no network, no keys)",
    )
    parser.add_argument(
        "--xai-network",
        action="store_true",
        help="Probe xAI api/imgen/vidgen connectivity (uses proxy if configured)",
    )
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="Probe OS clipboard image backends (no image dump; optional capture with --clipboard-capture)",
    )
    parser.add_argument(
        "--clipboard-capture",
        action="store_true",
        help="With --clipboard, also try capturing the current clipboard image",
    )
    args = parser.parse_args()

    if args.capabilities:
        print(json.dumps(capabilities_dict(), ensure_ascii=False, indent=2))
        return

    if args.clipboard or args.clipboard_capture:
        from _clipboard import capture_clipboard_image, probe_clipboard_backends

        report = {
            "ok": True,
            "clipboard": probe_clipboard_backends(),
        }
        if args.clipboard_capture:
            cap = capture_clipboard_image()
            report["capture"] = cap
            report["ok"] = bool(cap.get("ok"))
        else:
            report["ok"] = bool(report["clipboard"].get("any_backend"))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report.get("ok"):
            sys.exit(2)
        return

    if args.xai_network:
        report = check_xai_network(timeout=min(args.timeout, 10.0), use_cache=False)
        print(json.dumps({"ok": bool(report.get("ok")), "xai_network": report}, ensure_ascii=False, indent=2))
        if not report.get("ok"):
            sys.exit(2)
        return

    try:
        cfg, _ = load_config()
    except FileNotFoundError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    channels = cfg.get("channels") or []
    defaults = cfg.get("defaults") or {}
    results = []
    for ch in sorted(channels, key=lambda c: c.get("priority", 99)):
        if args.vision_only and not ch.get("vision"):
            continue
        if args.video_only and not ch.get("video"):
            continue
        if args.audio_only and not ch.get("audio"):
            continue
        name = ch.get("name", "?")
        mode = "dry-run" if args.dry_run else "live"
        eprint(f"[doctor] probing {name} ({mode})...")
        report = diagnose_channel(ch, args.timeout, probe_live=not args.dry_run)
        eprint(f"[doctor] {name}: status={report.get('status')}")
        results.append(report)

    fail_count = sum(1 for c in results if c.get("status") == "fail")
    warn_count = sum(1 for c in results if c.get("status") in ("warn", "degraded"))
    # ok=True means the doctor ran; overall_status reflects channel health
    if fail_count and not args.dry_run:
        overall = "fail"
    elif warn_count and not args.dry_run:
        overall = "degraded"
    elif args.dry_run:
        overall = "dry"
    else:
        overall = "ok"

    out = {
        "ok": overall != "fail",
        "overall_status": overall,
        "version": skill_version(),
        "skill_dir": str(SKILL_DIR),
        "defaults": defaults,
        "channel_count": len(results),
        "channels": results,
        "pillow_installed": _pillow_installed(),
        "proxy": proxy_summary(),
        "capabilities": {
            "vision": any(c.get("vision") for c in channels),
            "generate": any(c.get("generate") for c in channels),
            "video": any(c.get("video") for c in channels),
            "audio": any(c.get("audio") for c in channels),
        },
        "media_capabilities": capabilities_dict(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if not args.dry_run:
        vision_channels = [c for c in results if c.get("vision_enabled")]
        if vision_channels and all(c.get("status") == "fail" for c in vision_channels):
            sys.exit(2)
        if overall == "fail":
            sys.exit(2)


if __name__ == "__main__":
    main()
