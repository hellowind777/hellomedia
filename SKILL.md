---
name: hello-multimodal
description: "此技能应在用户消息包含图片/截图/照片时使用——优先由主模型尝试处理图片，若主模型无法正常处理（报错/无法读取/无法识别/格式错误/内容块缺失等）则使用此技能进行视觉理解。此技能也应在用户要求生成图片/画图/配图时使用。"
version: 0.3.2
---

# HelloMultimodal

两个脚本均为 **纯标准库，零外部依赖**。

## 路由

```
消息含图片 → 优先主模型处理
             ├── 成功 → 完成
             └── 无法处理 → 使用此技能视觉理解

要求生图 → 使用此技能图片生成
```

视觉理解通过 `scripts/vision.py` 调用外部多模态视觉 API，图片生成通过 `scripts/generate.py` 调用外部生图 API。

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
| `model` | 视觉理解模型 |
| `image_model` | 生图模型（不填回退 `model`） |
| `image_api_key` | 生图 API key（不填回退 `api_key`） |
| `image_base_url` | 生图 base URL（不填回退 `base_url`） |
| `api_format` | `openai`（默认）/ `anthropic` / `sd-webui` |
| `vision: true` | 可用于视觉理解 |
| `generate: true` | 可用于图片生成 |
| `priority` | 越小越优先，失败自动 fallback |

详细模板见 `config.example.json`。

## 工作流

> **Windows 路径注意**：bash 中反斜杠 `\` 会被当作转义符吃掉。使用正斜杠 `/` 或单引号包裹：`'C:/Users/xxx/img.png'`。

### 视觉理解

```bash
# 单图分析（默认 stdout，不产生文件）
python scripts/vision.py --image ./screenshot.png --prompt "描述图片内容"

# 批量分析
python scripts/vision.py --image-dir ./pages/ --prompt "批量分析"

# 指定渠道
python scripts/vision.py --channel 2 --image ./img.png --prompt "..."
```

### 图片生成

```bash
# 基本文生图（输出到 ./output/ 目录）
python scripts/generate.py --prompt "施工质量评分雷达图" --output ./output/chart.png

# 参考图编辑/变体
python scripts/generate.py --prompt "turn into oil painting" --image ./sketch.png --output ./output/painting.png

# 生成多张 / 指定渠道 / 调试
python scripts/generate.py --prompt "fantasy monster concept" --count 3 --output ./output/monster.png
python scripts/generate.py --channel 2 --prompt "..." --output ./output/img.png
python scripts/generate.py --prompt "test" --dry-run
```

> 视觉理解默认输出 stdout，不创建文件。图片生成输出到 `./output/`，不写入桌面或用户目录。

## 规则

- vision.py：按 priority 升序尝试渠道，失败自动下一个，不重试同一渠道
- generate.py：每个端点按 `retry_count` 重试后切换到下一个端点，再切换到下一个渠道
- 所有渠道失败后输出错误详情
