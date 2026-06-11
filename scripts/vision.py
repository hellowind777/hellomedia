#!/usr/bin/env python3
"""
HelloExpert Multimodal — Vision analysis via GPT-5.4
Routes visual tasks to multimodal model when main model lacks vision.
"""

import base64, json, os, sys, argparse, time
from pathlib import Path

def load_config():
    config = {}
    paths = [Path.home() / ".helloexpert" / "gpt_api.txt", Path(os.getcwd()) / "gpt_api.txt"]
    for config_path in paths:
        if config_path.exists():
            for line in config_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for sep in ("：", "=", ": "):
                    if sep in line:
                        key, val = line.split(sep, 1)
                        config[key.strip().strip('"').strip("'")] = val.strip().strip('"').strip("'")
                        break
            break
    return config

def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def vision_request(api_key, base_url, model, images, prompt, max_tokens=4096):
    import requests
    content = [{"type": "text", "text": prompt}]
    for img_path in images:
        b64 = encode_image(img_path)
        ext = os.path.splitext(img_path)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "bmp": "image/bmp", "tiff": "image/tiff"}.get(ext, "image/png")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}})

    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens},
        timeout=300
    )
    print(f"Status: {resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        print(f"Response: {resp.text[:500]}", file=sys.stderr)
    return resp.json() if resp.text else {"error": f"Empty response (status {resp.status_code})"}

def main():
    parser = argparse.ArgumentParser(description="HelloExpert Vision Analysis")
    parser.add_argument("--image", help="Single image path")
    parser.add_argument("--image-dir", help="Directory of images")
    parser.add_argument("--prompt", required=True, help="Analysis prompt")
    parser.add_argument("--output", default="-", help="Output file (default: stdout)")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()

    config = load_config()
    api_key = config.get("api-key", config.get("api_key", os.environ.get("GPT_API_KEY", "")))
    base_url = config.get("base_url", config.get("base-url", "https://api-cn.hi-code.cc"))
    model = config.get("model", "gpt-5.4")

    if not api_key:
        print(json.dumps({"error": "No API key found. Set in gpt_api.txt or GPT_API_KEY env."}), file=sys.stderr)
        sys.exit(1)

    # Collect images
    images = []
    if args.image:
        images.append(args.image)
    if args.image_dir:
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff"):
            images.extend(str(p) for p in Path(args.image_dir).glob(ext))
        images.sort()

    if not images:
        print(json.dumps({"error": "No images provided"}), file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing {len(images)} image(s) with {model}...", file=sys.stderr)
    result = vision_request(api_key, base_url, model, images, args.prompt, args.max_tokens)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(output)
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Saved to {args.output}", file=sys.stderr)

if __name__ == "__main__":
    main()
