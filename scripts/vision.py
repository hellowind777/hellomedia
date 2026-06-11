#!/usr/bin/env python3
"""
HelloMultimodal — Vision analysis with multi-channel fallback.
Reads config.json, tries channels by priority, falls back on failure.
"""

import base64, json, os, sys, argparse, time
from pathlib import Path

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

def try_channel(channel, images, prompt, max_tokens, timeout):
    """Try a single channel. Returns (success, result)."""
    import requests
    content = [{"type": "text", "text": prompt}]
    for img_path in images:
        b64 = encode_image(img_path)
        ext = os.path.splitext(img_path)[1].lower()
        mime_map = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","bmp":"image/bmp","tiff":"image/tiff"}
        mime = mime_map.get(ext, "image/png")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}})

    try:
        resp = requests.post(
            f"{channel['base_url']}/v1/chat/completions",
            headers={"Authorization": f"Bearer {channel['api_key']}", "Content-Type": "application/json"},
            json={"model": channel["model"], "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens},
            timeout=timeout
        )
        if resp.status_code == 200:
            return True, resp.json()
        return False, {"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return False, {"error": str(e)}

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
    retry_count = defaults.get("retry_count", 2)

    # Collect images
    images = []
    if args.image: images.append(args.image)
    if args.image_dir:
        for ext in ("*.png","*.jpg","*.jpeg","*.bmp","*.tiff"):
            images.extend(str(p) for p in Path(args.image_dir).glob(ext))
        images.sort()
    if not images:
        print(json.dumps({"error": "No images provided"}), file=sys.stderr)
        sys.exit(1)

    # Filter channels if forced
    targets = [c for c in channels if args.channel is None or c["priority"] == args.channel]
    if not targets:
        print(json.dumps({"error": "No matching channels"}), file=sys.stderr)
        sys.exit(1)

    # Try channels with fallback
    errors = []
    for channel in targets:
        for attempt in range(retry_count + 1):
            label = f"{channel['name']} ({channel['model']})"
            if attempt > 0:
                print(f"Retry {attempt}/{retry_count} with {label}...", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"Trying {label}...", file=sys.stderr)

            ok, result = try_channel(channel, images, args.prompt, max_tokens, timeout)
            if ok:
                result["_channel"] = channel["name"]
                result["_model"] = channel["model"]
                output = json.dumps(result, ensure_ascii=False, indent=2)
                if args.output == "-":
                    print(output)
                else:
                    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.output).write_text(output, encoding="utf-8")
                    print(f"Saved to {args.output}", file=sys.stderr)
                return
            errors.append(f"{label}: {result.get('error', 'unknown')}")
            break  # Don't retry same channel, try next

    # All channels failed
    print(json.dumps({"error": "All channels failed", "details": errors}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
