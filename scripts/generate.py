#!/usr/bin/env python3
"""
HelloMultimodal — Self-contained image generation engine.
Multi-endpoint fallback: responses → images(-edits) → chat.
Configured via config.json. No external script dependency.
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

RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
# 4xx errors that should never be retried (permanent failures)
PERMANENT_4XX = {400, 401, 402, 403, 404, 405, 410, 413, 414, 415, 422}
IMAGE_KEYS = ("b64_json", "result", "image_base64", "base64", "image", "data")
IMAGE_MAGIC = ("iVBOR", "/9j/", "UklGR", "R0lGOD", "Qk")

OPENAI_SIZE_LIMITS = {
    "2k": {"max_width": 1536, "max_height": 1536, "max_pixels": 2_359_296},
    "4k": {"max_width": 3840, "max_height": 3840, "max_pixels": 8_847_360},
}
SEMANTIC_RATIO_OPTIONS = (
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
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


def _decode_image_bytes(source, timeout):
    kind, value = source
    if kind == "b64":
        encoded = value.split(",", 1)[1] if value.startswith("data:image/") else value
        return base64.b64decode(encoded)
    with urllib.request.urlopen(value, timeout=timeout) as resp:
        return resp.read()


def _image_to_data_url(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Reference image not found: {p}")
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


def _build_endpoint_urls(base_url, endpoint):
    """Return ordered list of (style, url) variants to try."""
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
def _request_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
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
def _request_via_images(base_url, api_key, model, prompt, size, quality, fmt,
                        timeout, max_attempts, base_delay, cooldown, verbose, trace,
                        seed=None, thinking=None):
    """POST /v1/images/generations — full → minimal payload fallback."""
    headers = _request_headers(api_key)
    urls = _build_endpoint_urls(base_url, "images")
    last_exc = None

    for style, url in urls:
        def _try(payload):
            def call():
                return _post_json(url, payload, headers, timeout)
            result, attempts = _run_with_retries(
                "images", call, max_attempts, base_delay, cooldown, verbose)
            src = _extract_image_source(result)
            if not src:
                raise RequestFailure("images API returned no image payload", attempts=attempts)
            return _decode_image_bytes(src, timeout), attempts

        # Full payload
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
                              seed=None, thinking=None):
    """POST /v1/images/edits — multipart → JSON fallback."""
    headers = _request_headers(api_key)
    urls = _build_endpoint_urls(base_url, "images-edits")
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
                           responses_mode, trace, seed=None, thinking=None):
    """POST /v1/responses with image_generation tool. SSE → JSON fallback."""
    headers = _request_headers(api_key)
    urls = _build_endpoint_urls(base_url, "responses")
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
                      seed=None, thinking=None):
    """POST /v1/chat/completions — compat → legacy payload fallback."""
    headers = _request_headers(api_key)
    urls = _build_endpoint_urls(base_url, "chat")
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
# Multi-endpoint orchestrator
# ============================================================================
def generate_image(base_url, api_key, images_model, responses_model, chat_model,
                   prompt, size, quality, fmt, timeout, max_attempts=3, base_delay=2.0,
                   cooldown=2.5, verbose=False, image_refs=None,
                   endpoint_mode="auto", responses_mode="auto", seed=None, thinking=None):
    """
    Generate one image through the optimal endpoint path.
    Returns (image_bytes, transport, total_attempts, trace).
    """
    trace: list[dict[str, Any]] = []
    is_openai = _is_official_openai(base_url)

    # ---- Build ordered endpoint list ----
    if endpoint_mode == "images":
        order = ["images-edits" if image_refs else "images"]
    elif endpoint_mode == "responses":
        order = ["responses"]
    elif endpoint_mode == "chat":
        order = ["chat"]
    elif image_refs:
        # With reference images, responses handles them natively
        order = ["responses", "images-edits"]
        if not is_openai:
            order.append("chat")
    elif is_openai:
        order = ["responses", "images"]
    else:
        order = ["images", "responses"]
        if not is_openai:
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
                    seed=seed, thinking=thinking)
                total_attempts += attempts
                return image_bytes, "images", total_attempts, trace

            elif ep == "images-edits":
                image_bytes, attempts, _ = _request_via_images_edits(
                    base_url, api_key, images_model, prompt, image_refs,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown, verbose, trace,
                    seed=seed, thinking=thinking)
                total_attempts += attempts
                return image_bytes, "images-edits", total_attempts, trace

            elif ep == "responses":
                image_bytes, attempts, mode = _request_via_responses(
                    base_url, api_key, responses_model, prompt, image_refs,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown,
                    verbose, responses_mode, trace, seed=seed, thinking=thinking)
                total_attempts += attempts
                return image_bytes, f"responses:{mode}", total_attempts, trace

            elif ep == "chat":
                image_bytes, attempts, _ = _request_via_chat(
                    base_url, api_key, chat_model, prompt, image_refs,
                    size, quality, fmt, timeout, max_attempts, base_delay, cooldown, verbose, trace,
                    seed=seed, thinking=thinking)
                total_attempts += attempts
                return image_bytes, "chat", total_attempts, trace

        except RequestFailure as exc:
            total_attempts += exc.attempts or 0
            last_error = exc
            # Stop on permission/auth failures for non-official endpoints
            if exc.status in {401, 402, 403} and not is_openai:
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
        print(json.dumps({"error": f"config.json not found at {cfg_path}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    channels = [c for c in cfg.get("channels", []) if c.get("generate")]
    channels.sort(key=lambda c: c.get("priority", 99))
    return channels, cfg.get("defaults", {})


def resolve_channel_params(channel):
    return {
        "name": channel["name"],
        "base_url": channel.get("image_base_url") or channel["base_url"],
        "api_key": channel.get("image_api_key") or channel["api_key"],
        "images_model": channel.get("image_model") or channel["model"],
        "responses_model": channel.get("responses_model") or channel.get("image_model") or channel["model"],
        "chat_model": channel.get("chat_model") or channel.get("image_model") or channel["model"],
    }


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
    parser = argparse.ArgumentParser(description="HelloMultimodal Image Generation")
    parser.add_argument("--prompt", default=None, help="Generation prompt. Use '-' for stdin.")
    parser.add_argument("--prompt-file", default=None, help="Read prompt from UTF-8 file")
    parser.add_argument("--output", default="./output/generated.png", help="Output path")
    parser.add_argument("--channel", type=int, default=None, help="Force specific channel by priority")
    parser.add_argument("--size", default=None, help="Override auto-detected size (WxH or 'auto')")
    parser.add_argument("--max-resolution", choices=("2k", "4k", "1536", "2048", "3840"),
                        default=None, help="Provider resolution ceiling")
    parser.add_argument("--timeout", type=int, default=None, help="Per-request timeout in seconds")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="auto")
    parser.add_argument("--format", choices=("png", "jpeg", "webp"), default="png")
    parser.add_argument("--thinking", choices=("off", "low", "medium", "high"), default=None,
                        help="gpt-image-2 reasoning budget for complex compositing (off/low/medium/high)")
    parser.add_argument("--seed", type=int, default=None, help="Generation seed for semi-deterministic output")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Number of images to generate")
    parser.add_argument("--image", action="append", default=None, help="Reference image path (repeatable)")
    parser.add_argument("--endpoint-mode", choices=("auto", "images", "responses", "chat"), default="auto",
                        help="Force specific endpoint protocol")
    parser.add_argument("--responses-mode", choices=("auto", "stream", "json"), default="auto",
                        help="How /v1/responses should be consumed")
    parser.add_argument("--layout-analysis", choices=("auto", "off"), default="auto",
                        help="Use LLM to infer canvas ratio when prompt lacks explicit size/ratio")
    parser.add_argument("--layout-min-confidence", type=float, default=0.65,
                        help="Fallback to square when layout confidence below this (0-1)")
    parser.add_argument("--retry-count", type=int, default=None, help="Retries per channel (overrides config)")
    parser.add_argument("--cooldown", type=float, default=2.5, help="Seconds between requests to avoid rate limits")
    parser.add_argument("--dry-run", action="store_true", help="Print config preview without generating")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

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
    if not targets:
        print(json.dumps({"error": "No matching generate channels"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    # For dry-run, show info for first matching channel
    if args.dry_run:
        ch = targets[0]
        params = resolve_channel_params(ch)
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
            "endpoint_mode": args.endpoint_mode,
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
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return  # after dry-run

    has_ref = bool(args.image)
    image_refs = list(args.image) if args.image else None
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

    errors: list[str] = []
    all_trace: list[dict[str, Any]] = []

    # Pick the first matching channel as the workhorse for all images
    channel = targets[0]
    params = resolve_channel_params(channel)
    label = f"{params['name']} ({params['images_model']})"
    _progress(f"Using {label}...", verbose=verbose)

    if not params["base_url"] or not params["api_key"]:
        print(json.dumps({"error": f"{label}: Missing base_url or api_key"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    started = time.time()
    results = []
    transports = []
    total_attempts = 0
    any_fallback = False

    _progress(
        f"start generation: images_model={params['images_model']}, responses_model={params['responses_model']}, "
        f"chat_model={params['chat_model']}, size={size}, quality={quality}, endpoint_mode={args.endpoint_mode}, "
        f"count={args.count}",
        verbose=verbose,
    )

    for attempt in range(retry_count + 1):
        if attempt > 0:
            _progress(f"Retry batch {attempt}/{retry_count}...", verbose=verbose)
            time.sleep(2)

        try:
            for idx, output_path in enumerate(output_paths, start=1):
                _progress(f"generating image {idx}/{len(output_paths)} -> {output_path}", verbose=verbose)
                image_bytes, transport, attempts, trace = generate_image(
                    base_url=_normalize_base_url(params["base_url"]),
                    api_key=params["api_key"],
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
                    endpoint_mode=args.endpoint_mode,
                    responses_mode=args.responses_mode,
                    seed=seed,
                    thinking=thinking,
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_bytes)
                results.append({
                    "index": idx,
                    "output": str(output_path),
                    "transport": transport,
                    "fallback_used": "fallback" in [t.get("status") for t in trace if t.get("status") == "fallback"],
                    "attempts": attempts,
                    "timeout_seconds": timeout,
                    "bytes": len(image_bytes),
                    "attempt_trace": trace,
                    "markdown_image": f"![generated image]({str(output_path).replace(os.sep, '/')})",
                })
                all_trace.extend([{**item, "image_index": idx} for item in trace])
                transports.append(transport)
                total_attempts += attempts
                any_fallback = any_fallback or any(
                    t.get("status") == "fallback" for t in trace
                )
                _progress(f"saved image {idx}/{len(output_paths)} -> {output_path}", verbose=verbose)

            # All images generated successfully
            elapsed = round(time.time() - started, 2)
            result = {
                "ok": True,
                "output": results[0]["output"] if len(results) == 1 else [r["output"] for r in results],
                "channel": params["name"],
                "images_model": params["images_model"],
                "responses_model": params["responses_model"],
                "chat_model": params["chat_model"],
                "transport": transports[0] if len(set(transports)) == 1 else transports,
                "fallback_used": any_fallback,
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
            return  # success — exit main()

        except RequestFailure as exc:
            errors.append(f"{label}: {exc}")
            all_trace.append({"channel": params["name"], "attempt": attempt,
                              "status": "failed", "error": str(exc)})
            _progress(f"batch attempt {attempt} failed: {exc}", verbose=verbose)
            # Don't retry batch on permission errors for non-OpenAI
            if exc.status in {401, 402, 403} and not _is_official_openai(_normalize_base_url(params["base_url"])):
                break

    # All retries exhausted
    elapsed = round(time.time() - started, 2)
    error_result = {
        "ok": False, "error": "Generation failed after retries", "details": errors,
        "size": size, "count": args.count, "elapsed_seconds": elapsed, "trace": all_trace,
    }
    print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
