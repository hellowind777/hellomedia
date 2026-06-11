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
python scripts/generate.py --prompt "施工质量评分雷达图" --output ./chart.png
```

### 指定渠道

```bash
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

## 规则

- 按 priority 升序尝试渠道，失败自动下一个
- 每个渠道重试 `retry_count` 次后切换到下一个
- 所有渠道失败后输出错误详情
- generate.py 的图片提取逻辑借鉴 helloimage
