---
name: hello-multimodal
description: "视觉理解 & 图片生成。触发条件：1) 生图需求始终用此技能(所有文本模型均无法生图)。2) 视觉理解优先尝试主模型，若主模型报错(不支持vision/代理映射导致能力缺失/返回格式错误)则fallback到此技能。3) 用户明确要求使用此技能时直接调用。适用：分析截图、理解流程图、描述嵌入图片、生成配图、文档图片理解、代理映射场景下的视觉任务。"
---

# HelloMultimodal

## 路由规则（基于实际能力探测，非模型名匹配）

```
生图需求 → 始终用此技能
         （任何文本模型均无原生生图能力）

视觉理解 → 先试主模型
           ├── 成功 → 完成
           └── 失败(不支持/代理映射/格式错误) → fallback 到此技能
```

### 代理映射场景

如果当前模型名显示为 Opus，但实际是 DeepSeek 通过代理映射：
- 主模型尝试视觉请求时会报错（`does not support images`）
- Claude Code 检测到错误后自动 fallback 到 hello-multimodal
- 用户也可直接说"用 hello-multimodal 看图"强制路由

### capability-probe 优于 name-match

- 不依赖模型名称判断能力（名称可能被代理伪造）
- 以实际 API 返回结果为准
- 失败时自动降级，无需用户干预

## 配置 (config.json)

```json
{
  "channels": [
    {
      "name": "hi-code GPT-5.4",
      "base_url": "https://api-cn.hi-code.cc",
      "api_key": "sk-...",
      "model": "gpt-5.4",
      "vision": true,
      "generate": true,
      "priority": 1
    },
    {
      "name": "OpenAI GPT-4o",
      "base_url": "https://api.openai.com",
      "api_key": "sk-...",
      "model": "gpt-4o",
      "vision": true,
      "generate": true,
      "priority": 2
    },
    {
      "name": "Ollama Local",
      "base_url": "http://localhost:11434",
      "api_key": "ollama",
      "model": "llava:latest",
      "vision": true,
      "generate": false,
      "priority": 3
    }
  ],
  "defaults": {
    "max_tokens": 4096,
    "timeout_seconds": 300,
    "retry_count": 2
  }
}
```

- `vision: true` = 此渠道可用于视觉理解
- `generate: true` = 此渠道可用于图片生成
- `priority` = 越小越优先，失败自动 fallback

## 工作流

### 视觉理解

```bash
python scripts/vision.py --image ./screenshot.png --prompt "描述图片内容"
python scripts/vision.py --image-dir ./pages/ --prompt "批量分析"
```

### 图片生成

```bash
# Basic text-to-image
python scripts/generate.py --prompt "施工质量评分雷达图" --output ./chart.png

# Long prompt from file
python scripts/generate.py --prompt-file ./prompts/design.txt --output ./design.png

# Prompt from stdin
cat ./prompts/scene.txt | python scripts/generate.py --prompt - --output ./scene.png

# Generate multiple images
python scripts/generate.py --prompt "fantasy monster concept" --count 3 --output ./monster.png

# With reference image (editing / variation)
python scripts/generate.py --prompt "turn this sketch into a polished poster" --image ./sketch.png --output ./poster.png

# gpt-image-2 thinking mode for complex compositing
python scripts/generate.py --prompt "technical diagram with labels" --thinking medium --output ./diagram.png

# Deterministic output with seed
python scripts/generate.py --prompt "a cat in a spacesuit" --seed 42 --output ./cat.png

# Force specific endpoint
python scripts/generate.py --prompt "..." --endpoint-mode responses --output ./img.png

# Dry-run to inspect configuration
python scripts/generate.py --prompt "test" --dry-run

# Custom resolution ceiling (2k/4k)
python scripts/generate.py --prompt "panoramic landscape" --max-resolution 4k --output ./wide.png
```

### 指定渠道

```bash
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

## 规则

- 按 priority 升序尝试渠道，失败自动下一个
- 每个渠道重试 `retry_count` 次后切换到下一个
- 所有渠道失败后输出错误详情
- generate.py 完全自包含，零外部依赖

### 生图默认行为（`auto` 模式覆盖绝大多数场景）

generate.py 的 `--endpoint-mode auto`（默认）内部已经做了完整的多级 fallback，**通常你不需要手动指定任何参数**：

```
auto 模式内部 fallback 链（非 OpenAI 中继）：
  images → responses → chat

auto 模式内部 fallback 链（OpenAI 官方）：
  responses → images

每个端点内部：
  full payload → minimal payload 降级
  v1 路径 → plain 路径探路
```

### 何时手动指定 `--endpoint-mode`

仅在以下场景手动干预：

| 场景 | 做法 |
|------|------|
| 生图请求，不需要特殊处理 | **不传 `--endpoint-mode`（默认 auto 足够）** |
| 已知该中继只支持 `/v1/images/generations` | `--endpoint-mode images` |
| 已知该中继只支持 `/v1/responses` | `--endpoint-mode responses` |
| auto 模式所有端点都失败，想逐个排查 | 依次尝试 `--endpoint-mode images`、`--endpoint-mode responses`、`--endpoint-mode chat` 定位可用端点 |
| 用户明确要求用特定端点 | 按用户要求传 |
| 中继返回 401/403（权限错误） | auto 不会继续 fallback（避免烧 token），此时可**不传 `--endpoint-mode`，先检查 config.json 凭据** |

### 其他参数决策

| 用户需求 | 参数 |
|---------|------|
| 生成一张图 | 基本用法，无需额外参数 |
| 生成多张不同的图 | `--count N`（串行，每张独立 timeout） |
| prompt 很长（>200 字） | `--prompt-file ./prompt.txt` 避免 CLI 转义问题 |
| 有参考图做变体/编辑 | `--image ./ref.png`（可重复传多个） |
| 复杂合成/精确标签/图表 | `--thinking medium` 或 `--thinking high`（gpt-image-2 推理预算） |
| 需要可复现结果 | `--seed 42`（半确定性输出） |
| 默认正方形不够好 | 不用手动传尺寸——`auto` 模式会自动从 prompt 提取比例（如 "16:9"），或触发 semantic layout analysis 选最优画幅 |
| 想要更高分辨率 | `--max-resolution 4k`（默认 2k） |
| 调试配置不实际请求 | `--dry-run` |
| 减少进度日志输出 | `--quiet` |
