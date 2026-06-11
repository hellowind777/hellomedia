---
name: hello-multimodal
description: "视觉理解 & 图片生成。路由规则：生图需求始终使用此技能（Claude/GPT/DeepSeek 等文本模型均无法生图）。视觉理解时若主模型不支持 vision（如 DeepSeek）则调用此技能；若主模型本身支持 vision（如 Claude Opus/Sonnet、GPT-4o）则优先使用主模型。适用：分析截图、理解流程图、描述嵌入图片、生成配图、文档图片理解。"
---

# HelloMultimodal

## 路由规则

| 需求 | 主模型有能力 | 主模型无能力 |
|------|------------|------------|
| **视觉理解** | 主模型直接处理 | → 调用此技能 |
| **图片生成** | → 始终调用此技能 | → 调用此技能 |

- Claude Opus/Sonnet 有 vision → 看图直接用 Claude，不调用技能
- DeepSeek 无 vision → 看图自动调用此技能
- 所有模型均无法生图 → 生图始终走此技能

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
