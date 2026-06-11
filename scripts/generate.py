#!/usr/bin/env python3
"""
HelloExpert Multimodal — Image generation via GPT-5.4 chat/completions
Generates report illustrations, charts, and diagrams for bid review reports.
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
                if not line or line.startswith("#"): continue
                for sep in ("：", "=", ": "):
                    if sep in line:
                        key, val = line.split(sep, 1)
                        config[key.strip().strip('"').strip("'")] = val.strip().strip('"').strip("'")
                        break
            break
    return config

def generate_image(api_key, base_url, model, prompt, size="1024x1024"):
    """Generate image via chat/completions (GPT-5.4 multimodal can output images)"""
    import requests

    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": f"Generate an image: {prompt}. Output the image directly."}],
            "max_tokens": 4096,
        },
        timeout=300
    )
    data = resp.json()

    # Try to extract image from response
    if "choices" in data:
        content = data["choices"][0]["message"]["content"]
        # Check if response contains base64 image data
        if "data:image" in content or content.startswith("/9j/") or content.startswith("iVBOR"):
            return {"type": "base64", "data": content, "model": model}
        # Check for image URL
        if "http" in content and (".png" in content or ".jpg" in content or ".webp" in content):
            return {"type": "url", "data": content, "model": model}

    return {"type": "text", "data": data, "model": model}

def main():
    parser = argparse.ArgumentParser(description="HelloExpert Image Generation")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--output", default="./output/generated.png", help="Output path")
    parser.add_argument("--size", default="1024x1024", help="Image size (default 1024x1024)")
    args = parser.parse_args()

    config = load_config()
    api_key = config.get("api-key", os.environ.get("GPT_API_KEY", ""))
    base_url = config.get("base_url", "https://api-cn.hi-code.cc")
    model = config.get("model", "gpt-5.4")

    if not api_key:
        print(json.dumps({"error": "No API key found"}), file=sys.stderr)
        sys.exit(1)

    print(f"Generating image with {model}...", file=sys.stderr)
    result = generate_image(api_key, base_url, model, args.prompt, args.size)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if result["type"] == "base64":
        data = result["data"]
        # Strip data URL prefix if present
        if data.startswith("data:image"):
            data = data.split(",", 1)[1]
        output_path.write_bytes(base64.b64decode(data))
        print(f"Image saved to {args.output}", file=sys.stderr)
    elif result["type"] == "url":
        print(f"Image URL: {result['data']}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"No image generated. Raw response saved.", file=sys.stderr)
        output_path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
