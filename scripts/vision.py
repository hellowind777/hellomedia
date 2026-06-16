#!/usr/bin/env python3
"""
HelloMultimodal — Vision analysis with multi-channel fallback.
Reads config.json, tries channels by priority, falls back on failure.
Zero external dependencies — stdlib only.
"""

import base64, json, os, sys, argparse, urllib.request, urllib.error, socket
from pathlib import Path

# Ensure UTF-8 on Windows — must be at module level before any print() call
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).parent.parent

def load_channels():
    """Load channels from config.json, sorted by priority."""
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        print(f"config.json not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    channels = [c for c in cfg.get("channels", []) if c.get("vision")]
    channels.sort(key=lambda c: c.get("priority", 99))
    defaults = cfg.get("defaults", {})
    return channels, defaults

def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

def _normalize_base_url(raw):
    """Strip trailing /v1 (if present) so we can append our own path."""
    url = (raw or "").rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url


def _try_openai(channel, images, prompt, max_tokens, timeout):
    """OpenAI-compatible /v1/chat/completions (GPT, Kimi, MiniMax, Ollama, vLLM, etc.)."""
    content = [{"type": "text", "text": prompt}]
    for img_path in images:
        b64 = encode_image(img_path)
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "bmp": "image/bmp", "tiff": "image/tiff",
            "webp": "image/webp", "gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/png")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}})

    payload = {"model": channel["model"], "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {channel['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    base = _normalize_base_url(channel["base_url"])

    try:
        req = urllib.request.Request(f"{base}/v1/chat/completions", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        return False, {"error": f"HTTP {e.code}: {err_body}"}
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
        return False, {"error": str(e)}


def _try_anthropic(channel, images, prompt, max_tokens, timeout):
    """Anthropic native Messages API (/v1/messages)."""
    content = []
    for img_path in images:
        b64 = encode_image(img_path)
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "bmp": "image/bmp", "tiff": "image/tiff",
            "webp": "image/webp", "gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/png")
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
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
        "User-Agent": USER_AGENT,
    }
    base = _normalize_base_url(channel["base_url"])

    try:
        req = urllib.request.Request(f"{base}/v1/messages", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            # Normalise to OpenAI-style shape for uniform downstream parsing
            text = ""
            for block in data.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block.get("text", "")
            return True, {"choices": [{"message": {"content": text}}], "_anthropic_raw": data}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        return False, {"error": f"HTTP {e.code}: {err_body}"}
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
        return False, {"error": str(e)}


def try_channel(channel, images, prompt, max_tokens, timeout):
    """Route to the correct API format handler based on channel config."""
    fmt = channel.get("api_format", "openai")
    if fmt == "anthropic":
        return _try_anthropic(channel, images, prompt, max_tokens, timeout)
    return _try_openai(channel, images, prompt, max_tokens, timeout)

def _safe_output(output_path):
    """Reject unsafe output paths (Desktop, absolute user dirs outside project).
    Returns (is_safe: bool, resolved: Path | None)."""
    if output_path == "-":
        return True, None
    p = Path(output_path).resolve()
    cwd = Path.cwd().resolve()
    runtime = (SKILL_DIR / ".runtime").resolve()
    p_str = str(p)
    if p_str.startswith(str(cwd)) or p_str.startswith(str(runtime)):
        return True, p
    # Reject common unsafe locations
    for frag in ("Desktop", "Downloads", "Documents", "OneDrive", "Pictures",
                 "Music", "Videos", "Public"):
        if frag.lower() in p_str.lower():
            return False, p
    return False, p


def main():
    parser = argparse.ArgumentParser(description="HelloMultimodal Vision Analysis")
    parser.add_argument("--image", help="Single image path")
    parser.add_argument("--image-dir", help="Directory of images")
    parser.add_argument("--prompt", required=True, help="Analysis prompt")
    parser.add_argument("--output", default="-", help="Output file (default: stdout)")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--channel", type=int, default=None, help="Force specific channel by priority")
    args = parser.parse_args()

    channels, defaults = load_channels()
    max_tokens = args.max_tokens or defaults.get("max_tokens", 4096)
    timeout = defaults.get("timeout_seconds", 300)

    # Normalize paths: replace backslashes with forward slashes (survives shell escaping)
    def _norm(p):
        return str(Path(p).resolve()).replace("\\", "/") if p else None

    # Collect images
    images = []
    missing = []
    if args.image:
        p = _norm(args.image)
        if Path(p).exists():
            images.append(p)
        else:
            missing.append(p)
    if args.image_dir:
        dir_path = Path(_norm(args.image_dir))
        for ext in ("*.png","*.jpg","*.jpeg","*.bmp","*.tiff","*.webp","*.gif"):
            images.extend(str(p).replace("\\", "/") for p in dir_path.glob(ext))
        images.sort()
    if missing:
        print(json.dumps({"error": f"Image file(s) not found: {missing}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    if not images:
        print(json.dumps({"error": "No images provided"}), file=sys.stderr)
        sys.exit(1)

    # Filter channels if forced
    targets = [c for c in channels if args.channel is None or c["priority"] == args.channel]
    if not targets:
        print(json.dumps({"error": "No matching channels"}), file=sys.stderr)
        sys.exit(1)

    # Try channels with fallback — each channel gets one attempt, then next
    errors = []
    for channel in targets:
        label = f"{channel['name']} ({channel['model']})"
        print(f"Trying {label}...", file=sys.stderr)

        ok, result = try_channel(channel, images, args.prompt, max_tokens, timeout)
        if ok:
            result["_channel"] = channel["name"]
            result["_model"] = channel["model"]
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output == "-":
                print(output)
            else:
                safe, resolved = _safe_output(args.output)
                if not safe:
                    print(json.dumps({"error": f"Unsafe output path rejected: {args.output}. Output to stdout or a path within the project directory."}, ensure_ascii=False), file=sys.stderr)
                    sys.exit(1)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_text(output, encoding="utf-8")
                print(f"Saved to {resolved}", file=sys.stderr)
            return
        errors.append(f"{label}: {result.get('error', 'unknown')}")

    # All channels failed
    print(json.dumps({"error": "All channels failed", "details": errors}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
