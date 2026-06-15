---
name: hello-multimodal
description: "视觉理解 & 图片生成。MUST-INVOKE 条件：1) 任何生图需求 — 始终调用此技能。2) 用户消息包含图片/截图 — 若当前模型为纯文本模型或模型返回的响应语义为"无法处理图像/不支持视觉/不兼容多模态"(不限语言、不限 HTTP 状态码)，立即调用此技能进行视觉理解。3) 用户明确说 /hello-multimodal 或提及多模态/看图时直接调用。适用：分析截图、理解流程图、描述嵌入图片、生成配图、文档图片理解、代理映射下的视觉任务。"
---

# HelloMultimodal

两个脚本均为 **纯标准库，零外部依赖**。

## 路由规则

```
生图需求 → 始终用此技能（任何文本模型均无原生生图能力）

视觉理解 → 优先尝试主模型
           ├── 成功 → 完成
           └── 失败(语义为"模型不能处理图片") → fallback 到此技能
```

### 错误识别与自动触发（语义匹配，非关键词匹配）

**当主模型尝试处理图片后，若其响应的语义属于以下任一类，立即调用此技能：**

1. **能力缺失型** — 响应明确或隐含地表示"当前模型/端点不支持图像/视觉/多模态输入"。无论措辞、语言或 HTTP 状态码如何，只要语义指向"不能处理图片"，即触发。
   - 示例（仅作语义参考，非穷举）：`No endpoints found that support image input`、`model does not support images`、`图像输入不支持`、`画像入力をサポートしていません`、`does not have vision capability`、`multimodal not available for this model`

2. **格式拒绝型** — 响应表示图片格式/媒体类型不被接受，或要求纯文本输入。语义核心是"拒绝非文本内容"。

3. **代理透传型** — 模型名与实际不符（如显示 Opus 实为 DeepSeek），返回 vision/image/multimodal/media 相关错误。

**判断原则：用语义理解而非关键词匹配。只要错误的核心含义是"这个模型处理不了图片"，就触发此技能。**

### 捷径规则

如果当前会话模型已知是纯文本模型，且用户消息包含图片，**直接调用此技能，不先试主模型**，避免浪费一次请求。

> 注意：捷径规则是启发式优化，不覆盖 capability-probe 原则——不确定时仍以实际 API 返回为准。

## 配置 (config.json)

```json
{
  "channels": [
    {
      "name": "My Vision Channel",
      "base_url": "https://api.example.com",
      "api_key": "sk-your-api-key",
      "model": "gpt-4o",
      "image_model": "gpt-image-2",
      "image_api_key": "",
      "image_base_url": "",
      "responses_model": "",
      "chat_model": "",
      "vision": true,
      "generate": true,
      "priority": 1
    }
  ],
  "defaults": {
    "max_tokens": 4096,
    "timeout_seconds": 300,
    "retry_count": 2
  }
}
```

| 字段 | 说明 |
|------|------|
| `model` | 视觉理解用的模型 |
| `image_model` | 生图专用模型（不填则回退用 `model`） |
| `image_api_key` | 生图专用 API key（不填则回退用 `api_key`） |
| `image_base_url` | 生图专用 base URL（不填则回退用 `base_url`） |
| `responses_model` | `/v1/responses` 端点专用模型覆盖 |
| `chat_model` | `/v1/chat` 端点专用模型覆盖 |
| `api_format` | API 格式：`openai`（默认，兼容 GPT/Kimi/MiniMax/Ollama/vLLM/大多数代理）、`anthropic`（Claude 原生 Messages API）、`sd-webui`（本地 Stable Diffusion） |
| `vision: true` | 此渠道可用于视觉理解 |
| `generate: true` | 此渠道可用于图片生成 |
| `priority` | 越小越优先，失败自动 fallback |

### 提供商配置速查

绝大多数多模态模型使用 OpenAI 兼容的 `/v1/chat/completions` 格式，只需改 `base_url` + `model` + `api_key` 即可直接使用。详细模板见 `config.example.json`。

**视觉理解 — 直接支持的模型：**

| 提供商 | base_url | model 示例 | api_format |
|--------|----------|-----------|:---:|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` | openai |
| Kimi (Moonshot) | `https://api.moonshot.ai/v1` | `kimi-k2.6` | openai |
| MiniMax | `https://api.minimax.io/v1` | `MiniMax-M3` | openai |
| Ollama | `http://localhost:11434/v1` | `minicpm-v:latest` | openai |
| vLLM / LocalAI | `http://localhost:8000/v1` | `Qwen2.5-VL-7B` | openai |
| 硅基流动 / 火山引擎 / 其他代理 | 各家代理地址 | 各家模型 ID | openai |
| **Claude (Anthropic)** | `https://api.anthropic.com` | `claude-sonnet-4-20250514` | **anthropic** |

**图片生成 — 直接支持的平台：**

| 平台 | base_url | endpoint_mode | 说明 |
|------|----------|:---:|------|
| OpenAI / 兼容中继 | `https://api.openai.com` | auto | `/v1/images/generations` + `/v1/responses` + `/v1/chat` |
| AI/ML API (Nano Banana Pro) | `https://api.aimlapi.com/v1` | images | OpenAI 兼容格式 |
| fal.ai (Nano Banana Pro) | `https://fal.run` | images | 需 `image_model: fal-ai/nano-banana-pro` |
| **SD WebUI (A1111 本地)** | `http://localhost:7860` | **sd-webui** | 启动时带 `--api` 参数 |

## 工作流

### 视觉理解

```bash
# 单图分析
python scripts/vision.py --image ./screenshot.png --prompt "描述图片内容"

# 批量分析（支持 png/jpg/jpeg/bmp/tiff/webp/gif）
python scripts/vision.py --image-dir ./pages/ --prompt "从每页提取关键信息"

# 指定渠道
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."

# 输出到文件（默认 stdout）
python scripts/vision.py --image ./img.png --prompt "..." --output ./result.json

# 限制输出 token
python scripts/vision.py --image ./img.png --prompt "..." --max-tokens 1024
```

### 图片生成

```bash
# 基本文生图
python scripts/generate.py --prompt "施工质量评分雷达图" --output ./chart.png

# 从文件读取长 prompt
python scripts/generate.py --prompt-file ./prompts/design.txt --output ./design.png

# 从 stdin 读取
cat ./prompts/scene.txt | python scripts/generate.py --prompt - --output ./scene.png

# 生成多张
python scripts/generate.py --prompt "fantasy monster concept" --count 3 --output ./monster.png

# 参考图编辑/变体
python scripts/generate.py --prompt "turn this sketch into a polished poster" --image ./sketch.png --output ./poster.png

# gpt-image-2 推理模式
python scripts/generate.py --prompt "technical diagram with labels" --thinking medium --output ./diagram.png

# 确定性输出
python scripts/generate.py --prompt "a cat in a spacesuit" --seed 42 --output ./cat.png

# 强制端点
python scripts/generate.py --prompt "..." --endpoint-mode responses --output ./img.png

# 4K 分辨率
python scripts/generate.py --prompt "panoramic landscape" --max-resolution 4k --output ./wide.png

# 调试配置
python scripts/generate.py --prompt "test" --dry-run

# 静默模式
python scripts/generate.py --quiet --prompt "..." --output ./img.png

# SD WebUI 本地生图
python scripts/generate.py --prompt "a cat in a spacesuit" --endpoint-mode sd-webui --output ./cat.png

# SD WebUI 图生图
python scripts/generate.py --prompt "turn into oil painting" --image ./sketch.png --endpoint-mode sd-webui --output ./painting.png

# SD WebUI 自定义采样参数
python scripts/generate.py --prompt "..." --endpoint-mode sd-webui --sd-steps 50 --sd-cfg-scale 12 --sd-sampler "Euler a" --output ./img.png
```

## 规则

- vision.py：每个渠道尝试一次，失败自动下一个，不重试同一渠道
- generate.py：每个端点按 `retry_count` 重试后切换到下一个端点，再切换到下一个渠道
- 所有渠道失败后输出错误详情

### 生图默认行为（`auto` 模式覆盖绝大多数场景）

`--endpoint-mode auto`（默认）内部已做完整多级 fallback，**通常无需手动指定参数**：

```
auto 模式内部 fallback 链：

  无参考图 / 非 OpenAI：
    images → responses → chat

  无参考图 / OpenAI 官方：
    responses → images

  有参考图：
    responses → images-edits → chat (非 OpenAI)
    responses → images-edits       (OpenAI)

每个端点内部：
  full payload → minimal payload 降级
  v1 路径 → plain 路径探路
```

### 何时手动指定 `--endpoint-mode`

| 场景 | 做法 |
|------|------|
| 生图请求，不需要特殊处理 | **不传（默认 auto 足够）** |
| 已知该中继只支持 `/v1/images/generations` | `--endpoint-mode images` |
| 已知该中继只支持 `/v1/responses` | `--endpoint-mode responses` |
| 使用本地 Stable Diffusion WebUI (A1111) | `--endpoint-mode sd-webui` |
| 使用 Nano Banana Pro 等通过 OpenAI 兼容中继 | `--endpoint-mode images`（传 `image_model`） |
| auto 模式所有端点都失败，想逐个排查 | 依次尝试 images → responses → chat |
| 用户明确要求用特定端点 | 按用户要求传 |
| 中继返回 401/403 | auto 不会继续 fallback，先检查 config.json 凭据 |

### 其他参数决策

| 用户需求 | 参数 |
|---------|------|
| 生成一张图 | 基本用法，无需额外参数 |
| 生成多张不同的图 | `--count N` |
| prompt 很长（>200 字） | `--prompt-file ./prompt.txt` |
| 有参考图做变体/编辑 | `--image ./ref.png`（可重复传多个） |
| 复杂合成/精确标签/图表 | `--thinking medium` 或 `--thinking high` |
| 需要可复现结果 | `--seed 42` |
| 默认正方形不够好 | 不需手动传尺寸——auto 自动从 prompt 提取比例或触发 semantic layout analysis |
| 想要更高分辨率 | `--max-resolution 4k`（默认 2k） |
| 避免频繁请求被限流 | `--cooldown 5`（默认 2.5 秒） |
| 延长超时 | `--timeout 600`（默认自适应 220–600s） |
| SD WebUI 调高画质/步数 | `--sd-steps 50 --sd-cfg-scale 12` |
| SD WebUI 换采样器 | `--sd-sampler "Euler a"` |
| 调试配置 | `--dry-run` |
| 减少日志 | `--quiet` |
