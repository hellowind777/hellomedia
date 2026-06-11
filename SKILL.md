---
name: hello-multimodal
description: "当默认模型不具备视觉理解或图片生成能力时，自动路由到 config.json 中配置的多模态模型（按优先级 fallback）。适用：分析截图、理解流程图、描述嵌入图片、生成配图。"
---

# HelloMultimodal

多模态视觉理解 & 图片生成 Skill。通过 `config.json` 配置 3 个 API 渠道，按优先级自动 fallback。

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
