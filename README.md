# HelloMultimodal

> Visual understanding & image generation skill for Claude Code. Multi-channel fallback via config.json.

[English](#english) | [中文](#中文)

---

## English

A Claude Code skill that routes visual understanding and image generation tasks to configured multimodal models when the default model lacks these capabilities.

### Features

- **Visual Understanding**: Analyze screenshots, diagrams, embedded images, documents
- **Image Generation**: Create illustrations, charts, and diagrams via dedicated image models
- **Multi-Channel Fallback**: Configure up to 3 API channels with automatic priority-based fallback
- **Capability-Probe Routing**: Routes based on actual API capability, not model name (proxy-safe)
- **HelloImage Engine**: Image generation delegates to helloimage for full multi-endpoint fallback (responses → chat → images → edits)
- **Natural Language Sizing**: Detects size/ratio from prompts (e.g., "1920x1080 banner", "16:9 chart", "vertical poster")

### Quick Start

```bash
# 1. Copy template config
cp config.example.json config.json

# 2. Edit config.json with your API credentials
# 3. Link to Claude Code
ln -s $(pwd) ~/.claude/skills/hello-multimodal
```

### Usage

```bash
# Vision analysis
python scripts/vision.py --image screenshot.png --prompt "Describe this UI"

# Batch analysis
python scripts/vision.py --image-dir ./pages/ --prompt "Extract key info"

# Image generation (via helloimage engine)
python scripts/generate.py --prompt "A construction safety infographic" --output ./chart.png
```

### Routing Rules

| Task | Main Model Has Capability | Main Model Lacks Capability |
|------|--------------------------|---------------------------|
| Visual Understanding | Main model handles directly | → hello-multimodal |
| Image Generation | → Always hello-multimodal | → hello-multimodal |

### Configuration

See `config.example.json` for channel templates. Each channel supports:

- `api_key` / `image_api_key`: Separate credentials for vision vs generation
- `model` / `image_model`: Different models for different tasks
- `vision` / `generate`: Enable/disable capabilities per channel
- `priority`: Lower = tried first, auto-fallback on failure

### License

Apache 2.0 — see [LICENSE](./LICENSE)

---

## 中文

一个 Claude Code 技能，当默认模型不具备视觉理解或图片生成能力时，自动路由到配置的多模态模型。

### 功能

- **视觉理解**：分析截图、流程图、嵌入图片、文档
- **图片生成**：通过专用生图模型生成插图、图表、配图
- **多渠道 Fallback**：最多配置 3 个 API 渠道，按优先级自动切换
- **能力探测路由**：基于实际 API 能力而非模型名称判断（代理映射安全）
- **HelloImage 引擎**：生图委托 helloimage 实现全端点 fallback（responses → chat → images → edits）
- **自然语言尺寸**：从提示词中自动识别尺寸/比例

### 快速开始

```bash
# 1. 复制模板配置
cp config.example.json config.json

# 2. 编辑 config.json 填入你的 API 凭据
# 3. 链接到 Claude Code
ln -s $(pwd) ~/.claude/skills/hello-multimodal
```

### 使用

```bash
# 视觉分析
python scripts/vision.py --image screenshot.png --prompt "描述这张UI"

# 批量分析
python scripts/vision.py --image-dir ./pages/ --prompt "提取关键信息"

# 图片生成（通过 helloimage 引擎）
python scripts/generate.py --prompt "一张施工安全信息图" --output ./chart.png
```

### 路由规则

| 需求 | 主模型有能力 | 主模型无能力 |
|------|------------|------------|
| 视觉理解 | 主模型直接处理 | → hello-multimodal |
| 图片生成 | → 始终 hello-multimodal | → hello-multimodal |

### 许可证

Apache 2.0 — 详见 [LICENSE](./LICENSE)
