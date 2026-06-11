#!/usr/bin/env python3
"""
HelloMultimodal — Image generation with multi-channel fallback.
Reads config.json, tries channels by priority, falls back on failure.
Borrows image extraction logic from helloimage (magic bytes, base64 decode).
"""

import base64, json, os, sys, argparse, time
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
IMAGE_MAGIC = ("iVBOR", "/9j/", "UklGR", "R0lGOD", "Qk")

# Natural language size/ratio patterns — extracted from prompt, NOT overridden by defaults
SIZE_PATTERNS = [
    (r'\b(\d{3,4})[x×](\d{3,4})\b', lambda m: f"{m[1]}x{m[2]}"),           # 1920x1080
    (r'\b(\d+):(\d+)\s*(?:ratio|比例)?\b', lambda m: f"{m[1]}:{m[2]}"),     # 16:9 ratio
    (r'\b(portrait|vertical|竖屏|纵向|竖版)\b', lambda _: "portrait"),        # portrait
    (r'\b(landscape|horizontal|横屏|横向|横版)\b', lambda _: "landscape"),    # landscape
    (r'\b(square|方形|正方形)\b', lambda _: "square"),                        # square
    (r'\b(banner|横幅|banner图)\b', lambda _: "landscape"),                   # banner
    (r'\b(poster|海报)\b', lambda _: "portrait"),                             # poster
    (r'\b(widescreen|宽屏|宽幅)\b', lambda _: "21:9"),                        # widescreen
]

def parse_size_from_prompt(prompt):
    """Extract size/ratio intent from natural language. Returns None if not specified."""
    import re
    for pattern, resolver in SIZE_PATTERNS:
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m:
            return resolver(m)
    return None

def build_generation_prompt(user_prompt):
    """Build the final prompt — only add size hint if user explicitly specified one."""
    size = parse_size_from_prompt(user_prompt)
    if size:
        return f"Generate an image: {user_prompt}. Use {size} dimensions."
    # No size specified → let the model freely interpret
    return f"Generate an image: {user_prompt}."

def load_channels():
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        print(f"config.json not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    channels = [c for c in cfg.get("channels", []) if c.get("generate")]
    channels.sort(key=lambda c: c.get("priority", 99))
    defaults = cfg.get("defaults", {})
    return channels, defaults

def extract_image(content):
    """Extract base64 image from response text. Adapted from helloimage."""
    if not content: return None
    if "data:image" in content:
        for part in content.split(","):
            part = part.strip()
            if any(part.startswith(m) for m in IMAGE_MAGIC):
                return base64.b64decode(part)
    for line in content.split("\n"):
        line = line.strip()
        if line and any(line.startswith(m) for m in IMAGE_MAGIC):
            try: return base64.b64decode(line)
            except: pass
    return None

def try_channel(channel, prompt, timeout):
    """Try image generation — uses image_model + optional dedicated image_api_key."""
    import requests
    # Use dedicated image credentials if configured, otherwise fallback to main channel credentials
    img_key = channel.get("image_api_key") or channel["api_key"]
    img_base = channel.get("image_base_url") or channel["base_url"]
    image_model = channel.get("image_model") or channel["model"]

    if not img_key:
        return False, "No API key configured (image_api_key or api_key required)"

    headers = {"Authorization": f"Bearer {img_key}", "Content-Type": "application/json"}

    try:
        size = parse_size_from_prompt(prompt) or "1024x1024"
        size = size.replace(" ", "")
        resp = requests.post(
            f"{img_base}/v1/images/generations", headers=headers,
            json={"model": image_model, "prompt": prompt, "n": 1, "size": size, "response_format": "b64_json"},
            timeout=timeout
        )
        if resp.status_code == 200:
            data = resp.json()
            b64 = data.get("data", [{}])[0].get("b64_json", "")
            if b64: return True, base64.b64decode(b64)
            url = data.get("data", [{}])[0].get("url", "")
            if url: return True, {"url": url}
        # If images endpoint returns non-200, it might not exist for this provider
    except Exception:
        pass

    return False, f"No image generated (model: {image_model})"

def main():
    parser = argparse.ArgumentParser(description="HelloMultimodal Image Generation")
    parser.add_argument("--prompt", required=True, help="Generation prompt")
    parser.add_argument("--output", default="./output/generated.png", help="Output path")
    parser.add_argument("--channel", type=int, default=None, help="Force specific channel")
    args = parser.parse_args()

    channels, defaults = load_channels()
    timeout = defaults.get("timeout_seconds", 300)
    retry_count = defaults.get("retry_count", 2)

    targets = [c for c in channels if args.channel is None or c["priority"] == args.channel]
    if not targets:
        print(json.dumps({"error": "No matching generate channels"}), file=sys.stderr)
        sys.exit(1)

    errors = []
    for channel in targets:
        for attempt in range(retry_count + 1):
            label = f"{channel['name']} ({channel['model']})"
            if attempt > 0:
                print(f"Retry {attempt} with {label}...", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"Trying {label}...", file=sys.stderr)

            ok, result = try_channel(channel, args.prompt, timeout)
            if ok:
                out = Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(result, bytes):
                    out.write_bytes(result)
                    print(f"Image saved to {args.output} ({len(result)} bytes)", file=sys.stderr)
                elif isinstance(result, dict) and "url" in result:
                    print(f"Image URL: {result['url']}", file=sys.stderr)
                    out.with_suffix(".json").write_text(json.dumps({"url": result["url"], "_channel": channel["name"]}, ensure_ascii=False, indent=2), encoding="utf-8")
                return
            errors.append(f"{label}: {result}")
            break

    print(json.dumps({"error": "All channels failed", "details": errors}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
