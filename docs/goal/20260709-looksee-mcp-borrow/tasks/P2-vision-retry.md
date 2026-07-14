# P2：vision 瞬时错误重试

## 目标

让 `vision.py` 在**同一渠道**内对瞬时失败（429、5xx、超时、连接错误）做有限次指数退避重试；对永久 4xx（401/402/403/404 等）不重试，直接记失败并进入下一渠道。

## 来源证据

- looksee-mcp `server.py` `_chat`（约 L135–167）：
  - `retries=3`，`attempt in range(retries + 1)`
  - `retryable = e.code in (429, 502, 503, 504)`
  - timeout/connection 类 Exception 也可重试
  - `time.sleep(2 ** attempt)`
- target `generate.py` 已有更完整的 `RETRY_STATUS_CODES` / `PERMANENT_4XX` / Retry-After（约 L53–55、L665–716）——**对齐 generate 语义，而不是简单复制 looksee**

## 具体步骤

### 1. 增加重试常量与包装

文件：`scripts/vision.py`

在 imports 中确保有 `time`：

```python
import base64, json, os, sys, argparse, urllib.request, urllib.error, socket, time
```

增加：

```python
RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
PERMANENT_4XX = {400, 401, 402, 403, 404, 405, 410, 413, 414, 415, 422}


def _retry_count(defaults):
    # reuse config defaults.retry_count (already used by generate.py)
    return int(defaults.get("retry_count", 2))
```

### 2. 把 HTTP 调用抽成可重试循环

文件：`scripts/vision.py`

改造 `_try_openai` 与 `_try_anthropic` 的请求段，模式如下（两处对称）：

```python
def _try_openai(channel, images, prompt, max_tokens, timeout, *, compress=True, retries=2):
    # ... build payload/body/headers/url as today, but use load_image_payload from P1 ...

    last_err = None
    for attempt in range(1, retries + 2):  # retries=2 → 最多 3 次尝试
        try:
            req = urllib.request.Request(
                f"{base}/v1/chat/completions", data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:300]
            last_err = {"error": f"HTTP {e.code}: {err_body}"}
            if e.code in PERMANENT_4XX:
                return False, last_err
            if e.code not in RETRY_STATUS_CODES or attempt > retries + 1:
                # fall through; loop condition handles max
                if attempt >= retries + 1 or e.code not in RETRY_STATUS_CODES:
                    return False, last_err
            # 429 Retry-After（若有）
            delay = 2 ** (attempt - 1)
            if e.code == 429 and hasattr(e, "headers") and e.headers:
                ra = e.headers.get("Retry-After")
                if ra:
                    try:
                        delay = max(delay, int(ra))
                    except ValueError:
                        pass
            print(f"[vision] {channel.get('name')}: HTTP {e.code}, retry in {delay}s "
                  f"({attempt}/{retries + 1})", file=sys.stderr)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            last_err = {"error": str(e)}
            if attempt >= retries + 1:
                return False, last_err
            delay = 2 ** (attempt - 1)
            print(f"[vision] {channel.get('name')}: network error, retry in {delay}s "
                  f"({attempt}/{retries + 1})", file=sys.stderr)
            time.sleep(delay)
    return False, last_err or {"error": "unknown"}
```

对 `_try_anthropic` 做同样结构（URL 仍为 `/v1/messages`，成功后的 content 归一化逻辑保持不变）。

### 3. 从 defaults 传入 retries

文件：`scripts/vision.py` `main()`：

```python
retries = _retry_count(defaults)
# ...
ok, result = try_channel(channel, images, args.prompt, max_tokens, timeout,
                         compress=not args.no_compress, retries=retries)
```

`try_channel` 签名扩展并下传。

### 4. 保持「不重试同一渠道」文档语义的澄清

原 `SKILL.md` 写：「失败自动下一个，不重试同一渠道」。

P2 之后应改为（在 **P4** 改文档）：

- 同一渠道内：对瞬时错误按 `retry_count` 重试
- 渠道耗尽重试或永久错误：切换下一 priority 渠道

本任务只改代码；文案在 P4。

## 安装依赖（如有）

无。

## 验证命令

```bash
python -c "import ast; ast.parse(open('scripts/vision.py',encoding='utf-8').read()); print('syntax_ok')"

# 静态检查：重试集合与 generate 对齐
python -c "
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('vision', 'scripts/vision.py')
v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
assert 429 in v.RETRY_STATUS_CODES
assert 401 in v.PERMANENT_4XX
assert 500 in v.RETRY_STATUS_CODES
print('retry_constants_ok')
"
```

可选：用本地 mock HTTP 测重试次数（若实施者愿加临时测试）；最低限度语法 + 常量即可。

## 完成标准

- [ ] 429/502/503/504/timeout 在同一渠道内会 sleep 后重试
- [ ] 401/403/402 等永久错误不重试，立即 fallback 下一渠道
- [ ] 重试次数来自 `defaults.retry_count`（默认 2 → 共 3 次尝试）
- [ ] stderr 有可读的 retry 日志
- [ ] 渠道级 fallback 循环（for channel in targets）仍保留
