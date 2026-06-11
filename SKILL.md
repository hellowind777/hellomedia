---
name: hello-multimodal
description: "当当前默认模型不具备视觉理解或图片生成能力时，自动路由到已配置的 GPT 多模态模型进行视觉理解、图片描述、文档截图分析和图片生成。适用场景：分析截图、理解流程图、描述文档中的嵌入图片、生成配图。"
---

# HelloMultimodal

当主模型不具备 vision 能力时，自动路由视觉任务到 GPT 多模态模型。

## 配置

API 配置自动查找（优先级从高到低）：
1. 环境变量 `GPT_API_KEY` / `GPT_BASE_URL`
2. `~/.helloexpert/gpt_api.txt`
3. 当前项目目录下的 `gpt_api.txt`

## 工作流

### 视觉理解

```bash
python skills/hello-multimodal/scripts/vision.py \
  --image ./screenshot.png \
  --prompt "描述图片内容" \
  --output ./result.json
```

### 批量分析

```bash
python skills/hello-multimodal/scripts/vision.py \
  --image-dir ./pages/ \
  --prompt "提取关键信息" \
  --output ./batch.json
```

### 图片生成

```bash
python skills/hello-multimodal/scripts/generate.py \
  --prompt "生成一张图表" \
  --output ./chart.png
```

## 触发条件

以下情况自动激活此 Skill：
1. 用户上传/引用图片，但当前模型不支持 vision
2. Chat 中提到需要"看图"、"分析截图"、"识别图片"
3. 评审流程中遇到嵌入图片需要描述
4. 需要生成报告配图

## 规则

- 优先使用 `gpt-5.4` 进行视觉理解
- 图片生成使用相同 API 的 chat/completions 端点
- 不要将图片数据发送到不支持 vision 的模型
- 视觉分析结果以 JSON 格式返回，包含结构化描述
- 批量处理时，每张图片独立请求，避免超时
- 支持的图片格式: PNG, JPG, BMP, TIFF (自动编码为 base64)
- 单张图片最大 20MB
