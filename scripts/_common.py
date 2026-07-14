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
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlsplit, urlunsplit
from urllib.request import ProxyHandler, build_opener, install_opener, getproxies

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


def skill_version() -> str:
    """Public skill version string (from VERSION file)."""
    return _skill_version()


# Browser-like UA (aligned with happy-loki/grok-media-skill). Cloudflare / xAI CDN
# (imgen.x.ai, vidgen.x.ai) often block bare "hellomedia/*" or Python-urllib defaults.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
MEDIA_USER_AGENT_ENV = "HELLOMEDIA_USER_AGENT"


def resolve_media_user_agent() -> str:
    """User-Agent for API + media CDN. Override with HELLOMEDIA_USER_AGENT."""
    override = (os.environ.get(MEDIA_USER_AGENT_ENV) or os.environ.get("GROK_MEDIA_USER_AGENT") or "").strip()
    if override and "\n" not in override and "\r" not in override:
        return override
    return BROWSER_USER_AGENT


USER_AGENT = resolve_media_user_agent()
# Keep a short product tag only for non-media diagnostics if needed
PRODUCT_USER_AGENT = f"hellomedia/{_skill_version()}"

RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
PERMANENT_4XX = {400, 401, 402, 403, 404, 405, 410, 413, 414, 415, 422}

UNSAFE_PATH_FRAGMENTS = (
    "Desktop", "Downloads", "Documents", "OneDrive", "Pictures",
    "Music", "Videos", "Public",
)

# Media download: only network schemes. Loopback / LAN / local proxies MUST remain allowed.
ALLOWED_DOWNLOAD_SCHEMES = frozenset({"http", "https"})
DOWNLOAD_CHUNK_SIZE = 64 * 1024


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


def _path_is_under(path: Path, root: Path) -> bool:
    """True if path is root or a descendant. Uses path semantics, not string prefix."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_output_path(output_path: str) -> tuple[bool, Path | None]:
    """Allow writes under CWD, skill package tree, or skill .runtime.

    Uses Path relative_to (not startswith) so ``hellomedia_evil/`` cannot ride a
    prefix of ``hellomedia/``. Loopback / local network downloads are unrelated
    and remain unrestricted at the path layer.
    """
    if output_path == "-":
        return True, None
    p = Path(output_path).expanduser().resolve()
    cwd = Path.cwd().resolve()
    runtime = RUNTIME_DIR.resolve()
    skill = SKILL_DIR.resolve()
    allowed_roots = (cwd, runtime, skill)
    if any(_path_is_under(p, root) for root in allowed_roots):
        return True, p
    p_str = str(p)
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
    if max_bytes is not None:
        try:
            size = p.stat().st_size
        except OSError as e:
            raise ValueError(f"Cannot read file size: {path}: {e}") from e
        if size > max_bytes:
            raise ValueError(
                f"File too large for data URL ({size} bytes > {max_bytes}). "
                "Use a public URL or a smaller file."
            )
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



EXPLICIT_PROXY_ENV = "HELLOMEDIA_PROXY"
SUPPORTED_PROXY_SCHEMES = frozenset({"http", "https"})
MEDIA_DOWNLOAD_ATTEMPTS = 3
_PROXY_INSTALLED: dict[str, Any] | None = None


def _supported_proxy_url(value: Any) -> tuple[str | None, str | None]:
    proxy_url = str(value or "").strip()
    if not proxy_url:
        return None, None
    scheme = urlsplit(proxy_url).scheme.lower()
    if scheme in SUPPORTED_PROXY_SCHEMES:
        return proxy_url, None
    if scheme:
        return None, scheme
    return None, "unknown"


def _environment_proxy_is_configured() -> bool:
    names = {k.lower() for k in os.environ}
    return any(n in names for n in ("http_proxy", "https_proxy", "all_proxy", "hellomedia_proxy"))


def resolve_proxy_settings() -> tuple[dict[str, str], dict[str, Any]]:
    """Return (proxies for ProxyHandler, public_summary without secrets)."""
    explicit = os.environ.get(EXPLICIT_PROXY_ENV)
    if explicit:
        proxy_url, unsupported = _supported_proxy_url(explicit)
        if unsupported:
            return {}, {
                "enabled": False,
                "source": "explicit",
                "unsupported_schemes": [unsupported],
                "error": f"{EXPLICIT_PROXY_ENV} must use http/https proxy URL",
            }
        if not proxy_url:
            return {}, {"enabled": False, "source": "explicit", "unsupported_schemes": []}
        return (
            {"http": proxy_url, "https": proxy_url},
            {
                "enabled": True,
                "source": "explicit",
                "schemes": ["http", "https"],
                "unsupported_schemes": [],
            },
        )

    proxies: dict[str, str] = {}
    unsupported: list[str] = []
    detected: dict[str, str] = {}
    for key, env_names in (
        ("http", ("HTTP_PROXY", "http_proxy")),
        ("https", ("HTTPS_PROXY", "https_proxy")),
        ("all", ("ALL_PROXY", "all_proxy")),
    ):
        for name in env_names:
            val = os.environ.get(name)
            if val:
                detected[key] = val
                break
    try:
        for k, v in (getproxies() or {}).items():
            kl = k.lower()
            if kl in {"http", "https", "all"} and kl not in detected and v:
                detected[kl] = v
    except Exception:
        pass

    for target in ("http", "https"):
        if target in detected:
            url, bad = _supported_proxy_url(detected[target])
            if url:
                proxies[target] = url
            elif bad:
                unsupported.append(bad)
    if "all" in detected:
        url, bad = _supported_proxy_url(detected["all"])
        if url:
            proxies.setdefault("http", url)
            proxies.setdefault("https", url)
        elif bad:
            unsupported.append(bad)

    unsupported = sorted(set(unsupported))
    if proxies:
        source = "environment" if _environment_proxy_is_configured() else "system"
        return proxies, {
            "enabled": True,
            "source": source,
            "schemes": sorted(proxies.keys()),
            "unsupported_schemes": unsupported,
        }
    return {}, {
        "enabled": False,
        "source": "none",
        "schemes": [],
        "unsupported_schemes": unsupported,
    }


def configure_proxy_opener() -> dict[str, Any]:
    """Install process-wide urllib opener with ProxyHandler when proxies present."""
    global _PROXY_INSTALLED
    proxies, summary = resolve_proxy_settings()
    if proxies:
        opener = build_opener(ProxyHandler(proxies))
        install_opener(opener)
    else:
        install_opener(build_opener())
    _PROXY_INSTALLED = dict(summary)
    return summary


def proxy_summary() -> dict[str, Any]:
    if _PROXY_INSTALLED is not None:
        return dict(_PROXY_INSTALLED)
    _, summary = resolve_proxy_settings()
    return summary


def remove_partial_download(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


def validate_download_url(url: str) -> str:
    """Allow http(s) only — including loopback, LAN, and local reverse proxies.

    Rejects file:// and other non-network schemes. Does NOT block 127.0.0.1:
    local proxy / Ollama / flaky-test servers are first-class.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("empty download URL")
    parsed = urlsplit(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_DOWNLOAD_SCHEMES:
        raise ValueError(
            f"unsupported download URL scheme '{scheme or '(none)'}'; "
            f"only {', '.join(sorted(ALLOWED_DOWNLOAD_SCHEMES))} are allowed "
            "(loopback and LAN hosts are allowed)"
        )
    if not parsed.netloc:
        raise ValueError("download URL missing host")
    return raw


def download_url(
    url: str,
    dest: Path,
    timeout: float = 300,
    *,
    max_attempts: int = MEDIA_DOWNLOAD_ATTEMPTS,
    api_key: str | None = None,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
) -> Path:
    """Download URL to dest with retries; cleans incomplete files on failure.

    Streams to disk in chunks. Allows loopback/LAN http(s) by design.
    Uses browser-like User-Agent (xAI imgen/vidgen CDN friendly).
    If source host matches base_url host and api_key is set, sends Authorization
    (Sub2API same-host media). Does not force-block loopback.
    """
    url = validate_download_url(url)
    ensure_parent(dest)
    last_err: Exception | None = None
    ua = resolve_media_user_agent()
    for attempt in range(1, max_attempts + 1):
        try:
            req_headers = {"User-Agent": ua, "Accept": "*/*"}
            if headers:
                req_headers.update(headers)
            if api_key and base_url:
                try:
                    src_host = urlsplit(url).netloc.lower()
                    base_host = urlsplit(
                        base_url if "://" in base_url else f"https://{base_url}"
                    ).netloc.lower()
                    if src_host and base_host and src_host == base_host:
                        req_headers.setdefault("Authorization", f"Bearer {api_key}")
                except Exception:
                    pass
            req = urllib.request.Request(url, headers=req_headers, method="GET")
            wrote = 0
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                with dest.open("wb") as out:
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        out.write(chunk)
                        wrote += len(chunk)
            if wrote == 0:
                remove_partial_download(dest)
                raise OSError("empty download body")
            return dest
        except urllib.error.HTTPError as e:
            last_err = e
            remove_partial_download(dest)
            if e.code in PERMANENT_4XX and e.code not in RETRY_STATUS_CODES:
                raise
            if attempt >= max_attempts:
                raise
            delay = min(8, 2 ** (attempt - 1))
            eprint(f"[download] HTTP {e.code}, retry in {delay}s ({attempt}/{max_attempts})")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            last_err = e
            remove_partial_download(dest)
            if attempt >= max_attempts:
                raise
            delay = min(8, 2 ** (attempt - 1))
            eprint(f"[download] network error, retry in {delay}s ({attempt}/{max_attempts})")
            time.sleep(delay)
    raise OSError(f"download failed after {max_attempts} attempts: {last_err}")


def recover_media_url(
    url: str,
    output: str,
    *,
    kind: str = "video",
    timeout: float = 300,
) -> dict[str, Any]:
    """GET-only recovery of a previously generated media URL. Never POSTs generate."""
    safe, resolved = safe_output_path(output)
    if not safe or resolved is None:
        return {"ok": False, "error": f"Unsafe output path: {output}", "url": url}
    if kind == "video" and resolved.suffix.lower() not in (".mp4", ".webm", ".mov"):
        resolved = resolved.with_suffix(".mp4")
    if kind == "image" and resolved.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        resolved = resolved.with_suffix(".png")
    try:
        download_url(url, resolved, timeout=timeout)
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "url": url,
            "download_error": str(e),
            "status": "download_failed",
        }
    path_s = str(resolved).replace("\\", "/")
    return {
        "ok": True,
        "status": "completed",
        "url": url,
        "saved_to": path_s,
        "kind": kind,
        "markdown_media": f"![{kind}]({path_s})",
    }


XAI_NETWORK_TARGETS = (
    ("api", "https://api.x.ai/"),
    ("imgen", "https://imgen.x.ai/"),
    ("vidgen", "https://vidgen.x.ai/"),
)


def probe_http_target(name: str, url: str, timeout: float = 5.0) -> dict[str, Any]:
    started = time.time()
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": resolve_media_user_agent(), "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "name": name,
                "reachable": True,
                "http_status": int(getattr(resp, "status", 200) or 200),
                "latency_ms": round((time.time() - started) * 1000),
            }
    except urllib.error.HTTPError as e:
        return {
            "name": name,
            "reachable": True,
            "http_status": int(e.code),
            "latency_ms": round((time.time() - started) * 1000),
        }
    except Exception as e:
        return {
            "name": name,
            "reachable": False,
            "error": str(e),
            "latency_ms": round((time.time() - started) * 1000),
        }


def check_xai_network(timeout: float = 5.0, *, use_cache: bool = True) -> dict[str, Any]:
    """Probe xAI API/CDN hosts. HTTP 4xx counts as reachable."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RUNTIME_DIR / "xai_network_ok.json"
    if use_cache and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("ok") and (time.time() - float(cached.get("ts", 0))) < 3600:
                return {**cached, "cached": True}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    proxy = configure_proxy_opener()
    targets: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {
            pool.submit(probe_http_target, name, url, timeout): name
            for name, url in XAI_NETWORK_TARGETS
        }
        for fut in as_completed(futs):
            targets.append(fut.result())
    targets.sort(key=lambda t: t.get("name") or "")
    ok = all(t.get("reachable") for t in targets)
    result = {
        "ok": ok,
        "targets": targets,
        "proxy": proxy,
        "ts": time.time(),
        "cached": False,
    }
    if ok:
        try:
            cache_path.write_text(json.dumps(result), encoding="utf-8")
        except OSError:
            pass
    return result


def is_xai_like_channel(channel: dict[str, Any] | None, base_url: str = "") -> bool:
    """True for xAI-compatible *API shape* (official or Sub2API/relay)."""
    if channel:
        fmt = (channel.get("api_format") or "").lower()
        if fmt == "xai":
            return True
        base_url = base_url or channel.get("video_base_url") or channel.get("base_url") or ""
    return is_xai_endpoint(base_url or "")


def is_official_xai_host(base_url: str = "") -> bool:
    """True only for official api.x.ai (not Sub2API relays that set api_format=xai)."""
    return is_xai_endpoint(base_url or "")


def video_image_url_field(base_url: str = "", channel: dict[str, Any] | None = None) -> str:
    """Field name inside video image objects.

    Official api.x.ai uses ``url``. Sub2API relays (happy-loki/grok-media-skill)
    default to ``image_url`` unless host is api.x.ai.
    """
    if channel:
        explicit = (
            channel.get("video_image_url_field")
            or channel.get("image_url_field")
            or ""
        )
        if explicit:
            return str(explicit).strip()
        base_url = base_url or channel.get("video_base_url") or channel.get("base_url") or ""
    if is_official_xai_host(base_url):
        return "url"
    return "image_url"


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
