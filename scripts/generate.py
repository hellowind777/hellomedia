#!/usr/bin/env python3
"""
HelloMedia — image generation engine.

Multi-endpoint fallback: responses → images(-edits) → chat; optional sd-webui.
Credential sources (first match wins per field where applicable):
  CLI flags → env → skill config.json generate channels → Codex/Hermes/OpenClaw runtime.
"""

import argparse
import base64
import json
import mimetypes
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

# Runtime auth discovery (Codex / Hermes / OpenClaw) — first-class skill module
try:
    from scripts import _auth_discovery as _auth  # type: ignore
except Exception:
    try:
        import _auth_discovery as _auth  # type: ignore
    except Exception:
        _auth = None  # type: ignore

# Ensure UTF-8 on Windows — must be at module level before any print() call
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
# Constants
# ============================================================================
SKILL_DIR = Path(__file__).parent.parent
RUNTIME_DIR = SKILL_DIR / ".runtime"

DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_IMAGES_MODEL = "gpt-image-2"
DEFAULT_RESPONSES_MODEL = "gpt-5"
DEFAULT_CHAT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
DEFAULT_FORMAT = "png"
DEFAULT_COUNT = 1
DEFAULT_AUTO_TIMEOUT = 360
MIN_TIMEOUT = 180
MAX_TIMEOUT = 600

def _skill_version() -> str:
    try:
        return (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


# Prefer shared browser UA (xAI imgen CDN); fall back if _common unavailable at import
try:
    from _common import resolve_media_user_agent as _resolve_media_ua  # type: ignore

    USER_AGENT = _resolve_media_ua()
except Exception:
    try:
        from scripts._common import resolve_media_user_agent as _resolve_media_ua  # type: ignore

        USER_AGENT = _resolve_media_ua()
    except Exception:
        USER_AGENT = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        )

RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
# 4xx errors that should never be retried (permanent failures)
PERMANENT_4XX = {400, 401, 402, 403, 404, 405, 410, 413, 414, 415, 422}
IMAGE_KEYS = ("b64_json", "result", "image_base64", "base64", "image", "data")
IMAGE_MAGIC = ("iVBOR", "/9j/", "UklGR", "R0lGOD", "Qk")

OPENAI_SIZE_LIMITS = {
    "2k": {"max_width": 1536, "max_height": 1536, "max_pixels": 2_359_296},
    "4k": {"max_width": 3840, "max_height": 3840, "max_pixels": 8_847_360},
}
# Semantic layout ratios (prompt-side). Keep in sync with media_caps image aspects + layout extras.
try:
    from media_caps import IMAGE_ASPECT_RATIOS as _CAPS_IMAGE_RATIOS  # type: ignore
except Exception:
    try:
        from scripts.media_caps import IMAGE_ASPECT_RATIOS as _CAPS_IMAGE_RATIOS  # type: ignore
    except Exception:
        _CAPS_IMAGE_RATIOS = (
            "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
            "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20", "auto",
        )
_LAYOUT_EXTRA_RATIOS = ("4:5", "5:4", "21:9")
SEMANTIC_RATIO_OPTIONS = tuple(
    dict.fromkeys(
        [r for r in _CAPS_IMAGE_RATIOS if r != "auto"] + list(_LAYOUT_EXTRA_RATIOS)
    )
)
DEFAULT_SEMANTIC_RATIO = "1:1"

ENDPOINT_PATH_SUFFIXES = {
    "responses":    "/responses",
    "chat":         "/chat/completions",
    "images":       "/images/generations",
    "images-edits": "/images/edits",
}
ALL_ENDPOINT_SUFFIXES = tuple(ENDPOINT_PATH_SUFFIXES.values())


# ============================================================================
# Helpers
# ============================================================================
class RequestFailure(RuntimeError):
    def __init__(self, message, *, status=None, attempts=0):
        super().__init__(message)
        self.status = status
        self.attempts = attempts


def _progress(msg, *, verbose):
    if verbose:
        print(f"[generate] {msg}", file=sys.stderr, flush=True)


def _looks_like_base64(v):
    if not isinstance(v, str):
        return False
    return v.startswith("data:image/") or (len(v) > 1000 and v.startswith(IMAGE_MAGIC))


def _looks_like_remote(v):
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def _extract_image_source(payload):
    """Recursively extract (kind, value) of first image found."""
    if isinstance(payload, list):
        for item in payload:
            found = _extract_image_source(item)
            if found:
                return found
        return None
    if isinstance(payload, dict):
        for key in IMAGE_KEYS:
            val = payload.get(key)
            if _looks_like_base64(val):
                return ("b64", val)
        url_val = payload.get("url")
        if _looks_like_remote(url_val):
            return ("url", url_val)
        for val in payload.values():
            found = _extract_image_source(val)
            if found:
                return found
        return None
    if _looks_like_base64(payload):
        return ("b64", payload)
    if _looks_like_remote(payload):
        return ("url", payload)
    return None


def _decode_image_bytes(source, timeout, api_key=None, base_url=None):
    """Fetch image bytes from b64 or remote URL (browser UA for xAI CDN)."""
    kind, value = source
    if kind == "b64":
        encoded = value.split(",", 1)[1] if value.startswith("data:image/") else value
        return base64.b64decode(encoded)
    # Prefer shared download helper (chunked + UA + optional same-host auth)
    try:
        from _common import download_url as _dl, resolve_media_user_agent as _rua
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="hm-img-")) / "dl.bin"
        try:
            _dl(
                value,
                tmp,
                timeout=float(timeout or 120),
                api_key=api_key,
                base_url=base_url,
            )
            return tmp.read_bytes()
        finally:
            try:
                tmp.unlink(missing_ok=True)
                tmp.parent.rmdir()
            except OSError:
                pass
    except Exception:
        pass
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    req = urllib.request.Request(value, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


_MAX_REF_IMAGE_BYTES = 20 * 1024 * 1024


def _image_to_data_url(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Reference image not found: {p}")
    try:
        from _common import file_to_data_url as _ftd
        return _ftd(str(p), max_bytes=_MAX_REF_IMAGE_BYTES)
    except ImportError:
        pass
    try:
        size = p.stat().st_size
    except OSError as e:
        raise ValueError(f"Cannot read reference image: {p}: {e}") from e
    if size > _MAX_REF_IMAGE_BYTES:
        raise ValueError(
            f"Reference image too large ({size} bytes > {_MAX_REF_IMAGE_BYTES})"
        )
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _build_output_paths(output_arg, count, fmt):
    """Resolve output paths for 1..N images."""
    output_path = Path(output_arg).expanduser()
    if count == 1:
        return [output_path.resolve()]
    parent = output_path.parent if output_path.suffix else output_path
    stem = output_path.stem if output_path.suffix else output_path.name
    suffix = output_path.suffix or f".{fmt}"
    resolved_parent = parent.resolve()
    resolved_parent.mkdir(parents=True, exist_ok=True)
    return [(resolved_parent / f"{stem}-{index}{suffix}").resolve() for index in range(1, count + 1)]


def _validate_output_paths(paths):
    """Reject unsafe outputs using shared path rules (CWD / skill / .runtime)."""
    try:
        from _common import safe_output_path
    except ImportError:
        # Fallback if scripts/ not on path: still allow skill tree + cwd
        from pathlib import Path as _P
        skill = SKILL_DIR.resolve()
        runtime = RUNTIME_DIR.resolve()
        cwd = _P.cwd().resolve()

        def safe_output_path(output_path):
            p = _P(output_path).expanduser().resolve()
            for root in (cwd, runtime, skill):
                try:
                    p.relative_to(root)
                    return True, p
                except ValueError:
                    continue
            return False, p

    rejected = []
    for p in paths:
        ok, _ = safe_output_path(str(p))
        if not ok:
            rejected.append(str(p))
    return len(rejected) == 0, rejected


def _is_official_openai(base_url):
    parsed = urlparse(base_url.rstrip("/"))
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "api.openai.com" and (
        parsed.path in {"", "/"}
    )


# ============================================================================
# SSE parsing
# ============================================================================
def _iter_sse_events(response):
    buffer = ""
    event_name = None
    data_lines = []

    def emit():
        if not data_lines:
            return None
        return event_name, "\n".join(data_lines)

    while True:
        chunk = response.read(8192)
        if not chunk:
            item = emit()
            if item:
                yield item
            break
        buffer += chunk.decode("utf-8", errors="replace")
        lines = buffer.splitlines(keepends=True)
        if lines and not (lines[-1].endswith("\n") or lines[-1].endswith("\r")):
            buffer = lines.pop()
        else:
            buffer = ""
        for raw_line in lines:
            line = raw_line.rstrip("\r\n")
            if not line:
                item = emit()
                if item:
                    yield item
                event_name = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())


def _iter_sse_json(response):
    for _ev, data in _iter_sse_events(response):
        if data == "[DONE]":
            return
        if not data:
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


# ============================================================================
# URL normalisation
# ============================================================================
def _strip_endpoint_suffixes(path):
    normalized = re.sub(r"/+$", "", path or "")
    changed = True
    while changed and normalized:
        changed = False
        lowered = normalized.lower()
        for suffix in ALL_ENDPOINT_SUFFIXES:
            if lowered.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
                break
        if normalized.lower().endswith("/v1"):
            normalized = normalized[:-3]
            changed = True
    return normalized.rstrip("/")


def _normalize_base_url(value):
    raw = (value or DEFAULT_BASE_URL).strip()
    if not raw.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    parsed = urlparse(raw)
    path = _strip_endpoint_suffixes(parsed.path)
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return urlunparse(normalized).rstrip("/")


def _build_endpoint_urls(base_url, endpoint, auth=None):
    """Return ordered list of (style, url) variants to try.

    Uses style_hint / local-proxy awareness when auth context is present
    (full Codex/local-relay path probing).
    """
    auth = auth or {}
    # Prefer full variant builder when auth discovery is available
    if _auth is not None:
        try:
            preferred_style = auth.get("endpoint_style") or auth.get("endpoint_style_hint")
            allow_plain = bool(
                auth.get("is_local_codex_proxy")
                or auth.get("endpoint_style_hint") == "plain"
                or (_auth.is_localish_base_url(base_url) if hasattr(_auth, "is_localish_base_url") else False)
            )
            return _auth.build_endpoint_url_variants(
                base_url,
                endpoint,
                style_hint=preferred_style if isinstance(preferred_style, str) else None,
                allow_plain_variant=allow_plain,
            )
        except Exception:
            pass

    suffix = ENDPOINT_PATH_SUFFIXES[endpoint]
    parsed = urlparse(base_url.rstrip("/"))
    root_path = _strip_endpoint_suffixes(parsed.path)
    v1_path = f"{root_path}/v1{suffix}"
    plain_path = f"{root_path}{suffix}"

    variants = []
    if _is_official_openai(base_url):
        variants.append(("v1", urlunparse(parsed._replace(path=v1_path, params="", query="", fragment=""))))
    else:
        variants.append(("v1", urlunparse(parsed._replace(path=v1_path, params="", query="", fragment=""))))
        if plain_path != v1_path:
            variants.append(("plain", urlunparse(parsed._replace(path=plain_path, params="", query="", fragment=""))))
    return variants


# ============================================================================
# Size resolution
# ============================================================================
def _parse_ratio(prompt):
    for pat in (
        r"(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)\s*(?:ratio|aspect\s*ratio|比例)?",
        r"(?:ratio|aspect\s*ratio|比例)[^\d]{0,6}(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)",
    ):
        m = re.search(pat, prompt, re.IGNORECASE)
        if m:
            lv, rv = float(m.group(1)), float(m.group(2))
            if lv > 0 and rv > 0:
                return lv, rv
    return None


def _parse_explicit_size(prompt):
    m = re.search(r"(\d{3,5})\s*[xX×]\s*(\d{3,5})", prompt)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _orientation_from_ratio(ratio_str):
    left, right = ratio_str.split(":", 1)
    lv, rv = float(left), float(right)
    if abs(lv - rv) < 0.08:
        return "square"
    return "landscape" if lv > rv else "portrait"


def _format_size(size):
    return f"{size[0]}x{size[1]}"


def _constrain_size(size, max_resolution):
    w, h = size
    limit = OPENAI_SIZE_LIMITS[max_resolution]
    ratio = w / h
    if ratio > 3 or ratio < 1 / 3:
        raise ValueError(f"Aspect ratio {ratio:.2f}:1 exceeds 3:1 limit")
    scale = min(limit["max_width"] / w, limit["max_height"] / h, 1.0)
    w = max(512, int(w * scale))
    h = max(512, int(h * scale))
    if w * h > limit["max_pixels"]:
        pixel_scale = (limit["max_pixels"] / (w * h)) ** 0.5
        w = int(w * pixel_scale)
        h = int(h * pixel_scale)
    w = max(512, w - (w % 16))
    h = max(512, h - (h % 16))
    return w, h


def _complexity_from_length(prompt):
    tokens = len(re.findall(r"\S+", prompt))
    if tokens >= 90:
        return "high"
    if tokens >= 35:
        return "medium"
    return "low"


def _extract_first_json_object(raw):
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _extract_text_blocks(payload):
    """Extract text strings from various API response shapes."""
    blocks = []
    if isinstance(payload, dict):
        if isinstance(payload.get("output_text"), str):
            blocks.append(payload["output_text"])
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    content = item.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and isinstance(block.get("text"), str):
                                blocks.append(block["text"])
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                msg = choice.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        blocks.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and isinstance(block.get("text"), str):
                                blocks.append(block["text"])
    return blocks


def _analyze_layout(prompt, base_url, api_key, model, verbose):
    """Lightweight LLM call to determine the best canvas ratio for a prompt.
    Returns {"ratio":..., "confidence":..., "reason":...} or None on failure.
    """
    if not api_key:
        return None
    ratios = ", ".join(SEMANTIC_RATIO_OPTIONS)
    analysis_prompt = (
        "You analyze image-generation prompts and choose the most suitable canvas ratio.\n"
        "Return JSON only with keys: ratio, confidence, reason.\n"
        f"Allowed ratio values: {ratios}.\n"
        "Rules:\n"
        "1. Prefer what best preserves subject composition and scene readability.\n"
        "2. Use portrait for single standing full-body characters, fashion looks, vertical posters.\n"
        "3. Use landscape for wide scenes, environments, multi-subject horizontal action, panoramas.\n"
        "4. Use square when the prompt is ambiguous or balanced.\n"
        "5. confidence must be a number from 0 to 1.\n"
        "6. Keep reason under 18 words.\n"
        f"Prompt:\n{prompt}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    # Try chat API first (most compatible), then responses
    for endpoint in ("chat", "responses"):
        # Use v1 path only for this lightweight call
        parsed = urlparse(base_url.rstrip("/"))
        root_path = _strip_endpoint_suffixes(parsed.path)
        suffix = ENDPOINT_PATH_SUFFIXES[endpoint]
        url = urlunparse(parsed._replace(path=f"{root_path}/v1{suffix}", params="", query="", fragment=""))

        payload: dict[str, Any]
        if endpoint == "responses":
            payload = {
                "model": model,
                "input": [{"role": "user", "content": analysis_prompt}],
                "stream": False,
            }
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": analysis_prompt}],
            }

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            continue

        for block in _extract_text_blocks(data):
            parsed_block = _extract_first_json_object(block)
            if not parsed_block:
                continue
            ratio = parsed_block.get("ratio")
            confidence = parsed_block.get("confidence")
            reason = parsed_block.get("reason")
            if ratio not in SEMANTIC_RATIO_OPTIONS:
                continue
            try:
                conf_val = float(confidence)
            except (TypeError, ValueError):
                continue
            if conf_val < 0 or conf_val > 1:
                continue
            _progress(f"layout analysis: ratio={ratio} confidence={conf_val:.2f} reason={reason}", verbose=verbose)
            return {"ratio": ratio, "confidence": conf_val, "reason": str(reason or "").strip()}
    return None


def resolve_size(prompt, explicit_size, max_resolution,
                 base_url=None, api_key=None, model=None,
                 layout_analysis=True, layout_min_confidence=0.65, verbose=False):
    """Determine output size from prompt heuristics + optional semantic analysis."""
    # 1) Explicit size in prompt (e.g. "1024x1536")
    parsed_explicit = _parse_explicit_size(prompt)
    if parsed_explicit:
        constrained = _constrain_size(parsed_explicit, max_resolution)
        return _format_size(constrained), {
            "source": "prompt-explicit",
            "requested_size": _format_size(parsed_explicit),
            "orientation": _orientation_from_ratio(f"{parsed_explicit[0]}:{parsed_explicit[1]}"),
            "complexity": _complexity_from_length(prompt),
            "layout_reason": "prompt explicit size",
        }

    # 2) Explicit ratio in prompt (e.g. "16:9 ratio")
    requested_ratio = _parse_ratio(prompt)
    complexity = _complexity_from_length(prompt)
    limit = OPENAI_SIZE_LIMITS[max_resolution]

    if requested_ratio is not None:
        ratio_val = requested_ratio[0] / requested_ratio[1]
        orientation = _orientation_from_ratio(f"{requested_ratio[0]}:{requested_ratio[1]}")
        source = "prompt-ratio"
        layout_reason = "prompt explicit ratio"
        semantic = None
    elif layout_analysis:
        semantic = _analyze_layout(prompt, base_url, api_key, model, verbose)
        if semantic and semantic["confidence"] >= layout_min_confidence:
            ratio_pair = tuple(float(x) for x in semantic["ratio"].split(":", 1))
            ratio_val = ratio_pair[0] / ratio_pair[1]
            orientation = _orientation_from_ratio(semantic["ratio"])
            source = "semantic-layout"
            layout_reason = semantic["reason"] or "semantic analysis"
        else:
            ratio_val = 1.0
            orientation = "square"
            source = "default-square"
            layout_reason = "default square fallback"
    else:
        ratio_val = 1.0
        orientation = "square"
        source = "default-square"
        layout_reason = "default square (layout analysis disabled)"
        semantic = None

    # 3) Scale by complexity
    if complexity == "low":
        base_pixels = min(limit["max_pixels"], 1_048_576)
    elif complexity == "medium":
        base_pixels = min(limit["max_pixels"], 1_572_864 if max_resolution == "2k" else 4_194_304)
    else:
        base_pixels = limit["max_pixels"]

    w = int((base_pixels * ratio_val) ** 0.5)
    h = int(base_pixels / max(w, 1))
    constrained = _constrain_size((w, h), max_resolution)

    meta = {
        "source": source,
        "orientation": orientation,
        "complexity": complexity,
        "layout_reason": layout_reason,
    }
    if semantic:
        meta["semantic_ratio"] = semantic["ratio"]
        meta["semantic_confidence"] = semantic["confidence"]

    return _format_size(constrained), meta


def resolve_timeout(size_str, has_ref=False, override=None):
    if override is not None:
        return max(MIN_TIMEOUT, min(MAX_TIMEOUT, int(override)))
    m = re.match(r"(\d+)x(\d+)", size_str)
    if not m:
        return DEFAULT_AUTO_TIMEOUT
    pixels = int(m.group(1)) * int(m.group(2))
    # gpt-image-2 real-world latency: 1024x1024 medium ~80s, high ~195s
    # Add 60-90s headroom for relay proxy/gateway/CDN overhead
    if pixels <= 1_200_000:
        t = 220   # was 180 — too tight for 1024x1024 through relay
    elif pixels <= 2_400_000:
        t = 300   # was 240
    elif pixels <= 4_500_000:
        t = 420   # was 360
    else:
        t = 600   # 4K ceiling
    if has_ref:
        t += 60
    return min(MAX_TIMEOUT, max(MIN_TIMEOUT, t))


def choose_quality(size_str, user_quality):
    if user_quality != "auto":
        return user_quality
    m = re.match(r"(\d+)x(\d+)", size_str)
    if not m:
        return "medium"
    pixels = int(m.group(1)) * int(m.group(2))
    return "high" if pixels >= 4_000_000 else "medium"


def normalize_resolution(value):
    if not value:
        return "2k"
    aliases = {"2k": "2k", "1536": "2k", "2048": "2k", "4k": "4k", "3840": "4k"}
    v = value.strip().lower()
    if v in aliases:
        return aliases[v]
    raise ValueError(f"--max-resolution must be 2k or 4k, got: {value}")


# ============================================================================
# HTTP helpers
# ============================================================================
def _request_headers(api_key, auth=None):
    """Build request headers; attach Codex attribution when auth context needs it."""
    if auth and _auth is not None and (
        auth.get("auth_mode") in {"codex-oauth", "codex-agent-identity"}
        or auth.get("is_codex_backend")
        or auth.get("is_local_codex_proxy")
    ):
        try:
            return _auth.request_headers(auth)
        except Exception:
            pass
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def _post_json(url, payload, headers, timeout):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _build_multipart_body(fields, files):
    boundary = f"----generate-{random.randint(100000, 999999)}-{int(time.time() * 1000)}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, path in files:
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode("utf-8"))
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), boundary


def _post_multipart(url, fields, files, headers, timeout):
    body, boundary = _build_multipart_body(fields, files)
    mp_headers = dict(headers)
    mp_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers=mp_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ============================================================================
# Cooldown
# ============================================================================
def _maybe_cooldown(seconds, verbose):
    if seconds <= 0:
        return
    stamp_path = RUNTIME_DIR / "last_request_at.txt"
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        last = float(stamp_path.read_text(encoding="utf-8").strip())
    except Exception:
        last = 0.0
    remaining = seconds - (time.time() - last)
    if remaining > 0:
        _progress(f"cooldown {remaining:.2f}s before next request", verbose=verbose)
        time.sleep(remaining)
    stamp_path.write_text(str(time.time()), encoding="utf-8")


def _backoff_sleep(attempt, base_delay, label, verbose):
    delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.35)
    _progress(f"{label}: waiting {delay:.2f}s before retry", verbose=verbose)
    time.sleep(delay)


def _run_with_retries(label, func, max_attempts, base_delay, cooldown, verbose):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        _maybe_cooldown(cooldown, verbose)
        _progress(f"{label}: attempt {attempt}/{max_attempts}", verbose=verbose)
        try:
            result = func()
            _progress(f"{label}: success on attempt {attempt}", verbose=verbose)
            return result, attempt
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            last_error = RequestFailure(
                f"{label} failed HTTP {exc.code}: {detail}",
                status=exc.code, attempts=attempt,
            )
            _progress(f"{label}: HTTP {exc.code}", verbose=verbose)
            # Never retry permanent 4xx (400, 401, 402, 403, 404, 405, 410, 413, 414, 415, 422)
            if exc.code in PERMANENT_4XX:
                raise last_error
            # For 429, check Retry-After header for the backoff seed
            if exc.code == 429:
                retry_after = exc.headers.get('Retry-After') if hasattr(exc, 'headers') else None
                if retry_after:
                    try:
                        delay = int(retry_after)
                    except ValueError:
                        delay = None
                    if delay:
                        _progress(f"{label}: rate limited, Retry-After={delay}s", verbose=verbose)
                        time.sleep(delay)
                        continue  # Don't count as attempt, try immediately after delay
            # Only retry on transient errors: 408, 409, 425, 429, 5xx
            if exc.code not in RETRY_STATUS_CODES or attempt == max_attempts:
                raise last_error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = RequestFailure(f"{label} network error: {exc}", attempts=attempt)
            _progress(f"{label}: network error", verbose=verbose)
            # Network errors on 200s+ latency providers are often mid-link timeouts
            # (proxy/CDN/gateway dropping the connection before OpenAI finishes).
            # Retry with backoff but log clearly so user can tune --timeout up.
            if attempt == max_attempts:
                raise last_error
        except json.JSONDecodeError as exc:
            last_error = RequestFailure(f"{label} invalid JSON: {exc}", attempts=attempt)
            _progress(f"{label}: invalid JSON", verbose=verbose)
            if attempt == max_attempts:
                raise last_error
        if attempt < max_attempts:
            _backoff_sleep(attempt, base_delay, label, verbose)
    if last_error:
        raise last_error
    raise RequestFailure(f"{label} failed", attempts=max_attempts)


# ============================================================================
# Endpoint handlers — each tries URL variants (v1 → plain)
# ============================================================================
def _is_xai_api_format(auth=None, api_format=None):
    fmt = (api_format or (auth or {}).get("api_format") or "").lower()
    return fmt == "xai"


def _size_to_xai_resolution(size: str | None) -> str:
    """Map OpenAI-style size to xAI/Sub2API resolution 1k|2k."""
    if not size or size == "auto":
        return "1k"
    m = re.match(r"(\d+)x(\d+)", str(size))
    if not m:
        s = str(size).lower()
        if s in ("1k", "2k"):
            return s
        return "1k"
    pixels = int(m.group(1)) * int(m.group(2))
    return "2k" if pixels > 1_200_000 else "1k"


def _size_to_aspect_ratio(size: str | None) -> str | None:
    if not size or size == "auto":
        return None
    m = re.match(r"(\d+)x(\d+)", str(size))
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        return None
    # Reduce to small integer ratio when obvious
    from math import gcd
    g = gcd(w, h)
    a, b = w // g, h // g
    # Prefer common Grok ratios
    ratio = f"{a}:{b}"
    common = {
        "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
        "2:1", "1:2", "21:9", "4:5", "5:4",
    }
    if ratio in common:
        return ratio
    # Approximate
    target = w / h
    best, best_d = "1:1", 1e9
    for r in common:
        aa, bb = r.split(":")
        d = abs(float(aa) / float(bb) - target)
        if d < best_d:
            best, best_d = r, d
    return best


def _request_via_images(base_url, api_key, model, prompt, size, quality, fmt,
                        timeout, max_attempts, base_delay, cooldown, verbose, trace,
                        seed=None, thinking=None, auth=None, api_format=None):
    """POST /v1/images/generations — xAI/Sub2API or OpenAI-style payloads."""
    headers = _request_headers(api_key, auth=auth)
    urls = _build_endpoint_urls(base_url, "images", auth=auth)
    last_exc = None
    xai_mode = _is_xai_api_format(auth=auth, api_format=api_format) or (
        "x.ai" in (base_url or "").lower()
    )

    for style, url in urls:
        def _try(payload):
            def call():
                return _post_json(url, payload, headers, timeout)
            result, attempts = _run_with_retries(
                "images", call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("images API returned no image payload", attempts=attempts)
            return _decode_image_bytes(src, timeout, api_key=api_key, base_url=base_url), attempts

        # --- xAI / Sub2API: aspect_ratio + resolution (happy-loki/grok-media-skill) ---
        if xai_mode:
            xai_payload = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "resolution": _size_to_xai_resolution(size),
            }
            ar = _size_to_aspect_ratio(size)
            if ar:
                xai_payload["aspect_ratio"] = ar
            try:
                image_bytes, attempts = _try(xai_payload)
                trace.append({
                    "endpoint": "images", "variant": "xai-aspect", "route": style,
                    "attempts": attempts, "status": "success",
                })
                return image_bytes, attempts, False
            except RequestFailure as exc:
                trace.append({
                    "endpoint": "images", "variant": "xai-aspect", "route": style,
                    "attempts": exc.attempts, "status": "failed", "error": str(exc),
                })
                last_exc = exc
                # Fall through to OpenAI-style / minimal for hybrid relays
                _progress("xAI-style images payload failed, trying OpenAI-style", verbose=verbose)

        # Full OpenAI-compatible payload
        try:
            image_bytes, attempts = _try({
                "model": model, "prompt": prompt, "n": 1,
                "size": size, "quality": quality, "output_format": fmt,
                **({"seed": seed} if seed is not None else {}),
                **({"thinking": thinking} if thinking else {}),
            })
            trace.append({"endpoint": "images", "variant": "full", "route": style,
                          "attempts": attempts, "status": "success"})
            return image_bytes, attempts, False
        except RequestFailure as exc:
            trace.append({"endpoint": "images", "variant": "full", "route": style,
                          "attempts": exc.attempts, "status": "failed", "error": str(exc)})
            if exc.status not in {400, 404, 405, 415, 422, None} and not xai_mode:
                # Permanent client errors only skip when not xAI hybrid
                if exc.status and exc.status < 500 and exc.status not in RETRY_STATUS_CODES:
                    if exc.status not in {400, 404, 405, 415, 422}:
                        raise
            last_exc = exc
            _progress("images rich payload rejected, trying minimal payload", verbose=verbose)

        # Minimal fallback
        try:
            image_bytes, attempts = _try({"model": model, "prompt": prompt, "n": 1})
            trace.append({"endpoint": "images", "variant": "minimal", "route": style,
                          "attempts": attempts, "status": "success"})
            return image_bytes, attempts, True
        except RequestFailure as exc2:
            trace.append({"endpoint": "images", "variant": "minimal", "route": style,
                          "attempts": exc2.attempts, "status": "failed", "error": str(exc2)})
            last_exc = exc2
            _progress(f"images route '{style}' failed, trying next URL variant", verbose=verbose)

    raise last_exc or RequestFailure("images API failed before any request was sent")


def _request_via_images_edits(base_url, api_key, model, prompt, image_refs, size, quality, fmt,
                              timeout, max_attempts, base_delay, cooldown, verbose, trace,
                              seed=None, thinking=None, auth=None):
    """POST /v1/images/edits — multipart → JSON fallback."""
    headers = _request_headers(api_key, auth=auth)
    urls = _build_endpoint_urls(base_url, "images-edits", auth=auth)
    last_exc = None
    ref_paths = [Path(p).expanduser() for p in image_refs]

    for style, url in urls:
        # Multipart
        fields = [
            ("model", model), ("prompt", prompt), ("n", "1"),
            ("size", size), ("quality", quality), ("output_format", fmt),
        ]
        files = [("image[]", p) for p in ref_paths]

        try:
            def mp_call():
                return _post_multipart(url, fields, files, headers, timeout)
            result, attempts = _run_with_retries(
                "images-edits(mp)", mp_call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("images-edits returned no image", attempts=attempts)
            trace.append({"endpoint": "images-edits", "variant": "multipart", "route": style,
                          "attempts": attempts, "status": "success"})
            return _decode_image_bytes(src, timeout), attempts, False
        except RequestFailure as exc:
            trace.append({"endpoint": "images-edits", "variant": "multipart", "route": style,
                          "attempts": exc.attempts, "status": "failed", "error": str(exc)})
            if exc.status not in {400, 404, 405, 415, 422}:
                raise
            last_exc = exc
            _progress("images-edits multipart rejected, trying JSON payload", verbose=verbose)

        # JSON fallback
        try:
            data_urls = [_image_to_data_url(str(p)) for p in ref_paths]
            def json_call():
                return _post_json(url, {
                    "model": model, "prompt": prompt, "n": 1,
                    "images": [{"image_url": u} for u in data_urls],
                    "size": size, "quality": quality, "output_format": fmt,
                }, headers, timeout)
            result, attempts = _run_with_retries(
                "images-edits(json)", json_call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("images-edits JSON returned no image", attempts=attempts)
            trace.append({"endpoint": "images-edits", "variant": "json", "route": style,
                          "attempts": attempts, "status": "success"})
            return _decode_image_bytes(src, timeout), attempts, True
        except RequestFailure as exc2:
            trace.append({"endpoint": "images-edits", "variant": "json", "route": style,
                          "attempts": exc2.attempts, "status": "failed", "error": str(exc2)})
            last_exc = exc2
            _progress(f"images-edits route '{style}' failed, trying next URL variant", verbose=verbose)

    raise last_exc or RequestFailure("images-edits API failed before any request was sent")


def _request_via_responses(base_url, api_key, model, prompt, image_refs, size, quality, fmt,
                           timeout, max_attempts, base_delay, cooldown, verbose,
                           responses_mode, trace, seed=None, thinking=None, auth=None):
    """POST /v1/responses with image_generation tool. SSE → JSON fallback."""
    headers = _request_headers(api_key, auth=auth)
    urls = _build_endpoint_urls(base_url, "responses", auth=auth)
    last_exc = None

    tool: dict[str, Any] = {"type": "image_generation", "size": size,
                            "quality": quality, "output_format": fmt}
    if image_refs:
        tool["action"] = "edit"
        content = [{"type": "input_image", "image_url": _image_to_data_url(p)} for p in image_refs]
        content.append({"type": "input_text", "text": prompt})
        input_block = [{"role": "user", "content": content}]
    else:
        input_block = [{"role": "user", "content": prompt}]

    for style, url in urls:
        # Stream attempt (if enabled)
        if responses_mode in ("stream", "auto"):
            try:
                def stream_call():
                    body = json.dumps({
                        "model": model, "input": input_block,
                        "tools": [tool], "tool_choice": "auto",
                        "stream": True,
                    }).encode("utf-8")
                    sh = dict(headers)
                    sh["Accept"] = "text/event-stream"
                    req = urllib.request.Request(url, data=body, headers=sh, method="POST")
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        ct = resp.headers.get("content-type", "")
                        if "text/event-stream" not in ct:
                            data = json.loads(resp.read().decode("utf-8", errors="replace"))
                            src = _extract_image_source(data)
                            if not src:
                                raise RequestFailure("responses stream fallback returned no image")
                            return _decode_image_bytes(src, timeout), "stream-json"
                        for event in _iter_sse_json(resp):
                            src = _extract_image_source(event)
                            if src:
                                return _decode_image_bytes(src, timeout), "stream"
                    raise RequestFailure("responses stream returned no image data")

                result, attempts = _run_with_retries(
                    "responses(stream)", stream_call, max_attempts, base_delay, cooldown, verbose)
                image_bytes, mode = result
                trace.append({"endpoint": "responses", "variant": mode, "route": style,
                              "attempts": attempts, "status": "success"})
                return image_bytes, attempts, mode
            except RequestFailure as exc:
                trace.append({"endpoint": "responses", "variant": "stream", "route": style,
                              "attempts": exc.attempts, "status": "failed", "error": str(exc)})
                last_exc = exc
                if responses_mode == "stream":
                    _progress(f"responses stream route '{style}' failed", verbose=verbose)
                    continue
                _progress("responses stream failed, trying JSON mode", verbose=verbose)

        # JSON fallback
        try:
            def json_call():
                # Also fix the JSON fallback payload
                return _post_json(url, {
                    "model": model, "input": input_block,
                    "tools": [tool], "tool_choice": "auto",
                    "stream": False,
                }, headers, timeout)
            result, attempts = _run_with_retries(
                "responses(json)", json_call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("responses JSON returned no image", attempts=attempts)
            trace.append({"endpoint": "responses", "variant": "json", "route": style,
                          "attempts": attempts, "status": "success"})
            return _decode_image_bytes(src, timeout), attempts, "json"
        except RequestFailure as exc2:
            trace.append({"endpoint": "responses", "variant": "json", "route": style,
                          "attempts": exc2.attempts, "status": "failed", "error": str(exc2)})
            last_exc = exc2
            _progress(f"responses route '{style}' failed, trying next URL variant", verbose=verbose)

    raise last_exc or RequestFailure("responses API failed before any request was sent")


def _request_via_chat(base_url, api_key, model, prompt, image_refs, size, quality, fmt,
                      timeout, max_attempts, base_delay, cooldown, verbose, trace,
                      seed=None, thinking=None, auth=None):
    """POST /v1/chat/completions — compat → legacy payload fallback."""
    headers = _request_headers(api_key, auth=auth)
    urls = _build_endpoint_urls(base_url, "chat", auth=auth)
    last_exc = None

    for style, url in urls:
        # Compat payload
        if image_refs:
            content = [{"type": "text", "text": prompt}]
            content.extend({"type": "image_url", "image_url": {"url": _image_to_data_url(p)}}
                           for p in image_refs)
        else:
            content = prompt

        try:
            def call():
                return _post_json(url, {
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "modalities": ["text", "image"],
                    "image": {"size": size, "quality": quality, "format": fmt},
                }, headers, timeout)
            result, attempts = _run_with_retries(
                "chat", call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("chat API returned no image", attempts=attempts)
            trace.append({"endpoint": "chat", "variant": "compat", "route": style,
                          "attempts": attempts, "status": "success"})
            return _decode_image_bytes(src, timeout), attempts, False
        except RequestFailure as exc:
            trace.append({"endpoint": "chat", "variant": "compat", "route": style,
                          "attempts": exc.attempts, "status": "failed", "error": str(exc)})
            if exc.status not in {400, 404, 405, 415, 422}:
                raise
            last_exc = exc
            _progress("chat compat payload rejected, trying legacy", verbose=verbose)

        # Legacy payload
        try:
            if image_refs:
                legacy_content = [{"type": "input_text", "text": prompt}]
                legacy_content.extend({"type": "input_image", "image_url": _image_to_data_url(p)}
                                      for p in image_refs)
            else:
                legacy_content = prompt

            def legacy_call():
                return _post_json(url, {
                    "model": model,
                    "messages": [{"role": "user", "content": legacy_content}],
                    "modalities": ["text", "image"],
                    "size": size, "quality": quality, "output_format": fmt,
                }, headers, timeout)
            result, attempts = _run_with_retries(
                "chat(legacy)", legacy_call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("chat legacy returned no image", attempts=attempts)
            trace.append({"endpoint": "chat", "variant": "legacy", "route": style,
                          "attempts": attempts, "status": "success"})
            return _decode_image_bytes(src, timeout), attempts, True
        except RequestFailure as exc2:
            trace.append({"endpoint": "chat", "variant": "legacy", "route": style,
                          "attempts": exc2.attempts, "status": "failed", "error": str(exc2)})
            last_exc = exc2
            _progress(f"chat route '{style}' failed, trying next URL variant", verbose=verbose)

    raise last_exc or RequestFailure("chat API failed before any request was sent")


# ============================================================================
# SD WebUI (A1111) handler
# ============================================================================
def _request_via_sd_webui(base_url, prompt, image_refs, size, steps, cfg_scale,
                          sampler, timeout, verbose):
    """POST /sdapi/v1/txt2img or /sdapi/v1/img2img (Stable Diffusion WebUI)."""
    m = re.match(r"(\d+)x(\d+)", size)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)

    if image_refs:
        endpoint = "/sdapi/v1/img2img"
        ref_path = Path(image_refs[0]).expanduser()
        ref_b64 = base64.b64encode(ref_path.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "init_images": [ref_b64],
            "prompt": prompt,
            "denoising_strength": 0.6,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": w,
            "height": h,
            "sampler_name": sampler,
            "seed": -1,
        }
    else:
        endpoint = "/sdapi/v1/txt2img"
        payload = {
            "prompt": prompt,
            "negative_prompt": "",
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": w,
            "height": h,
            "sampler_name": sampler,
            "seed": -1,
        }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    url = base_url.rstrip("/") + endpoint
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    images = data.get("images", [])
    if not images:
        raise RequestFailure("SD WebUI returned no images")
    return base64.b64decode(images[0]), 1, endpoint.split("/")[-1]


def _request_via_fal(base_url, api_key, prompt, image_refs, size, timeout, verbose):
    """Minimal fal.run / fal.queue-style image generation.

    Expects base_url to be the full model endpoint (e.g. https://fal.run/fal-ai/...).
    Auth: Authorization: Key <api_key>
    """
    m = re.match(r"(\d+)x(\d+)", size or "")
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)
    payload: dict[str, Any] = {
        "prompt": prompt,
        "image_size": {"width": w, "height": h},
        "num_images": 1,
        "output_format": "png",
    }
    if image_refs:
        # common edit pattern: pass first ref as image_url data URL
        ref = Path(image_refs[0]).expanduser()
        b64 = base64.b64encode(ref.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(str(ref))[0] or "image/png"
        payload["image_url"] = f"data:{mime};base64,{b64}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if api_key:
        # fal accepts "Key xxx" ; some relays still use Bearer
        headers["Authorization"] = f"Key {api_key}" if not api_key.lower().startswith("key ") else api_key

    url = (base_url or "").rstrip("/")
    if not url:
        raise RequestFailure("fal base_url is empty")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    _progress(f"fal POST {url}", verbose=verbose)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    # Response shapes: {images:[{url|file_data|content}]}, or nested data
    candidates = []
    if isinstance(data, dict):
        for key in ("images", "image", "output", "data"):
            val = data.get(key)
            if isinstance(val, list):
                candidates.extend(val)
            elif isinstance(val, dict):
                candidates.append(val)
            elif isinstance(val, str):
                candidates.append({"url": val})
    for item in candidates:
        if not isinstance(item, dict):
            if isinstance(item, str) and item.startswith(("http://", "https://", "data:")):
                src = ("url", item) if item.startswith("http") else ("b64", item.split(",", 1)[-1] if "," in item else item)
                return _decode_image_bytes(src, timeout), 1, "fal"
            continue
        for k in ("url", "image_url", "file_data", "content", "b64_json", "base64"):
            v = item.get(k)
            if not v:
                continue
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return _decode_image_bytes(("url", v), timeout), 1, "fal"
            if isinstance(v, str):
                raw = v.split(",", 1)[-1] if v.startswith("data:") else v
                return _decode_image_bytes(("b64", raw), timeout), 1, "fal"
    raise RequestFailure(f"fal returned no recognizable image payload: {json.dumps(data)[:300]}")


# ============================================================================
# Multi-endpoint orchestrator
# ============================================================================
def generate_image(base_url, api_key, images_model, responses_model, chat_model,
                   prompt, size, quality, fmt, timeout, max_attempts=3, base_delay=2.0,
                   cooldown=2.5, verbose=False, image_refs=None,
                   endpoint_mode="auto", responses_mode="auto", seed=None, thinking=None,
                   sd_steps=30, sd_cfg_scale=7.5, sd_sampler="DPM++ 2M Karras",
                   auth=None, api_format=None):
    """
    Generate one image through the optimal endpoint path.
    Returns (image_bytes, transport, total_attempts, trace).
    """
    trace: list[dict[str, Any]] = []
    is_openai = _is_official_openai(base_url)
    auth = auth or {}
    if api_format and not auth.get("api_format"):
        auth = {**auth, "api_format": api_format}
    wire_api = (auth.get("wire_api") or "").lower()
    is_local_proxy = bool(auth.get("is_local_codex_proxy"))
    is_codex_backend = bool(auth.get("is_codex_backend"))
    xai_like = _is_xai_api_format(auth=auth, api_format=api_format) or (
        "x.ai" in (base_url or "").lower()
    )
    prefer_responses = bool(
        wire_api == "responses" or is_local_proxy or is_codex_backend or is_openai
    ) and not xai_like
    allow_chat = (
        not is_openai
        and not is_codex_backend
        and not is_local_proxy
        and not xai_like
    )

    # ---- Specialized providers ----
    if endpoint_mode == "sd-webui":
        image_bytes, attempts, mode = _request_via_sd_webui(
            base_url, prompt, image_refs, size,
            sd_steps, sd_cfg_scale, sd_sampler, timeout, verbose)
        trace.append({"endpoint": f"sd-webui:{mode}", "attempts": attempts, "status": "success"})
        return image_bytes, f"sd-webui:{mode}", attempts, trace

    if endpoint_mode == "fal":
        image_bytes, attempts, mode = _request_via_fal(
            base_url, api_key, prompt, image_refs, size, timeout, verbose)
        trace.append({"endpoint": f"fal:{mode}", "attempts": attempts, "status": "success"})
        return image_bytes, f"fal:{mode}", attempts, trace

    # ---- Build ordered endpoint list (wire_api / local proxy awareness) ----
    # xAI / Sub2API Imagine: only /v1/images/generations (and edits), not responses/chat.
    if endpoint_mode == "images":
        order = ["images-edits" if image_refs else "images"]
    elif endpoint_mode == "responses":
        order = ["responses"]
    elif endpoint_mode == "chat":
        order = ["chat"]
    elif xai_like:
        order = ["images-edits" if image_refs else "images"]
    elif image_refs:
        order = ["responses", "images-edits"]
        if allow_chat:
            order.append("chat")
    elif prefer_responses:
        order = ["responses", "images"]
        if allow_chat:
            order.append("chat")
    else:
        order = ["images", "responses"]
        if allow_chat:
            order.append("chat")

    if endpoint_mode == "images" and not image_refs and "images-edits" in order:
        order.remove("images-edits")

    total_attempts = 0
    last_error = None

    for ep in order:
        try:
            if ep == "images":
                image_bytes, attempts, _ = _request_via_images(
                    base_url, api_key, images_model, prompt,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown, verbose, trace,
                    seed=seed, thinking=thinking, auth=auth, api_format=api_format)
                total_attempts += attempts
                return image_bytes, "images", total_attempts, trace

            elif ep == "images-edits":
                image_bytes, attempts, _ = _request_via_images_edits(
                    base_url, api_key, images_model, prompt, image_refs,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown, verbose, trace,
                    seed=seed, thinking=thinking, auth=auth)
                total_attempts += attempts
                return image_bytes, "images-edits", total_attempts, trace

            elif ep == "responses":
                image_bytes, attempts, mode = _request_via_responses(
                    base_url, api_key, responses_model, prompt, image_refs,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown,
                    verbose, responses_mode, trace, seed=seed, thinking=thinking, auth=auth)
                total_attempts += attempts
                return image_bytes, f"responses:{mode}", total_attempts, trace

            elif ep == "chat":
                image_bytes, attempts, _ = _request_via_chat(
                    base_url, api_key, chat_model, prompt, image_refs,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown, verbose, trace,
                    seed=seed, thinking=thinking, auth=auth)
                total_attempts += attempts
                return image_bytes, "chat", total_attempts, trace

        except RequestFailure as exc:
            total_attempts += exc.attempts or 0
            last_error = exc
            # Local Codex/OpenAI-auth proxy: fail fast on permission errors
            if is_local_proxy and exc.status in {401, 403}:
                raise
            # Stop on permission/auth failures for non-official endpoints
            if exc.status in {401, 402, 403} and not is_openai:
                raise
            # Do not burn chat fallback on local auth proxies
            if is_local_proxy and ep != "chat":
                raise
            trace.append({"endpoint": ep, "status": "fallback",
                          "attempts": exc.attempts, "error": str(exc)})
            _progress(f"{ep} failed, trying next endpoint", verbose=verbose)

    if last_error:
        raise last_error
    raise RequestFailure("All endpoints exhausted", attempts=total_attempts)


# ============================================================================
# Config
# ============================================================================
def load_channels():
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        # Allow pure runtime auth (Codex/env/CLI) without skill config.json
        return [], {}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    channels = [c for c in cfg.get("channels", []) if c.get("generate")]
    channels.sort(key=lambda c: c.get("priority", 99))
    return channels, cfg.get("defaults", {})


def resolve_channel_params(channel):
    """Resolve channel credentials without KeyError when model keys are omitted."""
    name = channel.get("name") or "channel"
    base_url = channel.get("image_base_url") or channel.get("base_url") or ""
    api_key = channel.get("image_api_key") or channel.get("api_key") or ""
    fmt = (channel.get("api_format") or "openai").lower()
    raw_image = channel.get("image_model")
    raw_model = channel.get("model")
    # Prefer image_model; for sd-webui/fal allow blank model (path embeds model)
    if raw_image not in (None, ""):
        primary = raw_image
    elif raw_model not in (None, ""):
        primary = raw_model
    elif fmt in {"sd-webui", "fal"}:
        primary = ""
    else:
        primary = DEFAULT_IMAGES_MODEL
    return {
        "name": name,
        "base_url": base_url,
        "api_key": api_key,
        "images_model": primary if primary != "" or fmt in {"sd-webui", "fal"} else DEFAULT_IMAGES_MODEL,
        "responses_model": (
            channel.get("responses_model")
            or (raw_image if raw_image not in (None, "") else None)
            or (raw_model if raw_model not in (None, "") else None)
            or DEFAULT_RESPONSES_MODEL
        ),
        "chat_model": (
            channel.get("chat_model")
            or (raw_image if raw_image not in (None, "") else None)
            or (raw_model if raw_model not in (None, "") else None)
            or DEFAULT_CHAT_MODEL
        ),
        "api_format": fmt,
        "wire_api": channel.get("wire_api"),
        "requires_openai_auth": channel.get("requires_openai_auth"),
        # Prefer native Imagine models when channel uses xAI/Sub2API format
        "prefer_xai_images": fmt == "xai",
    }


def resolve_endpoint_mode(args_mode: str, api_format: str) -> str:
    """Map channel api_format onto endpoint_mode when user left auto."""
    if args_mode and args_mode != "auto":
        return args_mode
    fmt = (api_format or "openai").lower()
    if fmt == "sd-webui":
        return "sd-webui"
    if fmt == "fal":
        return "fal"
    # xAI / Sub2API: force images generations path (not responses/chat cascade)
    if fmt == "xai":
        return "images"
    return "auto"


def _read_prompt(args):
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
    if args.prompt == "-":
        return sys.stdin.read().strip()
    return (args.prompt or "").strip()


# ============================================================================
# Main
# ============================================================================
def main():
    try:
        from _common import configure_proxy_opener as _cpo
        _cpo()
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="HelloMedia Image Generation")
    parser.add_argument("--prompt", default=None, help="Generation prompt. Use '-' for stdin.")
    parser.add_argument("--prompt-file", default=None, help="Read prompt from UTF-8 file")
    parser.add_argument("--output", default="./output/generated.png", help="Output path")
    parser.add_argument("--channel", type=int, default=None, help="Force specific channel by priority")
    # Runtime / CLI credentials (skill is self-contained without separate image tools)
    parser.add_argument("--base-url", default=None, help="Override channel base URL")
    parser.add_argument("--api-key", default=None, help="Override channel API key")
    parser.add_argument("--model", default=None, help="Override images model")
    parser.add_argument("--responses-model", default=None, help="Override responses model")
    parser.add_argument("--chat-model", default=None, help="Override chat fallback model")
    parser.add_argument("--provider", default=None, help="Provider name from ~/.codex/config.toml")
    parser.add_argument("--codex-home", default=None, help="Codex home (default ~/.codex)")
    parser.add_argument("--no-codex-config", action="store_true", help="Do not read ~/.codex config")
    parser.add_argument("--no-runtime-auth", action="store_true",
                        help="Disable Codex/Hermes/OpenClaw auth discovery (config.json / explicit flags only)")
    parser.add_argument("--hermes-home", default=None, help="Hermes home for auth discovery")
    parser.add_argument("--openclaw-state-dir", default=None)
    parser.add_argument("--openclaw-agent-dir", default=None)
    parser.add_argument("--chatgpt-account-id", default=None)
    parser.add_argument("--client-version", default=None)
    parser.add_argument("--originator", default=None)
    parser.add_argument("--size", default=None, help="Override auto-detected size (WxH or 'auto')")
    parser.add_argument("--max-resolution", choices=("2k", "4k", "1536", "2048", "3840"),
                        default=None, help="Provider resolution ceiling")
    parser.add_argument("--timeout", type=int, default=None, help="Per-request timeout in seconds")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="auto")
    parser.add_argument("--format", choices=("png", "jpeg", "webp"), default="png")
    parser.add_argument("--thinking", choices=("off", "low", "medium", "high"), default=None,
                        help="gpt-image-2 reasoning budget for complex compositing (off/low/medium/high)")
    parser.add_argument("--seed", type=int, default=None, help="Generation seed for semi-deterministic output")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help="Number of images to generate (1-10)",
    )
    parser.add_argument("--image", action="append", default=None, help="Reference image path (repeatable)")
    parser.add_argument("--endpoint-mode", choices=("auto", "images", "responses", "chat", "sd-webui", "fal"), default="auto",
                        help="Endpoint protocol (auto maps api_format sd-webui/fal; else OpenAI-compatible cascade)")
    parser.add_argument("--responses-mode", choices=("auto", "stream", "json"), default="auto",
                        help="How /v1/responses should be consumed")
    parser.add_argument("--sd-steps", type=int, default=30, help="SD WebUI sampling steps (default: 30)")
    parser.add_argument("--sd-cfg-scale", type=float, default=7.5, help="SD WebUI CFG scale (default: 7.5)")
    parser.add_argument("--sd-sampler", default="DPM++ 2M Karras", help="SD WebUI sampler name")
    parser.add_argument("--layout-analysis", choices=("auto", "off"), default="auto",
                        help="Use LLM to infer canvas ratio when prompt lacks explicit size/ratio")
    parser.add_argument("--layout-min-confidence", type=float, default=0.65,
                        help="Fallback to square when layout confidence below this (0-1)")
    parser.add_argument("--retry-count", type=int, default=None, help="Retries per channel (overrides config)")
    parser.add_argument("--cooldown", type=float, default=2.5, help="Seconds between requests to avoid rate limits")
    parser.add_argument("--dry-run", action="store_true", help="Print config preview without generating")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        from media_caps import IMAGE_OUTPUT_COUNT_MAX, IMAGE_OUTPUT_COUNT_MIN
    except Exception:
        try:
            from scripts.media_caps import IMAGE_OUTPUT_COUNT_MAX, IMAGE_OUTPUT_COUNT_MIN
        except Exception:
            IMAGE_OUTPUT_COUNT_MIN, IMAGE_OUTPUT_COUNT_MAX = 1, 10
    if args.count < IMAGE_OUTPUT_COUNT_MIN or args.count > IMAGE_OUTPUT_COUNT_MAX:
        print(json.dumps({
            "ok": False,
            "error": f"count must be {IMAGE_OUTPUT_COUNT_MIN}-{IMAGE_OUTPUT_COUNT_MAX}, got {args.count}",
            "code": "invalid_count",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    # Resolve prompt
    args.prompt = _read_prompt(args)
    if not args.prompt:
        print(json.dumps({"error": "No prompt provided. Use --prompt, --prompt-file, or stdin."},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    verbose = not args.quiet
    channels, defaults = load_channels()
    timeout_override = args.timeout or defaults.get("timeout_seconds")
    retry_count = args.retry_count or defaults.get("retry_count", 2)
    max_resolution = normalize_resolution(
        args.max_resolution or defaults.get("max_resolution", "2k"))
    cooldown = args.cooldown if args.cooldown > 0 else defaults.get("cooldown_seconds", 2.5)
    layout_analysis = args.layout_analysis != "off"
    layout_min_confidence = args.layout_min_confidence

    targets = [c for c in channels if args.channel is None or c["priority"] == args.channel]

    # Runtime auth: Codex/Hermes/OpenClaw + CLI. Skill config.json channels preferred when present.
    runtime_auth = {}
    runtime_cfg = {}
    codex_home = None
    if _auth is not None and not args.no_runtime_auth:
        codex_home = Path(args.codex_home).expanduser() if args.codex_home else _auth.default_codex_home()
        if not args.no_codex_config:
            try:
                runtime_cfg = _auth.read_codex_config(codex_home, args.provider)
            except Exception as exc:
                _progress(f"codex config read skipped: {exc}", verbose=verbose)
                runtime_cfg = {}

    if not targets:
        # Fall back to pure runtime credentials when no generate channel is configured
        if _auth is None or args.no_runtime_auth:
            print(json.dumps({"error": "No matching generate channels"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        raw_base = args.base_url or (_auth.first_value(_auth.BASE_URL_ENV) if _auth else None) or runtime_cfg.get("base_url")
        if not raw_base:
            print(json.dumps({"error": "No generate channels and no --base-url / Codex base_url"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        base_url = _auth.normalize_base_url(raw_base)
        # Build a synthetic channel
        ns = argparse.Namespace(
            api_key=args.api_key,
            chatgpt_account_id=args.chatgpt_account_id,
            originator=args.originator,
            client_version=args.client_version,
            hermes_home=args.hermes_home,
            openclaw_agent_dir=args.openclaw_agent_dir,
            openclaw_state_dir=args.openclaw_state_dir,
            base_url=base_url,
        )
        runtime_auth = _auth.resolve_auth_context(ns, runtime_cfg, codex_home)
        api_key = runtime_auth.get("api_key")
        images_model = (
            args.model
            or (_auth.first_value(_auth.MODEL_ENV) if _auth else None)
            or runtime_cfg.get("images_model")
            or DEFAULT_IMAGES_MODEL
        )
        responses_model = args.responses_model or runtime_cfg.get("responses_model") or DEFAULT_RESPONSES_MODEL
        chat_model = args.chat_model or runtime_cfg.get("chat_model") or images_model
        synthetic = {
            "name": f"runtime:{runtime_auth.get('auth_source') or 'cli'}",
            "base_url": base_url,
            "api_key": api_key or "",
            "model": images_model,
            "image_model": images_model,
            "responses_model": responses_model,
            "chat_model": chat_model,
            "generate": True,
            "priority": 0,
            "wire_api": runtime_auth.get("wire_api") or runtime_cfg.get("wire_api"),
            "requires_openai_auth": runtime_auth.get("requires_openai_auth") or runtime_cfg.get("requires_openai_auth"),
        }
        targets = [synthetic]
        channels = targets

    # For dry-run, show info for first matching channel
    if args.dry_run:
        ch = targets[0]
        params = resolve_channel_params(ch)
        # CLI overrides
        if args.base_url:
            params["base_url"] = args.base_url
        if args.api_key:
            params["api_key"] = args.api_key
        if args.model:
            params["images_model"] = args.model
        if args.responses_model:
            params["responses_model"] = args.responses_model
        if args.chat_model:
            params["chat_model"] = args.chat_model
        effective_ep = resolve_endpoint_mode(args.endpoint_mode, params.get("api_format") or "openai")
        # ---- Determine effective timeout ----
        _size = args.size or "auto"
        _timeout = "auto (will be computed at runtime)" if _size == "auto" else resolve_timeout(_size, has_ref=bool(args.image), override=timeout_override)
        preview = {
            "ok": True,
            "dry_run": True,
            "channel": params["name"],
            "base_url": _normalize_base_url(params["base_url"]) if params["base_url"] else None,
            "has_api_key": bool(params["api_key"]),
            "images_model": params["images_model"],
            "responses_model": params["responses_model"],
            "chat_model": params["chat_model"],
            "api_format": params.get("api_format"),
            "endpoint_mode": args.endpoint_mode,
            "effective_endpoint_mode": effective_ep,
            "generate_channel_count": len(targets),
            "responses_mode": args.responses_mode,
            "size": args.size or "auto",
            "max_resolution": max_resolution,
            "quality": args.quality,
            "format": args.format,
            "timeout_seconds": _timeout,
            "retry_count": retry_count,
            "cooldown": cooldown,
            "layout_analysis": layout_analysis,
            "image_refs": args.image,
            "count": args.count,
            "runtime_auth_available": _auth is not None and not args.no_runtime_auth,
            "provider": args.provider or (runtime_cfg.get("provider") if runtime_cfg else None),
        }
        if _auth is not None and not args.no_runtime_auth:
            try:
                b = _auth.normalize_base_url(params["base_url"]) if params.get("base_url") else ""
                ns = argparse.Namespace(
                    api_key=args.api_key or params.get("api_key"),
                    chatgpt_account_id=args.chatgpt_account_id,
                    originator=args.originator,
                    client_version=args.client_version,
                    hermes_home=args.hermes_home,
                    openclaw_agent_dir=args.openclaw_agent_dir,
                    openclaw_state_dir=args.openclaw_state_dir,
                    base_url=b,
                )
                ch_home = codex_home or _auth.default_codex_home()
                ac = _auth.resolve_auth_context(ns, runtime_cfg or {}, ch_home)
                preview["auth_mode"] = ac.get("auth_mode")
                preview["auth_source"] = ac.get("auth_source")
                preview["has_api_key"] = bool(ac.get("api_key") or params.get("api_key"))
                preview["wire_api"] = ac.get("wire_api")
                preview["is_local_codex_proxy"] = ac.get("is_local_codex_proxy")
                preview["is_codex_backend"] = ac.get("is_codex_backend")
            except Exception as exc:
                preview["auth_probe_error"] = str(exc)
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return  # after dry-run

    has_ref = bool(args.image)
    image_refs = [str(Path(p).resolve()).replace("\\", "/") for p in args.image] if args.image else None
    format_out = args.format
    seed = args.seed
    thinking = args.thinking

    # ---- Determine size (with optional semantic layout analysis) ----
    if args.size and args.size != "auto":
        # CLI explicit size
        parsed = None
        m = re.match(r"(\d+)x(\d+)", args.size)
        if m:
            parsed = (int(m.group(1)), int(m.group(2)))
        if parsed:
            constrained = _constrain_size(parsed, max_resolution)
            size = _format_size(constrained)
        else:
            size = args.size
        size_meta = {"source": "cli-override", "orientation": "unknown"}
    else:
        # Use first channel for layout analysis
        params = resolve_channel_params(targets[0])
        base_url = _normalize_base_url(params["base_url"]) if params["base_url"] else None
        analysis_model = params.get("responses_model") or params.get("images_model")
        size, size_meta = resolve_size(
            args.prompt, None, max_resolution,
            base_url=base_url, api_key=params["api_key"], model=analysis_model,
            layout_analysis=layout_analysis, layout_min_confidence=layout_min_confidence,
            verbose=verbose,
        )

    quality = choose_quality(size, args.quality)
    timeout = resolve_timeout(size, has_ref=has_ref, override=timeout_override)
    output_paths = _build_output_paths(args.output, args.count, format_out)

    # Validate output paths are safe (within project or skill runtime dir)
    safe, rejected = _validate_output_paths(output_paths)
    if not safe:
        print(json.dumps({"error": f"Unsafe output path(s) rejected: {rejected}. Use a path within the project directory (e.g. ./output/)."}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    errors: list[str] = []
    all_trace: list[dict[str, Any]] = []

    def prepare_channel(channel: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Return (params, auth_ctx, endpoint_mode) for one generate channel."""
        params = resolve_channel_params(channel)
        if args.base_url:
            params["base_url"] = args.base_url
        if args.model:
            params["images_model"] = args.model
        if args.responses_model:
            params["responses_model"] = args.responses_model
        if args.chat_model:
            params["chat_model"] = args.chat_model
        if args.api_key:
            params["api_key"] = args.api_key

        auth_ctx: dict[str, Any] = dict(runtime_auth) if runtime_auth else {}
        if _auth is not None and not args.no_runtime_auth:
            try:
                base_for_auth = (
                    _auth.normalize_base_url(params["base_url"]) if params.get("base_url") else ""
                )
            except Exception:
                base_for_auth = (
                    _normalize_base_url(params["base_url"]) if params.get("base_url") else ""
                )
            ns = argparse.Namespace(
                api_key=params.get("api_key") or None,
                chatgpt_account_id=args.chatgpt_account_id,
                originator=args.originator,
                client_version=args.client_version,
                hermes_home=args.hermes_home,
                openclaw_agent_dir=args.openclaw_agent_dir,
                openclaw_state_dir=args.openclaw_state_dir,
                base_url=base_for_auth,
            )
            cfg_for_auth = dict(runtime_cfg)
            if params.get("wire_api"):
                cfg_for_auth.setdefault("wire_api", params.get("wire_api"))
            if params.get("requires_openai_auth") is not None:
                cfg_for_auth.setdefault("requires_openai_auth", params.get("requires_openai_auth"))
            ch_home = codex_home or _auth.default_codex_home()
            try:
                auth_ctx = _auth.resolve_auth_context(ns, cfg_for_auth, ch_home)
            except Exception as exc:
                _progress(f"runtime auth resolve skipped: {exc}", verbose=verbose)
                auth_ctx = {
                    "api_key": params.get("api_key"),
                    "auth_mode": "skill-config",
                    "auth_source": "config.json",
                }
            if auth_ctx.get("api_key"):
                params["api_key"] = auth_ctx["api_key"]
            if base_for_auth:
                params["base_url"] = base_for_auth
            if auth_ctx.get("wire_api") and not params.get("wire_api"):
                params["wire_api"] = auth_ctx.get("wire_api")
        else:
            auth_ctx = {
                "api_key": params.get("api_key"),
                "auth_mode": "skill-config",
                "auth_source": "config.json",
                "wire_api": params.get("wire_api"),
                "requires_openai_auth": params.get("requires_openai_auth"),
            }

        # channel wire_api into auth for endpoint ordering
        if params.get("wire_api") and not auth_ctx.get("wire_api"):
            auth_ctx["wire_api"] = params["wire_api"]
        if params.get("requires_openai_auth") is not None:
            auth_ctx["requires_openai_auth"] = params["requires_openai_auth"]

        ep_mode = resolve_endpoint_mode(args.endpoint_mode, params.get("api_format") or "openai")
        # sd-webui may not need api_key
        needs_key = ep_mode not in {"sd-webui"}
        if not params.get("base_url") or (needs_key and not params.get("api_key")):
            raise RequestFailure(
                f"{params['name']}: missing base_url"
                + (" or api_key" if needs_key else "")
            )
        return params, auth_ctx, ep_mode

    started = time.time()
    results = []
    transports = []
    total_attempts = 0
    any_fallback = False
    used_params = None
    used_ep_mode = args.endpoint_mode

    # Multi-channel cascade: try each generate channel until success
    last_channel_error = None
    for ch_index, channel in enumerate(targets):
        try:
            params, auth_ctx, ep_mode = prepare_channel(channel)
        except RequestFailure as exc:
            errors.append(str(exc))
            all_trace.append({"channel": channel.get("name"), "status": "skip", "error": str(exc)})
            last_channel_error = exc
            continue

        label = f"{params['name']} ({params['images_model'] or ep_mode})"
        _progress(f"Using {label} endpoint_mode={ep_mode}...", verbose=verbose)
        used_params = params
        used_ep_mode = ep_mode

        channel_ok = False
        for attempt in range(retry_count + 1):
            if attempt > 0:
                _progress(f"Retry batch {attempt}/{retry_count} on {label}...", verbose=verbose)
                time.sleep(2)
            try:
                results = []
                transports = []
                total_attempts = 0
                any_fallback = False
                for idx, output_path in enumerate(output_paths, start=1):
                    _progress(f"generating image {idx}/{len(output_paths)} -> {output_path}", verbose=verbose)
                    image_bytes, transport, attempts, trace = generate_image(
                        base_url=_normalize_base_url(params["base_url"]),
                        api_key=params["api_key"] or "",
                        images_model=params["images_model"],
                        responses_model=params["responses_model"],
                        chat_model=params["chat_model"],
                        prompt=args.prompt,
                        size=size,
                        quality=quality,
                        fmt=format_out,
                        timeout=timeout,
                        max_attempts=3,
                        base_delay=2.0,
                        cooldown=cooldown,
                        verbose=verbose,
                        image_refs=image_refs,
                        endpoint_mode=ep_mode,
                        responses_mode=args.responses_mode,
                        seed=seed,
                        thinking=thinking,
                        sd_steps=args.sd_steps,
                        sd_cfg_scale=args.sd_cfg_scale,
                        sd_sampler=args.sd_sampler,
                        auth=auth_ctx,
                        api_format=params.get("api_format") or (auth_ctx or {}).get("api_format"),
                    )
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(image_bytes)
                    results.append({
                        "index": idx,
                        "output": str(output_path),
                        "transport": transport,
                        "fallback_used": any(t.get("status") == "fallback" for t in trace),
                        "attempts": attempts,
                        "timeout_seconds": timeout,
                        "bytes": len(image_bytes),
                        "attempt_trace": trace,
                        "markdown_image": f"![generated image]({str(output_path).replace(os.sep, '/')})",
                    })
                    all_trace.extend([{**item, "image_index": idx, "channel": params["name"]} for item in trace])
                    transports.append(transport)
                    total_attempts += attempts
                    any_fallback = any_fallback or any(t.get("status") == "fallback" for t in trace)
                    _progress(f"saved image {idx}/{len(output_paths)} -> {output_path}", verbose=verbose)

                channel_ok = True
                break
            except RequestFailure as exc:
                errors.append(f"{label}: {exc}")
                all_trace.append({
                    "channel": params["name"], "attempt": attempt,
                    "status": "failed", "error": str(exc),
                })
                last_channel_error = exc
                _progress(f"batch attempt {attempt} failed on {label}: {exc}", verbose=verbose)
                if exc.status in {401, 402, 403}:
                    break  # try next channel
                # permanent client errors other than auth → still try next channel after retries
                continue

        if channel_ok:
            elapsed = round(time.time() - started, 2)
            result = {
                "ok": True,
                "output": results[0]["output"] if len(results) == 1 else [r["output"] for r in results],
                "channel": used_params["name"] if used_params else None,
                "images_model": used_params["images_model"] if used_params else None,
                "responses_model": used_params["responses_model"] if used_params else None,
                "chat_model": used_params["chat_model"] if used_params else None,
                "endpoint_mode": used_ep_mode,
                "api_format": used_params.get("api_format") if used_params else None,
                "transport": transports[0] if len(set(transports)) == 1 else transports,
                "fallback_used": any_fallback or ch_index > 0,
                "attempts": total_attempts,
                "attempt_trace": all_trace,
                "count": args.count,
                "size": size,
                "size_source": size_meta.get("source"),
                "orientation": size_meta.get("orientation"),
                "quality": quality,
                "timeout_seconds": timeout,
                "elapsed_seconds": elapsed,
                "results": results,
            }
            print(f"Image(s) saved: {len(results)}/{args.count} ({elapsed}s)", file=sys.stderr)
            if not args.quiet:
                print(json.dumps(result, ensure_ascii=False))
            return

        _progress(f"channel {label} exhausted, trying next generate channel...", verbose=verbose)

    elapsed = round(time.time() - started, 2)
    error_result = {
        "ok": False,
        "error": "Generation failed after all channels/retries",
        "details": errors,
        "size": size,
        "count": args.count,
        "elapsed_seconds": elapsed,
        "trace": all_trace,
        "last_error": str(last_channel_error) if last_channel_error else None,
    }
    print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
