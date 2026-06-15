# HelloMultimodal

> Visual understanding & image generation skill for Claude Code. Multi-provider, multi-channel fallback.
> **v0.3.1** — Pure stdlib, zero external dependencies.

[English](#english) | [中文](#中文)

---

> 🏅 This project is linked & recognized by the [LINUX DO](https://linux.do) community.

---

## English

A Claude Code skill that routes visual understanding and image generation tasks to configured multimodal models when the default model lacks these capabilities. **Fully self-contained — zero external dependencies, pure Python stdlib, runs anywhere.**

### Highlights (v0.3.0+)

- **10+ providers out of the box** — GPT-4o, Kimi K2.5/K2.6, MiniMax-M3, Claude Sonnet/Opus, Ollama, vLLM, and more
- **Semantic error matching** — auto-detects vision failure across any language (Chinese, English, Japanese, etc.) and any HTTP status code
- **Local image generation** — Stable Diffusion WebUI (A1111) via `/sdapi/v1/txt2img` and `/sdapi/v1/img2img`
- **Browser User-Agent** — avoids Cloudflare 403 blocks on public proxy sites
- **Pure stdlib** — both vision.py and generate.py use only the Python standard library

### Features

#### Visual Understanding
- **10+ vision providers**: OpenAI, Kimi (Moonshot), MiniMax, Claude (Anthropic native), Ollama, vLLM/LocalAI, and any OpenAI-compatible proxy
- Two API formats: `openai` (default, `/v1/chat/completions`) and `anthropic` (Claude native `/v1/messages`)
- Single image analysis and batch directory scan (png, jpg, jpeg, bmp, tiff, webp, gif)
- Multi-channel auto-fallback by priority — each channel gets one attempt, then next
- Capability-probe routing based on actual API response, not model name

#### Image Generation (via `generate.py`)
- **4-endpoint auto-fallback**: `responses` → `images` → `images-edits` → `chat`
- **SD WebUI (A1111) support** — `--endpoint-mode sd-webui` for local Stable Diffusion
- Double payload degradation within each endpoint: full-format → minimal fallback
- Dual URL variant probing: `/v1/...` → plain path for local proxy compatibility
- Semantic layout analysis: auto-selects optimal canvas ratio via lightweight LLM call
- gpt-image-2 native features: `--thinking` reasoning budget, `--seed` for semi-deterministic output
- Reference image editing: multipart → JSON auto-fallback
- Multi-image generation: `--count N` serial generation with per-image independent timeout
- Adaptive sizing, cross-request cooldown, permanent error fast-fail

#### General
- Cross-channel API key isolation (`image_api_key` / `api_key` separation)
- Retry with exponential backoff + jitter per channel
- Configurable timeout (auto-scaled by output resolution)
- Browser User-Agent on all requests (avoids Cloudflare blocking)

### Quick Start

```bash
# 1. Copy template config
cp config.example.json config.json

# 2. Edit config.json with your API credentials
# 3. Link to Claude Code
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### Supported Providers

#### Vision Providers

| Provider | api_format | base_url | Model Example |
|----------|:---:|----------|---------------|
| OpenAI | openai | `https://api.openai.com/v1` | `gpt-4o` |
| Kimi (Moonshot) | openai | `https://api.moonshot.ai/v1` | `kimi-k2.6` |
| MiniMax | openai | `https://api.minimax.io/v1` | `MiniMax-M3` |
| Claude (Anthropic) | **anthropic** | `https://api.anthropic.com` | `claude-sonnet-4-20250514` |
| Ollama (local) | openai | `http://localhost:11434/v1` | `minicpm-v:latest` |
| vLLM / LocalAI | openai | `http://localhost:8000/v1` | `Qwen2.5-VL-7B` |

Any OpenAI-compatible proxy (硅基流动, 火山引擎, etc.) works with `api_format: "openai"`.

#### Image Generation Providers

| Provider | endpoint_mode | base_url |
|----------|:---:|----------|
| OpenAI / GPT-image | auto | `https://api.openai.com` |
| AI/ML API (Nano Banana Pro) | images | `https://api.aimlapi.com/v1` |
| fal.ai (Nano Banana Pro) | images | `https://fal.run` |
| **SD WebUI (A1111)** | **sd-webui** | `http://localhost:7860` |

See `config.example.json` for complete channel templates.

### Usage

#### Vision Analysis

```bash
# Single image
python scripts/vision.py --image screenshot.png --prompt "Describe this UI"

# Batch analysis
python scripts/vision.py --image-dir ./pages/ --prompt "Extract key info from each page"

# Force specific channel
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."

# Output to file (default stdout)
python scripts/vision.py --image ./img.png --prompt "..." --output ./result.json
```

#### Image Generation

```bash
# Basic text-to-image
python scripts/generate.py --prompt "A construction safety infographic" --output ./chart.png

# Long prompt from file
python scripts/generate.py --prompt-file ./prompts/design.txt --output ./design.png

# Prompt from stdin
cat ./prompts/scene.txt | python scripts/generate.py --prompt - --output ./scene.png

# Multiple images
python scripts/generate.py --prompt "fantasy creature concept" --count 3 --output ./creature.png

# Reference image editing
python scripts/generate.py --prompt "turn this sketch into a polished poster" --image ./sketch.png --output ./poster.png

# gpt-image-2 thinking mode
python scripts/generate.py --prompt "technical chart with precise labels" --thinking medium --output ./chart.png

# Deterministic output
python scripts/generate.py --prompt "a cat in a spacesuit" --seed 42 --output ./cat.png

# SD WebUI local generation
python scripts/generate.py --prompt "a cat in a spacesuit" --endpoint-mode sd-webui --output ./cat.png

# SD WebUI img2img
python scripts/generate.py --prompt "turn into oil painting" --image ./sketch.png --endpoint-mode sd-webui --output ./painting.png

# SD WebUI custom sampling
python scripts/generate.py --prompt "..." --endpoint-mode sd-webui --sd-steps 50 --sd-cfg-scale 12 --sd-sampler "Euler a" --output ./img.png

# 4K resolution (requires 4K-capable provider)
python scripts/generate.py --prompt "panoramic landscape" --max-resolution 4k --output ./wide.png

# Dry-run to inspect configuration
python scripts/generate.py --prompt "test" --dry-run

# Quiet mode
python scripts/generate.py --quiet --prompt "..." --output ./img.png
```

### Routing Rules

| Task | Main Model Has Capability | Main Model Lacks Capability |
|------|--------------------------|---------------------------|
| Visual Understanding | Main model handles directly | → hello-multimodal |
| Image Generation | → Always hello-multimodal | → hello-multimodal |

The skill uses **semantic error matching** — if the main model's response means "I can't process images" (in any language, any HTTP status code), the skill is auto-invoked.

### Configuration

See `config.example.json` for 10 pre-built channel templates. Each channel supports:

| Field | Description |
|-------|------------|
| `api_key` / `image_api_key` | Separate credentials for vision vs generation |
| `model` / `image_model` | Different models for different tasks |
| `responses_model` / `chat_model` | Model overrides for `/v1/responses` and `/v1/chat` fallback |
| `image_base_url` | Separate base URL for image generation |
| `api_format` | API protocol: `openai` (default), `anthropic` (Claude native), `sd-webui` (A1111) |
| `vision` / `generate` | Enable/disable capabilities per channel |
| `priority` | Lower = tried first, auto-fallback on failure |

### Repository Layout

```text
hello-multimodal/
├── SKILL.md              # Skill definition for Claude Code
├── README.md
├── LICENSE
├── VERSION
├── config.example.json   # 10-provider template — copy to config.json
├── config.json           # Your credentials (gitignored)
├── .gitignore
└── scripts/
    ├── vision.py         # Visual understanding (stdlib only)
    └── generate.py       # Image generation (stdlib only)
```

### Changelog

#### v0.3.1
- **vision.py**: Anthropic native Messages API support (`api_format: "anthropic"`)
- **vision.py**: refactored `requests` → stdlib `urllib` (zero external deps)
- **vision.py**: webp / gif format support added
- **vision.py**: fixed fake retry loop — now one attempt per channel as documented
- **vision.py**: `_normalize_base_url` — auto-strip trailing `/v1` to avoid double-path bug
- **generate.py**: Stable Diffusion WebUI (A1111) support via `--endpoint-mode sd-webui`
- **generate.py**: `--sd-steps`, `--sd-cfg-scale`, `--sd-sampler` parameters
- **generate.py**: Browser User-Agent on all HTTP requests (avoids Cloudflare 403)
- **SKILL.md**: semantic error matching (not keyword matching) for cross-language vision fallback
- **SKILL.md**: MUST-INVOKE directive descriptions for higher auto-trigger rate
- **SKILL.md**: provider compatibility quick-reference table
- **config.example.json**: 10 pre-built provider templates (OpenAI, Kimi, MiniMax, Claude, Ollama, vLLM, SD WebUI, Nano Banana Pro x2, Gemini-proxy)
- All channel names / URLs / keys sanitized in public documentation

#### v0.2.1
- `generate.py`: timeout calibration and Retry-After header support
- `generate.py`: 402 now stops fallback alongside 401/403
- `generate.py`: various bugfixes (model ID, error propagation, dry-run display)

#### v0.2.0
- `generate.py`: gpt-image-2 native `--thinking` and `--seed` support
- `generate.py`: permanent 4xx fast-fail, `--count` multi-image, `--endpoint-mode`, `--dry-run`, `--quiet`
- `generate.py`: semantic layout analysis, dual URL variant probing

#### v0.1.0
- Initial release: visual understanding + image generation via config.json channels

### License

Apache 2.0 — see [LICENSE](./LICENSE)

---

## 中文

一个 Claude Code 技能，当默认模型不具备视觉理解或图片生成能力时，自动路由到配置的多模态模型。**完全自包含——零外部依赖，纯 Python 标准库，随处可跑。**

### 亮点 (v0.3.0+)

- **10+ 提供商开箱即用** — GPT-4o、Kimi K2.5/K2.6、MiniMax-M3、Claude Sonnet/Opus、Ollama、vLLM 等
- **语义错误匹配** — 跨语言（中/英/日等）、跨 HTTP 状态码自动识别视觉能力缺失
- **本地生图** — Stable Diffusion WebUI (A1111) 支持
- **浏览器 UA** — 避免公益站 Cloudflare 403 拦截
- **纯标准库** — vision.py 和 generate.py 均仅依赖 Python 标准库

### 功能

#### 视觉理解
- **10+ 视觉提供商**：OpenAI、Kimi（月之暗面）、MiniMax、Claude（Anthropic 原生）、Ollama、vLLM/LocalAI 及任意 OpenAI 兼容代理
- 两种 API 格式：`openai`（默认，`/v1/chat/completions`）和 `anthropic`（Claude 原生 `/v1/messages`）
- 单图分析和批量目录扫描（支持 png/jpg/jpeg/bmp/tiff/webp/gif）
- 多渠道按优先级自动 fallback — 每渠道一次尝试，失败自动下一个
- 基于实际 API 响应的能力探测路由，不依赖模型名称

#### 图片生成（`generate.py`）
- **4 端点自动 fallback**：`responses` → `images` → `images-edits` → `chat`
- **SD WebUI (A1111) 本地支持** — `--endpoint-mode sd-webui`
- 每端点内双层 payload 降级
- 双 URL variant 探路（`/v1/...` → 裸路径）
- 语义画幅分析、gpt-image-2 推理模式、参考图编辑、多图生成
- 自适应尺寸、跨请求冷却、永久性错误快速失败

#### 通用
- 跨渠道密钥隔离（`image_api_key` / `api_key` 分离）
- 指数退避 + jitter 重试
- 可配置超时（按输出分辨率自动缩放）
- 所有 HTTP 请求携带浏览器 User-Agent

### 快速开始

```bash
# 1. 复制模板
cp config.example.json config.json

# 2. 编辑 config.json 填入 API 凭据
# 3. 链接到 Claude Code
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### 支持的提供商

#### 视觉理解

| 提供商 | api_format | base_url | 模型示例 |
|----------|:---:|----------|---------------|
| OpenAI | openai | `https://api.openai.com/v1` | `gpt-4o` |
| Kimi（月之暗面） | openai | `https://api.moonshot.ai/v1` | `kimi-k2.6` |
| MiniMax | openai | `https://api.minimax.io/v1` | `MiniMax-M3` |
| Claude（Anthropic） | **anthropic** | `https://api.anthropic.com` | `claude-sonnet-4-20250514` |
| Ollama（本地） | openai | `http://localhost:11434/v1` | `minicpm-v:latest` |
| vLLM / LocalAI | openai | `http://localhost:8000/v1` | `Qwen2.5-VL-7B` |

任意 OpenAI 兼容代理（硅基流动、火山引擎等）使用 `api_format: "openai"` 即可。

#### 图片生成

| 提供商 | endpoint_mode | base_url |
|----------|:---:|----------|
| OpenAI / GPT-image | auto | `https://api.openai.com` |
| AI/ML API（Nano Banana Pro） | images | `https://api.aimlapi.com/v1` |
| fal.ai（Nano Banana Pro） | images | `https://fal.run` |
| **SD WebUI (A1111)** | **sd-webui** | `http://localhost:7860` |

完整模板见 `config.example.json`。

### 使用

#### 视觉分析

```bash
# 单图
python scripts/vision.py --image screenshot.png --prompt "描述这张UI"

# 批量分析
python scripts/vision.py --image-dir ./pages/ --prompt "从每页提取关键信息"

# 指定渠道
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."

# 输出到文件（默认 stdout）
python scripts/vision.py --image ./img.png --prompt "..." --output ./result.json
```

#### 图片生成

```bash
# 基本文生图
python scripts/generate.py --prompt "施工安全信息图" --output ./chart.png

# 从文件读取长 prompt
python scripts/generate.py --prompt-file ./prompts/design.txt --output ./design.png

# 从 stdin 读取
cat ./prompts/scene.txt | python scripts/generate.py --prompt - --output ./scene.png

# 生成多张
python scripts/generate.py --prompt "幻想生物概念图" --count 3 --output ./creature.png

# 参考图编辑
python scripts/generate.py --prompt "把草图变成精致海报" --image ./sketch.png --output ./poster.png

# gpt-image-2 推理模式
python scripts/generate.py --prompt "带有精确标签的图表" --thinking medium --output ./chart.png

# 确定性输出
python scripts/generate.py --prompt "穿宇航服的猫" --seed 42 --output ./cat.png

# SD WebUI 本地生图
python scripts/generate.py --prompt "穿宇航服的猫" --endpoint-mode sd-webui --output ./cat.png

# SD WebUI 图生图
python scripts/generate.py --prompt "变成油画风格" --image ./sketch.png --endpoint-mode sd-webui --output ./painting.png

# SD WebUI 自定义采样
python scripts/generate.py --prompt "..." --endpoint-mode sd-webui --sd-steps 50 --sd-cfg-scale 12 --sd-sampler "Euler a" --output ./img.png

# 4K 分辨率
python scripts/generate.py --prompt "全景风景" --max-resolution 4k --output ./wide.png

# 调试配置
python scripts/generate.py --prompt "test" --dry-run

# 静默模式
python scripts/generate.py --quiet --prompt "..." --output ./img.png
```

### 路由规则

| 需求 | 主模型有能力 | 主模型无能力 |
|------|------------|------------|
| 视觉理解 | 主模型直接处理 | → hello-multimodal |
| 图片生成 | → 始终 hello-multimodal | → hello-multimodal |

技能使用**语义错误匹配** —— 主模型响应的语义为"无法处理图片"（不限语言、不限 HTTP 状态码）时自动触发。

### 配置

见 `config.example.json` 中的 10 个预制渠道模板。每个渠道支持：

| 字段 | 说明 |
|-------|------|
| `api_key` / `image_api_key` | 视觉/生图分离凭据 |
| `model` / `image_model` | 不同任务用不同模型 |
| `responses_model` / `chat_model` | `/v1/responses` 和 `/v1/chat` 端点模型覆盖 |
| `image_base_url` | 生图专用 base URL |
| `api_format` | API 协议：`openai`（默认）、`anthropic`（Claude 原生）、`sd-webui`（A1111） |
| `vision` / `generate` | 按渠道启停能力 |
| `priority` | 越小越优先，失败自动 fallback |

### 仓库结构

```text
hello-multimodal/
├── SKILL.md              # Claude Code 技能定义
├── README.md
├── LICENSE
├── VERSION
├── config.example.json   # 10 提供商模板 — 复制为 config.json
├── config.json           # 你的凭据（已 gitignored）
├── .gitignore
└── scripts/
    ├── vision.py         # 视觉理解（纯标准库）
    └── generate.py       # 图片生成（纯标准库）
```

### Changelog

#### v0.3.1
- **vision.py**：Anthropic 原生 Messages API 支持（`api_format: "anthropic"`）
- **vision.py**：重构 `requests` → stdlib `urllib`（零外部依赖）
- **vision.py**：新增 webp / gif 格式支持
- **vision.py**：修复假重试循环 — 每渠道一次尝试，与文档一致
- **vision.py**：`_normalize_base_url` — 自动去除尾部 `/v1` 避免双路径 bug
- **generate.py**：Stable Diffusion WebUI (A1111) 支持（`--endpoint-mode sd-webui`）
- **generate.py**：`--sd-steps`、`--sd-cfg-scale`、`--sd-sampler` 参数
- **generate.py**：所有 HTTP 请求携带浏览器 User-Agent（避免 Cloudflare 403）
- **SKILL.md**：语义错误匹配替代关键词匹配，跨语言视觉 fallback
- **SKILL.md**：MUST-INVOKE 指令式描述，提高自动触发率
- **SKILL.md**：提供商兼容性速查表
- **config.example.json**：10 个预制提供商模板
- 公开文档中所有渠道名称 / URL / 密钥已脱敏

#### v0.2.1
- `generate.py`：超时校准和 Retry-After 头支持
- `generate.py`：402 与 401/403 同等停止 fallback
- `generate.py`：多项 bug 修复

#### v0.2.0
- `generate.py`：gpt-image-2 原生 `--thinking` 和 `--seed` 支持
- `generate.py`：永久性 4xx 快速失败、`--count` 多图、`--endpoint-mode`、`--dry-run`、`--quiet`
- `generate.py`：语义画幅分析、双 URL variant 探路

#### v0.1.0
- 初始版本：视觉理解 + 图片生成，通过 config.json 多渠道调度

### 许可证

Apache 2.0 — 详见 [LICENSE](./LICENSE)

---

> 🏅 此项目已链接认可 [LINUX DO](https://linux.do) 社区。
