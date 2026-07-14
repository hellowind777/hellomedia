#!/usr/bin/env python3
"""Shared helpers for HelloMedia scripts (stdlib only)."""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).parent.parent
RUNTIME_DIR = SKILL_DIR / ".runtime"

def _skill_version() -> str:
    try:
        return (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


USER_AGENT = f"hellomedia/{_skill_version()}"

RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
PERMANENT_4XX = {400, 401, 402, 403, 404, 405, 410, 413, 414, 415, 422}

UNSAFE_PATH_FRAGMENTS = (
    "Desktop", "Downloads", "Documents", "OneDrive", "Pictures",
    "Music", "Videos", "Public",
)


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, flush=True, **kwargs)


def load_config() -> tuple[dict[str, Any], dict[str, Any]]:
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json not found at {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return cfg, cfg.get("defaults") or {}


def load_channels(capability: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load channels that enable a capability flag (vision/generate/video/audio)."""
    cfg, defaults = load_config()
    channels = [c for c in cfg.get("channels", []) if c.get(capability)]
    channels.sort(key=lambda c: c.get("priority", 99))
    return channels, defaults


def normalize_path(p: str | None) -> str | None:
    if not p:
        return None
    return str(Path(p).expanduser().resolve()).replace("\\", "/")


def normalize_base_url(raw: str) -> str:
    url = (raw or "").rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url


def safe_output_path(output_path: str) -> tuple[bool, Path | None]:
    if output_path == "-":
        return True, None
    p = Path(output_path).expanduser().resolve()
    cwd = Path.cwd().resolve()
    runtime = RUNTIME_DIR.resolve()
    p_str = str(p)
    if p_str.startswith(str(cwd)) or p_str.startswith(str(runtime)):
        return True, p
    for frag in UNSAFE_PATH_FRAGMENTS:
        if frag.lower() in p_str.lower():
            return False, p
    return False, p


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def mime_for_path(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime
    ext = Path(path).suffix.lower().lstrip(".")
    return {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
        "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
        "ogg": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac",
    }.get(ext, "application/octet-stream")


def file_to_data_url(path: str, max_bytes: int | None = None) -> str:
    p = Path(path)
    raw = p.read_bytes()
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValueError(
            f"File too large for data URL ({len(raw)} bytes > {max_bytes}). "
            "Use a public URL or a smaller file."
        )
    import base64
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_for_path(str(p))};base64,{b64}"


def auth_headers(api_key: str, *, content_type: str | None = "application/json") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict | None = None,
    timeout: float = 120,
    retries: int = 2,
    label: str = "request",
) -> tuple[bool, Any]:
    """JSON request with transient retries. Returns (ok, data_or_error_dict)."""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    last_err: dict[str, Any] | None = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    return True, {}
                text = raw.decode("utf-8", errors="replace")
                try:
                    return True, json.loads(text)
                except json.JSONDecodeError:
                    return True, {"_raw": text, "_content_type": resp.headers.get("Content-Type")}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            last_err = {"error": f"HTTP {e.code}: {err_body}", "status": e.code}
            if e.code in PERMANENT_4XX:
                return False, last_err
            if e.code not in RETRY_STATUS_CODES or attempt >= retries + 1:
                return False, last_err
            delay = 2 ** (attempt - 1)
            if e.code == 429 and e.headers and e.headers.get("Retry-After"):
                try:
                    delay = max(delay, int(e.headers.get("Retry-After")))
                except ValueError:
                    pass
            eprint(f"[{label}] HTTP {e.code}, retry in {delay}s ({attempt}/{retries + 1})")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            last_err = {"error": str(e)}
            if attempt >= retries + 1:
                return False, last_err
            delay = 2 ** (attempt - 1)
            eprint(f"[{label}] network error, retry in {delay}s ({attempt}/{retries + 1})")
            time.sleep(delay)
    return False, last_err or {"error": "unknown"}


def http_bytes(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
    timeout: float = 120,
    retries: int = 2,
    label: str = "request",
) -> tuple[bool, bytes | dict[str, Any], dict[str, str]]:
    """Return (ok, body_or_error, response_headers)."""
    last_err: dict[str, Any] | None = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                hdrs = {k: v for k, v in resp.headers.items()}
                return True, raw, hdrs
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            last_err = {"error": f"HTTP {e.code}: {err_body}", "status": e.code}
            if e.code in PERMANENT_4XX or e.code not in RETRY_STATUS_CODES or attempt >= retries + 1:
                return False, last_err, {}
            delay = 2 ** (attempt - 1)
            eprint(f"[{label}] HTTP {e.code}, retry in {delay}s ({attempt}/{retries + 1})")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            last_err = {"error": str(e)}
            if attempt >= retries + 1:
                return False, last_err, {}
            delay = 2 ** (attempt - 1)
            eprint(f"[{label}] network error, retry in {delay}s ({attempt}/{retries + 1})")
            time.sleep(delay)
    return False, last_err or {"error": "unknown"}, {}


def download_url(url: str, dest: Path, timeout: float = 300) -> None:
    ensure_parent(dest)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())


def channel_creds(channel: dict[str, Any], kind: str) -> dict[str, str]:
    """Resolve base_url / api_key / model for vision|generate|video|audio."""
    if kind == "vision":
        return {
            "name": channel.get("name", "?"),
            "base_url": channel.get("base_url", ""),
            "api_key": channel.get("api_key", ""),
            "model": channel.get("model", ""),
            "api_format": channel.get("api_format", "openai"),
        }
    if kind == "generate":
        return {
            "name": channel.get("name", "?"),
            "base_url": channel.get("image_base_url") or channel.get("base_url", ""),
            "api_key": channel.get("image_api_key") or channel.get("api_key", ""),
            "model": channel.get("image_model") or channel.get("model", ""),
            "api_format": channel.get("api_format", "openai"),
        }
    if kind == "video":
        return {
            "name": channel.get("name", "?"),
            "base_url": channel.get("video_base_url") or channel.get("base_url", ""),
            "api_key": channel.get("video_api_key") or channel.get("api_key", ""),
            "model": channel.get("video_model") or "grok-imagine-video",
            "api_format": channel.get("api_format", "openai"),
        }
    if kind == "audio":
        return {
            "name": channel.get("name", "?"),
            "base_url": channel.get("audio_base_url") or channel.get("base_url", ""),
            "api_key": channel.get("audio_api_key") or channel.get("api_key", ""),
            "model": channel.get("audio_model") or "",
            "voice_id": channel.get("tts_voice") or "eve",
            "api_format": channel.get("api_format", "openai"),
        }
    raise ValueError(f"unknown kind: {kind}")


def is_xai_endpoint(base_url: str) -> bool:
    try:
        host = urlparse(base_url if "://" in base_url else f"https://{base_url}").netloc.lower()
    except Exception:
        host = ""
    return "x.ai" in host or host.endswith("api.x.ai")


def emit_json(obj: Any, output: str = "-") -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if output == "-":
        print(text)
        return
    safe, resolved = safe_output_path(output)
    if not safe or resolved is None:
        eprint(json.dumps({
            "error": f"Unsafe output path rejected: {output}. Use a path within the project directory."
        }, ensure_ascii=False))
        sys.exit(1)
    ensure_parent(resolved)
    resolved.write_text(text, encoding="utf-8")
    eprint(f"Saved to {resolved}")


def fail(obj: Any, code: int = 1) -> None:
    print(json.dumps(obj, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)
