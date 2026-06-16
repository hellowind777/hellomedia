# HelloMultimodal

> Visual understanding & image generation skill for Claude Code. Multi-provider, multi-channel fallback.
> **v0.3.2** — Pure stdlib, zero external dependencies.

[English](#english) | [中文](#中文)

---

> 🏅 This project is linked & recognized by the [LINUX DO](https://linux.do) community.

---

## English

A Claude Code skill that provides visual understanding and image generation capabilities through external multimodal APIs. **Fully self-contained — zero external dependencies, pure Python stdlib, runs anywhere.**

### Design Philosophy

This skill follows the official Anthropic Agent Skills standard: it describes **when it should be invoked** without constraining or commenting on the host model's capabilities. Trigger logic is based on message content (presence of images), not keywords. The host model tries native processing first; the skill handles the fallback when needed.

### Highlights

- **Message-driven activation** — triggers when user messages contain images, not by keyword matching
- **Try-first-then-fallback** — host model attempts native processing; skill steps in only when needed
- **Multi-provider vision** — GPT-4o, Kimi K2.6, MiniMax-M3, Claude Sonnet/Opus, Ollama, vLLM, and any OpenAI-compatible proxy
- **Multi-endpoint generation** — `responses` → `images` → `images-edits` → `chat` auto-fallback chain, plus SD WebUI (A1111) support
- **Pure stdlib** — both vision.py and generate.py use only the Python standard library
- **Safe output paths** — blocks writes to Desktop, Downloads, Documents, etc.; defaults to stdout for vision, `./output/` for generation
- **Windows UTF-8 support** — automatic stdout/stderr encoding fix at module level
- **Path normalization** — backslash-to-forward-slash for Windows shell compatibility

### Quick Start

```bash
cp config.example.json config.json
# Edit config.json with your API credentials
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### Supported Providers

#### Vision

| Provider | api_format | base_url | Model Example |
|----------|:---:|----------|---------------|
| OpenAI | openai | `https://api.openai.com/v1` | `gpt-4o` |
| Kimi (Moonshot) | openai | `https://api.moonshot.ai/v1` | `kimi-k2.6` |
| MiniMax | openai | `https://api.minimax.io/v1` | `MiniMax-M3` |
| Claude (Anthropic) | **anthropic** | `https://api.anthropic.com` | `claude-sonnet-4-20250514` |
| Ollama (local) | openai | `http://localhost:11434/v1` | `minicpm-v:latest` |
| vLLM / LocalAI | openai | `http://localhost:8000/v1` | `Qwen2.5-VL-7B` |

Any OpenAI-compatible proxy works with `api_format: "openai"`.

#### Image Generation

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
python scripts/vision.py --image screenshot.png --prompt "Describe this UI"
python scripts/vision.py --image-dir ./pages/ --prompt "Extract key info"
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

#### Image Generation

```bash
python scripts/generate.py --prompt "A safety infographic" --output ./output/chart.png
python scripts/generate.py --prompt "oil painting style" --image ./sketch.png --output ./output/painting.png
python scripts/generate.py --prompt "fantasy concept" --count 3 --output ./output/monster.png
python scripts/generate.py --endpoint-mode sd-webui --prompt "a cat" --output ./output/cat.png
python scripts/generate.py --prompt "test" --dry-run
```

### Routing

| Task | Behavior |
|------|----------|
| Image in message | Host model tries first. If it can't process the image, the skill handles it via an external vision API. |
| Image generation | Always handled by the skill. |

### Configuration

Each channel in `config.json` supports:

| Field | Description |
|-------|------------|
| `api_key` / `image_api_key` | Separate credentials for vision vs generation |
| `model` / `image_model` | Different models for different tasks |
| `responses_model` / `chat_model` | Model overrides for specific endpoints |
| `image_base_url` | Separate base URL for image generation |
| `api_format` | `openai` (default), `anthropic` (Claude native), `sd-webui` (A1111) |
| `vision` / `generate` | Enable/disable capabilities per channel |
| `priority` | Lower = tried first, auto-fallback on failure |

### Repository

```text
hello-multimodal/
├── SKILL.md              # Skill definition for Claude Code
├── README.md
├── LICENSE
├── VERSION
├── config.example.json   # Provider templates
├── config.json           # Your credentials (gitignored)
├── .gitignore
└── scripts/
    ├── vision.py         # Visual understanding (stdlib only)
    └── generate.py       # Image generation (stdlib only)
```

### Changelog

#### v0.3.2
- **SKILL.md**: rewritten to follow official Anthropic Agent Skills standard — third-person, message-driven activation, no keyword matching, no model capability commentary
- **SKILL.md**: simplified body — removed proxy-mapping, capability-probe, and error-recognition sections that constrained the host model
- **vision.py**: module-level UTF-8 stdout/stderr encoding fix for Windows (avoids GBK errors)
- **vision.py**: path normalization — backslash → forward slash for Windows shell compatibility
- **vision.py**: graceful error on missing image files (structured JSON error instead of FileNotFoundError crash)
- **generate.py**: module-level UTF-8 encoding fix
- **generate.py**: reference image path normalization
- **vision.py + generate.py**: output path safety — blocks writes to Desktop, Downloads, Documents, etc.
- **SKILL.md**: Windows path guidance note added

#### v0.3.1
- Anthropic native Messages API support, stdlib-only refactor, webp/gif support, SD WebUI support, browser UA, semantic error matching, 10 provider templates

#### v0.2.1
- Timeout calibration, Retry-After header support, 402 fast-fail, bugfixes

#### v0.2.0
- gpt-image-2 `--thinking` and `--seed`, multi-image `--count`, endpoint mode, dry-run, quiet mode, semantic layout analysis

#### v0.1.0
- Initial release: visual understanding + image generation via config.json channels

### License

Apache 2.0 — see [LICENSE](./LICENSE)

---

## 中文

一个 Claude Code 技能，通过外部多模态 API 提供视觉理解和图片生成能力。**完全自包含——零外部依赖，纯 Python 标准库，随处可跑。**

### 设计哲学

遵循 Anthropic 官方 Agent Skills 标准：描述**何时应被调用**，不约束或评论主模型的能力。基于消息内容（图片存在性）触发，不依赖关键词匹配。主模型优先尝试原生处理，必要时技能介入。

### 亮点

- **消息驱动激活** — 用户消息含图片即触发，不靠关键词匹配
- **先试后降级** — 主模型先尝试，不行再由技能接管
- **多渠道视觉** — GPT-4o、Kimi K2.6、MiniMax-M3、Claude Sonnet/Opus、Ollama、vLLM 及任意 OpenAI 兼容代理
- **多端点生图** — `responses` → `images` → `images-edits` → `chat` 自动 fallback 链，支持 SD WebUI (A1111)
- **纯标准库** — vision.py 和 generate.py 仅依赖 Python 标准库
- **安全输出路径** — 阻止写入桌面、下载、文档等目录；视觉默认 stdout，生图默认 `./output/`
- **Windows UTF-8** — 模块级自动 stdout/stderr 编码修复
- **路径归一化** — Windows 反斜杠自动转正斜杠

### 快速开始

```bash
cp config.example.json config.json
# 编辑 config.json 填入 API 凭据
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

任意 OpenAI 兼容代理使用 `api_format: "openai"` 即可。

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
python scripts/vision.py --image screenshot.png --prompt "描述这张UI"
python scripts/vision.py --image-dir ./pages/ --prompt "提取关键信息"
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

#### 图片生成

```bash
python scripts/generate.py --prompt "施工安全信息图" --output ./output/chart.png
python scripts/generate.py --prompt "变成油画风格" --image ./sketch.png --output ./output/painting.png
python scripts/generate.py --prompt "幻想生物概念" --count 3 --output ./output/monster.png
python scripts/generate.py --endpoint-mode sd-webui --prompt "一只猫" --output ./output/cat.png
python scripts/generate.py --prompt "test" --dry-run
```

### 路由

| 场景 | 行为 |
|------|------|
| 消息含图片 | 主模型先尝试，无法处理时由技能通过外部视觉 API 接管 |
| 要求生图 | 始终由技能处理 |

### 配置

每个渠道支持：

| 字段 | 说明 |
|-------|------|
| `api_key` / `image_api_key` | 视觉/生图分离凭据 |
| `model` / `image_model` | 不同任务用不同模型 |
| `responses_model` / `chat_model` | 特定端点模型覆盖 |
| `image_base_url` | 生图专用 base URL |
| `api_format` | `openai`（默认）、`anthropic`（Claude 原生）、`sd-webui`（A1111） |
| `vision` / `generate` | 按渠道启停能力 |
| `priority` | 越小越优先，失败自动 fallback |

### 仓库结构

```text
hello-multimodal/
├── SKILL.md              # Claude Code 技能定义
├── README.md
├── LICENSE
├── VERSION
├── config.example.json   # 提供商模板
├── config.json           # 凭据（已 gitignored）
├── .gitignore
└── scripts/
    ├── vision.py         # 视觉理解（纯标准库）
    └── generate.py       # 图片生成（纯标准库）
```

### 更新日志

#### v0.3.2
- **SKILL.md**：遵循 Anthropic 官方 Agent Skills 标准重写 — 第三人称、消息驱动激活、无关键词匹配、不评论模型能力
- **SKILL.md**：精简 body — 移除代理映射、capability-probe、报错识别等约束主模型的章节
- **vision.py**：模块级 UTF-8 编码修复（Windows GBK 错误）
- **vision.py**：路径归一化 — 反斜杠自动转正斜杠
- **vision.py**：图片不存在时优雅报错（JSON 错误取代 FileNotFoundError 崩溃）
- **generate.py**：模块级 UTF-8 编码修复
- **generate.py**：参考图路径归一化
- **vision.py + generate.py**：输出路径安全 — 阻止写入桌面/下载/文档等目录
- **SKILL.md**：新增 Windows 路径注意事项

#### v0.3.1
- Anthropic 原生 Messages API、纯标准库重构、webp/gif 支持、SD WebUI、浏览器 UA、语义错误匹配、10 提供商模板

#### v0.2.1
- 超时校准、Retry-After 头支持、402 快速失败、bug 修复

#### v0.2.0
- gpt-image-2 `--thinking` 和 `--seed`、多图 `--count`、端点模式、调试模式、语义画幅分析

#### v0.1.0
- 初始版本：视觉理解 + 图片生成

### 许可证

Apache 2.0 — 详见 [LICENSE](./LICENSE)

---

> 🏅 此项目已链接认可 [LINUX DO](https://linux.do) 社区。
