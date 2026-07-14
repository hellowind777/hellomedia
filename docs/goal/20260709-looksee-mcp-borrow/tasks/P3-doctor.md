# P3：doctor 连通性诊断脚本

## 目标

新增 `scripts/doctor.py`：读取 `config.json`，对每个启用了 `vision` 和/或 `generate` 的渠道做**只读、低成本**连通性探测，输出结构化 JSON，便于排障。

## 来源证据

- looksee-mcp `server.py` `doctor()`（约 L388–423）：
  - 报告 base_url / model / api_key_set
  - GET `{base}/models`
  - 对模型 POST 极短 chat「回复 OK」
- target 已有多渠道，需**按 channel 循环**，不能照搬单 env

## 具体步骤

### 1. 新建 `scripts/doctor.py`

文件：`scripts/doctor.py`（完整可运行实现如下，实施时可原样创建后按需微调）

```python
#!/usr/bin/env python3
"""HelloMedia — channel connectivity doctor (read-only probes)."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).parent.parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _normalize_base_url(raw: str) -> str:
    url = (raw or "").rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url


def load_config():
    cfg_path = SKILL_DIR / "config.json"
    if not cfg_path.exists():
        return None, f"config.json not found at {cfg_path}"
    return json.loads(cfg_path.read_text(encoding="utf-8")), None


def probe_models(base_url: str, api_key: str, timeout: float) -> dict:
    base = _normalize_base_url(base_url)
    url = f"{base}/v1/models"
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            ids = [m.get("id", "") for m in (data.get("data") or []) if isinstance(m, dict)]
            return {"ok": True, "http_status": getattr(resp, "status", 200), "model_count": len(ids), "sample_models": ids[:15]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "http_status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def probe_chat_openai(base_url: str, api_key: str, model: str, timeout: float) -> dict:
    if not model:
        return {"ok": False, "error": "empty model"}
    base = _normalize_base_url(base_url)
    url = f"{base}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 5,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return {"ok": True, "reply_preview": str(text)[:80]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "http_status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def probe_anthropic(base_url: str, api_key: str, model: str, timeout: float) -> dict:
    if not model:
        return {"ok": False, "error": "empty model"}
    base = _normalize_base_url(base_url)
    url = f"{base}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            texts = [
                b.get("text", "")
                for b in data.get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return {"ok": True, "reply_preview": "".join(texts)[:80]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "http_status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def diagnose_channel(ch: dict, timeout: float, *, probe_live: bool) -> dict:
    name = ch.get("name", "?")
    api_format = ch.get("api_format", "openai")
    base_url = ch.get("base_url", "")
    api_key = ch.get("api_key", "")
    report = {
        "name": name,
        "priority": ch.get("priority"),
        "api_format": api_format,
        "base_url": base_url,
        "api_key_set": bool(api_key),
        "vision_enabled": bool(ch.get("vision")),
        "generate_enabled": bool(ch.get("generate")),
        "model": ch.get("model") or "",
        "image_model": ch.get("image_model") or "",
    }
    if not base_url:
        report["status"] = "skip"
        report["error"] = "missing base_url"
        return report
    if not api_key and api_format != "sd-webui":
        report["status"] = "warn"
        report["error"] = "api_key empty"
        # still try models if open local endpoints
    if not probe_live:
        report["status"] = "dry"
        return report

    if api_format == "sd-webui":
        # light touch: GET base
        try:
            req = urllib.request.Request(base_url.rstrip("/") + "/", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                report["sd_webui"] = {"ok": True, "http_status": getattr(resp, "status", 200)}
                report["status"] = "ok"
        except Exception as e:
            report["sd_webui"] = {"ok": False, "error": str(e)}
            report["status"] = "fail"
        return report

    report["models_endpoint"] = probe_models(base_url, api_key, timeout)

    if ch.get("vision") and ch.get("model"):
        if api_format == "anthropic":
            report["vision_probe"] = probe_anthropic(base_url, api_key, ch["model"], timeout)
        else:
            report["vision_probe"] = probe_chat_openai(base_url, api_key, ch["model"], timeout)

    # generate: only cheap chat probe if image_model looks like a chat-capable id; skip heavy image gen
    if ch.get("generate") and (ch.get("image_model") or ch.get("model")):
        report["generate_probe_note"] = (
            "skipped live image generation (cost); models_endpoint + vision_probe only"
        )

    vision_ok = report.get("vision_probe", {}).get("ok")
    models_ok = report.get("models_endpoint", {}).get("ok")
    if vision_ok is True or models_ok is True:
        report["status"] = "ok" if (vision_ok is not False) else "degraded"
    elif vision_ok is False or models_ok is False:
        report["status"] = "fail"
    else:
        report["status"] = "unknown"
    return report


def main():
    parser = argparse.ArgumentParser(description="HelloMedia connectivity doctor")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print channel config summary without network calls",
    )
    parser.add_argument(
        "--vision-only",
        action="store_true",
        help="Only diagnose channels with vision:true",
    )
    args = parser.parse_args()

    cfg, err = load_config()
    if err:
        print(json.dumps({"ok": False, "error": err}, ensure_ascii=False, indent=2))
        sys.exit(1)

    channels = cfg.get("channels") or []
    defaults = cfg.get("defaults") or {}
    results = []
    for ch in sorted(channels, key=lambda c: c.get("priority", 99)):
        if args.vision_only and not ch.get("vision"):
            continue
        results.append(
            diagnose_channel(ch, args.timeout, probe_live=not args.dry_run)
        )

    out = {
        "ok": True,
        "skill_dir": str(SKILL_DIR),
        "defaults": defaults,
        "channel_count": len(results),
        "channels": results,
        "pillow_installed": _pillow_installed(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    # exit 1 if any live vision channel failed hard
    if not args.dry_run:
        hard_fails = [
            c for c in results
            if c.get("vision_enabled") and c.get("status") == "fail"
        ]
        if hard_fails and all(c.get("status") == "fail" for c in results if c.get("vision_enabled")):
            sys.exit(2)


def _pillow_installed() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    main()
```

### 2. 不把 doctor 做成 MCP tool

保持 CLI，与 vision/generate 一致。

### 3. 不写真实生图探测

避免费用与副作用；报告里用 `generate_probe_note` 说明。

## 安装依赖（如有）

无。可选 `Pillow` 仅影响报告字段 `pillow_installed`。

## 验证命令

```bash
cd D:/GitHub/dev/skills/hellomedia

python -c "import ast; ast.parse(open('scripts/doctor.py',encoding='utf-8').read()); print('syntax_ok')"

# dry-run 不访问网络
python scripts/doctor.py --dry-run
```

期望：stdout 为 JSON，`ok: true`，`channels` 为数组，含 `api_key_set` / `vision_enabled` 等。

若有真实 key：

```bash
python scripts/doctor.py --vision-only --timeout 20
```

## 完成标准

- [ ] `scripts/doctor.py` 存在且可执行
- [ ] `--dry-run` 零网络，退出码 0（有 config 时）
- [ ] 缺 config 时 JSON error 且非 0
- [ ] 支持 openai / anthropic 探测分支
- [ ] 不触发真实图片生成 API
- [ ] 报告含 `pillow_installed` 便于对照 P1
