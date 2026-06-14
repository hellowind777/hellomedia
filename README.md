# HelloMultimodal

> Visual understanding and image generation skill for Claude Code with multi-channel fallback.
> **v0.2.2**

[English](#english) | [中文](#中文)

---

> 🏅 This project is linked & recognized by the [LINUX DO](https://linux.do) community.

---

## English

HelloMultimodal routes vision and image-generation tasks to configured multimodal providers when the active Claude Code session model cannot do them well or cannot do them at all.

### The key limitation

If your current Claude Code chat model does **not** support image input, an image attached directly in chat can fail **before the skill is invoked**.

Typical error:

```text
No endpoints found that support image input
```

That means the fix is **not** "improve fallback after attachment". The fix is to avoid chat attachments for non-vision session models and use one of these inputs instead:

1. local image path
2. image directory
3. Windows clipboard screenshot

### Features

#### Vision analysis

- Single image analysis from a local file path
- Batch analysis from a directory
- Windows clipboard screenshot ingestion via `--clipboard`
- Multi-channel fallback by configured priority
- Structured JSON result with `_assistant_text` extracted when available
- Retry only on retryable transport / rate / server failures

#### Image generation

- Multi-endpoint fallback in `generate.py`
- Reference-image editing
- Multi-image generation
- `gpt-image-2` options such as `--thinking` and `--seed`

#### General

- Standard library only for `vision.py`
- One `config.json`
- Works well with proxy / relay providers

### Quick start

```bash
# 1. Copy template config
cp config.example.json config.json

# 2. Fill in your credentials
# 3. Link into Claude Code
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### Usage

#### Vision analysis

```bash
# Single local image
python scripts/vision.py --image "./screenshot.png" --prompt "Describe this UI"

# Directory of images
python scripts/vision.py --image-dir "./pages" --prompt "Extract key info from each page"

# Windows clipboard screenshot
python scripts/vision.py --clipboard --prompt "Describe the screenshot I just copied"

# Force a specific channel priority
python scripts/vision.py --channel 2 --image "./img.png" --prompt "..."
```

#### Recommended Claude Code skill invocations

```text
/hello-multimodal "D:\shots\bug.png" "Analyze this error screenshot"
/hello-multimodal "dir:D:\pages" "Review these page captures one by one"
/hello-multimodal "clipboard" "Check the screenshot I just copied"
```

#### Important: what not to do on non-vision chat models

Do **not** attach an image directly into the chat if your current session model lacks image support. The request can fail before Claude gets a chance to route to this skill.

Use a file path, `dir:<folder>`, or `clipboard` instead.

#### Image generation

```bash
# Basic text-to-image
python scripts/generate.py --prompt "A construction safety infographic" --output "./chart.png"

# Long prompt from file
python scripts/generate.py --prompt-file "./prompts/design.txt" --output "./design.png"

# Generate multiple images
python scripts/generate.py --prompt "fantasy creature concept" --count 3 --output "./creature.png"

# Reference image editing
python scripts/generate.py --prompt "turn this sketch into a polished poster" --image "./sketch.png" --output "./poster.png"

# gpt-image-2 thinking mode
python scripts/generate.py --prompt "technical chart with precise labels and data" --thinking medium --output "./chart.png"
```

### Routing rules

| Task | Session model supports vision | Session model does not support vision |
|------|-------------------------------|----------------------------------------|
| Vision understanding | Session model may handle it directly | Use hello-multimodal with path / dir / clipboard |
| Image generation | Always hello-multimodal | Always hello-multimodal |

### Configuration

See `config.example.json`.

| Field | Description |
|-------|-------------|
| `api_key` / `image_api_key` | Separate credentials for vision vs generation |
| `model` / `image_model` | Different models for different tasks |
| `vision` / `generate` | Enable capabilities per channel |
| `priority` | Lower value = tried first |

### Repository layout

```text
hello-multimodal/
├── SKILL.md
├── README.md
├── LICENSE
├── config.example.json
├── config.json
├── .gitignore
└── scripts/
    ├── vision.py
    ├── generate.py
    └── export_clipboard_image.ps1
```

### Changelog

#### v0.2.2

- clarified the core limitation: chat image attachments can fail before skill routing on non-vision session models
- added path / directory / clipboard guidance to the skill itself
- added `vision.py --clipboard`
- added Windows clipboard export helper
- changed `vision.py` to stay standard-library-only
- improved retry behavior to retry only retryable failures
- extracted `_assistant_text` from successful vision responses

#### v0.2.0

- `generate.py`: gpt-image-2 native `--thinking` and `--seed`
- `generate.py`: permanent 4xx fast-fail
- `generate.py`: `--count`, `--endpoint-mode`, `--responses-mode`, `--dry-run`, `--quiet`
- semantic layout analysis
- dual URL probing for proxy compatibility

### License

Apache 2.0 — see [LICENSE](./LICENSE)

---

## 中文

HelloMultimodal 用来把看图和生图任务路由到你在 `config.json` 里配置的多模态渠道，尤其适合当前 Claude Code 会话模型没有视觉能力，或者代理映射把视觉能力弄丢的场景。

### 先看核心限制

如果当前 Claude Code 会话模型**不支持图片输入**，你把图片直接作为聊天附件发出去，失败会发生在**技能触发之前**。

典型报错：

```text
No endpoints found that support image input
```

所以这个问题的关键不是“附件失败后再 fallback 到技能”，而是：

**非视觉会话模型下，不要直接发聊天附件图。**

改用下面三种输入：

1. 本地图片路径
2. 图片目录
3. Windows 剪贴板截图

### 功能

#### 视觉理解

- 支持本地单图分析
- 支持目录批量分析
- 支持 Windows 剪贴板截图 `--clipboard`
- 按 `priority` 自动切换视觉渠道
- 成功结果会尽量提取 `_assistant_text`
- 只在可重试错误上重试，不再无效重试

#### 图片生成

- 继续使用 `generate.py` 的多端点 fallback
- 支持参考图编辑、多图生成、`--thinking`、`--seed`

#### 通用

- `vision.py` 保持纯标准库
- 一个 `config.json` 即可运行
- 兼容代理 / 中继渠道

### 快速开始

```bash
# 1. 复制模板配置
cp config.example.json config.json

# 2. 填入你的凭据
# 3. 链接到 Claude Code
ln -s "$(pwd)" ~/.claude/skills/hello-multimodal
```

### 使用

#### 视觉分析

```bash
# 单图
python scripts/vision.py --image "./screenshot.png" --prompt "描述这张界面"

# 目录批量分析
python scripts/vision.py --image-dir "./pages" --prompt "逐张提取关键信息"

# Windows 剪贴板截图
python scripts/vision.py --clipboard --prompt "描述我刚复制的截图"

# 强制指定某个 priority 渠道
python scripts/vision.py --channel 2 --image "./img.png" --prompt "..."
```

#### 在 Claude Code 里推荐这样调用技能

```text
/hello-multimodal "D:\shots\bug.png" "帮我分析这张报错截图"
/hello-multimodal "dir:D:\pages" "把这些页面截图逐张分析"
/hello-multimodal "clipboard" "看看我刚复制的截图有什么问题"
```

#### 非视觉会话模型下不要这样用

不要把图片直接作为聊天附件发送给当前会话。

因为一旦当前会话模型不支持图片输入，请求会先报错，技能来不及接管。

正确做法是改传：

- 图片路径
- `dir:目录`
- `clipboard`

#### 图片生成

```bash
# 基本文生图
python scripts/generate.py --prompt "一张施工安全信息图" --output "./chart.png"

# 从文件读取长 prompt
python scripts/generate.py --prompt-file "./prompts/design.txt" --output "./design.png"

# 多图生成
python scripts/generate.py --prompt "幻想生物概念图" --count 3 --output "./creature.png"

# 参考图编辑
python scripts/generate.py --prompt "把这张草图变成精致海报" --image "./sketch.png" --output "./poster.png"

# gpt-image-2 推理模式
python scripts/generate.py --prompt "带精确标签和数据的图表" --thinking medium --output "./chart.png"
```

### 路由规则

| 任务 | 会话模型支持视觉 | 会话模型不支持视觉 |
|------|------------------|--------------------|
| 看图 | 可直接由会话模型处理 | 用 hello-multimodal，输入改为路径 / 目录 / clipboard |
| 生图 | 始终 hello-multimodal | 始终 hello-multimodal |

### 配置

参考 `config.example.json`。

| 字段 | 说明 |
|------|------|
| `api_key` / `image_api_key` | 视觉与生图可分开配置凭据 |
| `model` / `image_model` | 不同任务可用不同模型 |
| `vision` / `generate` | 是否启用该能力 |
| `priority` | 越小越优先 |

### 仓库结构

```text
hello-multimodal/
├── SKILL.md
├── README.md
├── LICENSE
├── config.example.json
├── config.json
├── .gitignore
└── scripts/
    ├── vision.py
    ├── generate.py
    └── export_clipboard_image.ps1
```

### 更新记录

#### v0.2.2

- 明确说明了核心限制：非视觉会话模型下，聊天附件图可能在技能路由前直接失败
- 在技能说明里加入 路径 / 目录 / clipboard 三种可执行入口
- 新增 `vision.py --clipboard`
- 新增 Windows 剪贴板导出脚本
- `vision.py` 改为纯标准库实现
- 重试逻辑改为只对可重试错误生效
- 成功结果自动补充 `_assistant_text`

#### v0.2.0

- `generate.py` 支持 `gpt-image-2` 原生 `--thinking`、`--seed`
- 持久 4xx 快速失败
- 支持 `--count`、`--endpoint-mode`、`--responses-mode`、`--dry-run`、`--quiet`
- 语义画幅分析
- 双 URL 探路兼容代理

### 许可证

Apache 2.0 — 详见 [LICENSE](./LICENSE)

---

> 🏅 此项目已链接认可 [LINUX DO](https://linux.do) 社区。
