#!/usr/bin/env python3
"""
HelloMultimodal — Image generation engine.
Delegates to helloimage for full multi-endpoint fallback capabilities.
Uses config.json for channel credentials.
"""

import base64, json, os, sys, argparse, time, subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
HELLOIMAGE_SCRIPT = Path("D:/GitHub/dev/skills/helloimage/scripts/helloimage.py")

# Natural language size patterns
SIZE_PATTERNS = [
    (r'\b(\d{3,4})[x×](\d{3,4})\b', lambda m: f"{m[1]}x{m[2]}" ),
    (r'\b(\d+):(\d+)\s*(?:ratio|比例)?\b', lambda m: f"{m[1]}:{m[2]}" ),
    (r'\b(portrait|vertical|竖屏|纵向|竖版)\b', lambda _: "portrait"),
    (r'\b(landscape|horizontal|横屏|横向|横版)\b', lambda _: "landscape"),
    (r'\b(square|方形|正方形)\b', lambda _: "square"),
    (r'\b(banner|横幅|banner图)\b', lambda _: "landscape"),
    (r'\b(poster|海报)\b', lambda _: "portrait"),
    (r'\b(widescreen|宽屏|宽幅)\b', lambda _: "21:9"),
]

def parse_size_from_prompt(prompt):
    import re
    for pattern, resolver in SIZE_PATTERNS:
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m: return resolver(m)
    return None

def load_channels():
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        print(f"config.json not found at {cfg_path}", file=sys.stderr)
        sys.exit(1)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    channels = [c for c in cfg.get("channels", []) if c.get("generate")]
    channels.sort(key=lambda c: c.get("priority", 99))
    return channels, cfg.get("defaults", {})

def try_channel_helloimage(channel, prompt, output_path, size, timeout):
    """Use helloimage.py engine — gets all its multi-endpoint fallback for free."""
    img_key = channel.get("image_api_key") or channel["api_key"]
    img_base = channel.get("image_base_url") or channel["base_url"]
    image_model = channel.get("image_model") or channel["model"]

    if not img_key:
        return False, "No API key configured"

    if not HELLOIMAGE_SCRIPT.exists():
        return False, "helloimage script not found"

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = img_key
    env["GPT_BASE_URL"] = img_base
    env["OPENAI_IMAGE_MODEL"] = image_model

    cmd = [
        sys.executable, str(HELLOIMAGE_SCRIPT),
        "--prompt", prompt,
        "--output", str(output_path),
        "--size", size,
        "--timeout", str(timeout),
    ]

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout + 30)
        if result.returncode == 0 and output_path.exists():
            return True, output_path.read_bytes()
        err = result.stderr.strip() or result.stdout.strip()
        return False, err[:300] if err else f"Exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"Timeout after {timeout}s"
    except Exception as e:
        return False, str(e)

def try_channel_direct(channel, prompt, timeout):
    """Fallback: direct /v1/images/generations call (when helloimage unavailable)."""
    import requests
    img_key = channel.get("image_api_key") or channel["api_key"]
    img_base = channel.get("image_base_url") or channel["base_url"]
    image_model = channel.get("image_model") or channel["model"]

    if not img_key:
        return False, "No API key"

    headers = {"Authorization": f"Bearer {img_key}", "Content-Type": "application/json"}
    size = parse_size_from_prompt(prompt) or "1024x1024"

    try:
        resp = requests.post(
            f"{img_base}/v1/images/generations", headers=headers,
            json={"model": image_model, "prompt": prompt, "n": 1, "size": size.replace(" ",""), "response_format": "b64_json"},
            timeout=timeout
        )
        if resp.status_code == 200:
            data = resp.json()
            b64 = data.get("data", [{}])[0].get("b64_json", "")
            if b64: return True, base64.b64decode(b64)
    except Exception as e:
        return False, str(e)

    return False, "No image data"

def main():
    parser = argparse.ArgumentParser(description="HelloMultimodal Image Generation (powered by helloimage engine)")
    parser.add_argument("--prompt", required=True, help="Generation prompt")
    parser.add_argument("--output", default="./output/generated.png", help="Output path")
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--size", default=None, help="Override auto-detected size")
    parser.add_argument("--timeout", type=int, default=None)
    args = parser.parse_args()

    channels, defaults = load_channels()
    timeout = args.timeout or defaults.get("timeout_seconds", 300)
    retry_count = defaults.get("retry_count", 2)
    size = args.size or parse_size_from_prompt(args.prompt) or "1024x1024"

    targets = [c for c in channels if args.channel is None or c["priority"] == args.channel]
    if not targets:
        print(json.dumps({"error": "No matching generate channels"}), file=sys.stderr)
        sys.exit(1)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    errors = []
    for channel in targets:
        for attempt in range(retry_count + 1):
            label = f"{channel['name']} ({channel.get('image_model') or channel['model']})"
            if attempt > 0:
                print(f"Retry {attempt}/{retry_count} with {label}...", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"Trying {label}...", file=sys.stderr)

            # Primary: helloimage engine (responses→chat→images→edits multi-fallback)
            ok, result = try_channel_helloimage(channel, args.prompt, out, size, timeout)
            engine = "helloimage"

            # Fallback: direct API call
            if not ok:
                ok, result = try_channel_direct(channel, args.prompt, timeout)
                engine = "direct"

            if ok:
                if isinstance(result, bytes):
                    out.write_bytes(result)
                    print(f"Image saved to {args.output} ({len(result)} bytes, via {engine})", file=sys.stderr)
                return
            errors.append(f"{label}: {result}")
            break

    print(json.dumps({"error": "All channels failed", "details": errors}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
