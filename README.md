# HelloMultimodal

> Visual understanding & image generation skill for Claude Code. Multi-channel fallback via config.json.
> **v0.2.0**

[English](#english) | [中文](#中文)

---

> 🏅 This project is linked & recognized by the [LINUX DO](https://linux.do) community.

---

## English

A Claude Code skill that routes visual understanding and image generation tasks to configured multimodal models when the default model lacks these capabilities. Fully self-contained — zero external dependencies, one config.json, runs anywhere.

### Features

#### Visual Understanding
- Single image analysis: screenshots, diagrams, embedded images, documents
- Batch image analysis via directory scan
- Multi-channel auto-fallback by priority
- Capability-probe routing based on actual API response, not model name (proxy-mapping safe)

#### Image Generation (via `generate.py`)
- **4-endpoint auto-fallback**: `responses` → `images` → `images-edits` → `chat`
- **Double payload degradation within each endpoint**: full-format → minimal fallback
- **Dual URL variant probing**: `/v1/...` → plain path for local proxy compatibility
- **Semantic layout analysis**: auto-selects optimal canvas ratio via lightweight LLM call when no explicit size/ratio is given
- **gpt-image-2 native features**: `--thinking` reasoning budget (off/low/medium/high), `--seed` for semi-deterministic output
- **Reference image editing**: multipart → JSON auto-fallback via responses / images-edits / chat
- **Multi-image generation**: `--count N` serial generation with per-image independent timeout
- **Adaptive sizing**: honors prompt-declared size, aspect ratio, or auto-infers via complexity heuristic
- **Cross-request cooldown**: prevents rate-limit cascading
- **Permanent error fast-fail**: 400/401/403 etc. fail immediately without wasting retries
- **Structured JSON output**: machine-readable results with full attempt trace

#### General
- All standard library only — no pip install required
- Cross-channel API key isolation (`image_api_key` / `api_key` separation)
- Retry with exponential backoff + jitter per channel
- Configurable timeout (auto-scaled by output resolution)

### Quick Start

```bash
# 1. Copy template config
cp config.example.json config.json

# 2. Edit config.json with your API credentials
# 3. Link to Claude Code
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### Usage

#### Vision Analysis

```bash
# Single image
python scripts/vision.py --image screenshot.png --prompt "Describe this UI"

# Batch analysis
python scripts/vision.py --image-dir ./pages/ --prompt "Extract key info from each page"

# Force specific channel
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

#### Image Generation

```bash
# Basic text-to-image
python scripts/generate.py --prompt "A construction safety infographic" --output ./chart.png

# Long prompt from file
python scripts/generate.py --prompt-file ./prompts/design.txt --output ./design.png

# Prompt from stdin
cat ./prompts/scene.txt | python scripts/generate.py --prompt - --output ./scene.png

# Generate multiple images
python scripts/generate.py --prompt "fantasy creature concept" --count 3 --output ./creature.png

# With reference image (editing / variation)
python scripts/generate.py --prompt "turn this sketch into a polished poster" --image ./sketch.png --output ./poster.png

# gpt-image-2 thinking mode for complex compositing
python scripts/generate.py --prompt "technical chart with precise labels and data" --thinking medium --output ./chart.png

# Deterministic output with seed
python scripts/generate.py --prompt "a cat in a spacesuit" --seed 42 --output ./cat.png

# Force specific endpoint (rarely needed — auto is sufficient)
python scripts/generate.py --prompt "..." --endpoint-mode responses --output ./img.png

# 4K resolution ceiling (requires 4K-capable provider)
python scripts/generate.py --prompt "panoramic landscape" --max-resolution 4k --output ./wide.png

# Dry-run to inspect configuration
python scripts/generate.py --prompt "test" --dry-run

# Quiet mode for scripting
python scripts/generate.py --quiet --prompt "..." --output ./img.png
```

### Routing Rules

| Task | Main Model Has Capability | Main Model Lacks Capability |
|------|--------------------------|---------------------------|
| Visual Understanding | Main model handles directly | → hello-multimodal |
| Image Generation | → Always hello-multimodal | → hello-multimodal |

### Configuration

See `config.example.json` for channel templates. Each channel supports:

| Field | Description |
|-------|------------|
| `api_key` / `image_api_key` | Separate credentials for vision vs generation |
| `model` / `image_model` | Different models for different tasks |
| `responses_model` / `chat_model` | Model overrides for /v1/responses and /v1/chat fallback |
| `vision` / `generate` | Enable/disable capabilities per channel |
| `priority` | Lower = tried first, auto-fallback on failure |

### Repository Layout

```text
hello-multimodal/
├── SKILL.md              # Skill definition for Claude Code
├── README.md
├── LICENSE
├── config.example.json   # Template — copy to config.json
├── config.json           # Your credentials (gitignored)
├── .gitignore
└── scripts/
    ├── vision.py         # Vision analysis engine
    └── generate.py       # Self-contained image generation engine
```

### Changelog

#### v0.2.0
- `generate.py`: gpt-image-2 native `--thinking` and `--seed` support
- `generate.py`: permanent 4xx fast-fail (no wasted retries)
- `generate.py`: `tool_choice: "auto"` for 2026 Responses API compatibility
- `generate.py`: `--count` multi-image serial generation
- `generate.py`: `--endpoint-mode`, `--responses-mode`, `--dry-run`, `--quiet`
- `generate.py`: semantic layout analysis with `--layout-analysis` / `--layout-min-confidence`
- `generate.py`: dual URL variant probing (v1 + plain) for local proxy compatibility
- `SKILL.md`: LLM-friendly decision guide for parameter selection
- `README.md`: comprehensive usage examples covering all features

#### v0.1.0
- Initial release: visual understanding + image generation via config.json channels

### License

Apache 2.0 — see [LICENSE](./LICENSE)

---

## 中文

一个 Claude Code 技能，当默认模型不具备视觉理解或图片生成能力时，自动路由到配置的多模态模型。**完全自包含——零外部依赖，一个 config.json，随处可跑。**

### 功能

#### 视觉理解
- 单图分析：截图、流程图、嵌入图片、文档
- 批量图片分析（目录扫描）
- 多渠道按优先级自动 fallback
- 基于实际 API 响应而非模型名称的能力探测路由（代理映射安全）

#### 图片生成（`generate.py`）
- **4 端点自动 fallback**：`responses` → `images` → `images-edits` → `chat`
- **每端点内双层 payload 降级**：完整格式 → 最小回退
- **双 URL variant 探路**：`/v1/...` → 裸路径，兼容本地代理
- **语义画幅分析**：无显式尺寸/比例时自动通过轻量 LLM 调用选最优画幅
- **gpt-image-2 原生特性**：`--thinking` 推理预算（off/low/medium/high），`--seed` 半确定性输出
- **参考图编辑**：multipart → JSON 自动回退（responses / images-edits / chat）
- **多图生成**：`--count N` 串行生成，每张独立 timeout
- **自适应尺寸**：优先 prompt 显式尺寸，其次比例，最后启发式推断
- **跨请求冷却**：防止限流雪崩
- **永久性错误快速失败**：400/401/403 等立即失败不浪费重试
- **结构化 JSON 输出**：机器可读结果含完整 attempt trace

#### 通用
- 纯标准库，无需 pip install
- 跨渠道密钥隔离（`image_api_key` / `api_key` 分离）
- 指数退避 + jitter 重试
- 可配置超时（按输出分辨率自动缩放）

### 快速开始

```bash
# 1. 复制模板配置
cp config.example.json config.json

# 2. 编辑 config.json 填入你的 API 凭据
# 3. 链接到 Claude Code
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### 使用

#### 视觉分析

```bash
# 单图
python scripts/vision.py --image screenshot.png --prompt "描述这张UI"

# 批量分析
python scripts/vision.py --image-dir ./pages/ --prompt "从每页提取关键信息"

# 指定渠道
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

#### 图片生成

```bash
# 基本文生图
python scripts/generate.py --prompt "一张施工安全信息图" --output ./chart.png

# 从文件读取长 prompt
python scripts/generate.py --prompt-file ./prompts/design.txt --output ./design.png

# 从 stdin 读取 prompt
cat ./prompts/scene.txt | python scripts/generate.py --prompt - --output ./scene.png

# 生成多张图片
python scripts/generate.py --prompt "幻想生物概念图" --count 3 --output ./creature.png

# 参考图编辑
python scripts/generate.py --prompt "把这张草图变成精致的海报" --image ./sketch.png --output ./poster.png

# gpt-image-2 推理模式（复杂合成）
python scripts/generate.py --prompt "带有精确标签和数据的图表" --thinking medium --output ./chart.png

# 确定性输出
python scripts/generate.py --prompt "穿宇航服的猫" --seed 42 --output ./cat.png

# 强制指定端点（极少需要，auto 已足够）
python scripts/generate.py --prompt "..." --endpoint-mode responses --output ./img.png

# 4K 分辨率上限
python scripts/generate.py --prompt "全景风景" --max-resolution 4k --output ./wide.png

# 调试配置
python scripts/generate.py --prompt "test" --dry-run

# 脚本静默模式
python scripts/generate.py --quiet --prompt "..." --output ./img.png
```

### 路由规则

| 需求 | 主模型有能力 | 主模型无能力 |
|------|------------|------------|
| 视觉理解 | 主模型直接处理 | → hello-multimodal |
| 图片生成 | → 始终 hello-multimodal | → hello-multimodal |

### 仓库结构

```text
hello-multimodal/
├── SKILL.md              # Claude Code 技能定义
├── README.md
├── LICENSE
├── config.example.json   # 模板——复制为 config.json
├── config.json           # 你的凭据（已 gitignored）
├── .gitignore
└── scripts/
    ├── vision.py         # 视觉理解引擎
    └── generate.py       # 独立生图引擎
```

### Changelog

#### v0.2.0
- `generate.py`：gpt-image-2 原生 `--thinking` 和 `--seed` 支持
- `generate.py`：永久性 4xx 快速失败（不浪费重试）
- `generate.py`：`tool_choice: "auto"` 兼容 2026 Responses API
- `generate.py`：`--count` 多图串行生成
- `generate.py`：`--endpoint-mode`、`--responses-mode`、`--dry-run`、`--quiet`
- `generate.py`：语义画幅分析（`--layout-analysis` / `--layout-min-confidence`）
- `generate.py`：双 URL variant 探路（v1 + plain）兼容本地代理
- `SKILL.md`：LLM 友好的参数决策指南
- `README.md`：覆盖所有功能的完整使用示例

#### v0.1.0
- 初始版本：视觉理解 + 图片生成，通过 config.json 多渠道调度

### 许可证

Apache 2.0 — 详见 [LICENSE](./LICENSE)

---

> 🏅 此项目已链接认可 [LINUX DO](https://linux.do) 社区。
