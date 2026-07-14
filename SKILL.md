---
name: hellomedia
description: "此技能应在用户消息包含图片/截图/照片/视频/音频时使用——优先由主模型尝试处理，若主模型无法正常处理（报错/无法读取/无法识别/格式错误/内容块缺失等）则使用此技能进行多模态理解。此技能也应在用户要求生成/编辑图片、生成/编辑/延长视频（含 image_to_video / reference_to_video 图生视频）、文生语音(TTS)、语音转写(STT)时使用。生图支持 skill config.json 多渠道，以及 Codex/Hermes/OpenClaw/env/CLI 运行时凭据。"
version: 0.5.0
---

# HelloMedia

独立完整的多模态 Skill：**识图 / 生图 / 改图 · 读视频 / 生视频 / 改视频 · 读音频 / 生音频**。  
脚本默认 **纯标准库，零硬依赖**（Pillow 可选，用于大图压缩）。

## 与 Grok Build 内置工具的关系

Grok Build 会话里的 `image_to_video` / `reference_to_video` 是 **host 内置工具**（运行时注入）。  
其底层产品是 **xAI Imagine REST**。本技能提供跨宿主可用的 REST 等价实现：

| Grok Build host tool | 本技能 CLI |
|----------------------|-----------|
| `image_to_video` | `python scripts/video.py --mode image_to_video --image ...` |
| `reference_to_video` | `python scripts/video.py --mode reference_to_video --reference ...` |
| （无纯 T2V host tool） | `python scripts/video.py --mode text_to_video` 或先 `generate.py` 再 I2V |

在 **Grok Build 内**：host 工具可用时可优先用 host；跨宿主/脚本/固定落盘一律走本技能。  
中转若返回 403 `not enabled for this group` = 账号未开通 Imagine，不是脚本契约错误。

## 路由

```
消息含 图片/视频/音频
  → 优先主模型原生处理
  → 无法处理时 → 本技能理解脚本（勿只说「看不到/听不到」）

要求 生图 / 改图     → scripts/generate.py
要求 单图生视频      → scripts/video.py --mode image_to_video
要求 多参考图生视频  → scripts/video.py --mode reference_to_video
要求 纯文生视频      → scripts/video.py --mode text_to_video
                     或：generate.py 出首帧 → image_to_video
要求 改视频 / 延长   → scripts/video.py --mode edit|extend
要求 TTS / STT       → scripts/audio.py
配置排障             → scripts/doctor.py
```

| 能力 | 脚本 |
|------|------|
| 图像理解 | `scripts/vision.py` 或 `scripts/understand.py --image` |
| 视频/音频理解 | `scripts/understand.py --video` / `--audio` |
| 图像生成与编辑 | `scripts/generate.py` |
| 视频生成/编辑/延长 | `scripts/video.py` |
| 语音合成 / 转写 | `scripts/audio.py tts` / `stt` |
| 连通性诊断 | `scripts/doctor.py` |
| 运行时凭据发现 | `scripts/_auth_discovery.py`（由 generate 调用） |

## 配置 (config.json)

```json
{
  "channels": [
    {
      "name": "xAI Grok (full multimodal)",
      "base_url": "https://api.x.ai",
      "api_key": "xai-your-key",
      "model": "grok-4.5",
      "image_model": "grok-imagine-image",
      "video_model": "grok-imagine-video",
      "tts_voice": "eve",
      "api_format": "xai",
      "vision": true,
      "generate": true,
      "video": true,
      "audio": true,
      "priority": 1
    }
  ],
  "defaults": {
    "max_tokens": 4096,
    "timeout_seconds": 300,
    "retry_count": 2,
    "video_poll_timeout": 600
  }
}
```

| 字段 | 说明 |
|------|------|
| `model` | 视觉/理解模型 |
| `image_model` | 生图模型（不填回退 `model`） |
| `video_model` | 视频模型 |
| `image_api_key` / `image_base_url` | 生图专用凭据（可选） |
| `video_api_key` / `video_base_url` | 视频专用凭据（可选） |
| `audio_api_key` / `audio_base_url` | 语音专用凭据（可选） |
| `tts_voice` | 默认 TTS 音色 |
| `api_format` | `openai` / `anthropic` / `xai` / `sd-webui` / `fal`（生图时 `sd-webui`/`fal` 会自动映射 endpoint） |
| `wire_api` | 可选：`responses` 时生图优先走 `/v1/responses` |
| `requires_openai_auth` | 可选：本地 OpenAI-auth 代理时置 true |
| `vision` / `generate` / `video` / `audio` | 按渠道启停能力 |
| `priority` | 越小越优先 |

模板见 `config.example.json`。

### 生图凭据解析顺序

1. CLI：`--base-url` / `--api-key` / `--model` / `--provider` …
2. 环境变量：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_IMAGE_MODEL` …
3. 技能 `config.json` 中 `generate: true` 的渠道
4. 运行时发现：`~/.codex`、Hermes、OpenClaw（可用 `--no-runtime-auth` 关闭）

无任何 generate 渠道时，只要有 CLI/env/Codex 等 runtime 凭据仍可生图。

## 工作流

> **Windows 路径**：bash 中反斜杠会被转义。用正斜杠或单引号：`'C:/Users/xxx/img.png'`。

### 图像理解

```bash
python scripts/vision.py --image ./screenshot.png --prompt "描述图片内容"
python scripts/vision.py --image-dir ./pages/ --prompt "批量分析"
python scripts/vision.py --image ./big.png --prompt "..." --no-compress
python scripts/understand.py --image ./shot.png --prompt "提取 UI 文案"
```

### 视频 / 音频理解

```bash
python scripts/understand.py --video ./clip.mp4 --prompt "总结镜头与台词"
python scripts/understand.py --audio ./meeting.mp3 --prompt "提炼待办事项"
python scripts/audio.py stt --audio ./meeting.mp3 --format-text
```

### 图片生成 / 编辑

```bash
# config.json 渠道
python scripts/generate.py --prompt "施工质量评分雷达图" --output ./output/chart.png
python scripts/generate.py --prompt "oil painting" --image ./sketch.png --output ./output/painting.png
python scripts/generate.py --prompt "fantasy concept" --count 3 --output ./output/monster.png
python scripts/generate.py --prompt-file ./prompts/heroine.txt --output ./output/heroine.png
python scripts/generate.py --thinking medium --prompt "complex composite" --output ./output/cmp.png

# Codex provider / 显式凭据 / 本地代理
python scripts/generate.py --provider fluxcode --prompt "..." --output ./output/image.png
python scripts/generate.py --base-url https://api.openai.com --api-key sk-... --prompt "..." --output ./output/oai.png
python scripts/generate.py --endpoint-mode responses --prompt "..." --output ./output/r.png

# SD WebUI (A1111)
python scripts/generate.py --endpoint-mode sd-webui --base-url http://localhost:7860 --prompt "anime girl" --output ./output/sd.png

python scripts/generate.py --prompt "test" --dry-run
```

### 视频生成

默认对齐 Build：`duration=6`、`resolution=480p`。  
`--mode auto`：有 `--image` → I2V；有 `--reference` → reference；仅 prompt → T2V。

```bash
python scripts/video.py --mode image_to_video --image ./still.png \
  --prompt "水面落下，镜头缓缓拉远" --duration 6 --resolution 480p --output ./output/water.mp4

python scripts/video.py --mode reference_to_video \
  --reference ./char.png --reference ./outfit.png \
  --prompt "模特从 <IMAGE_1> 走上秀场，穿着 <IMAGE_2>" --duration 10 --aspect-ratio 16:9 --output ./output/run.mp4

python scripts/video.py --mode text_to_video --prompt "火星升起的水晶火箭" --duration 6 --output ./output/rocket.mp4

python scripts/generate.py --prompt "静帧：水晶火箭在火星沙丘" --output ./output/frame.png
python scripts/video.py --mode image_to_video --image ./output/frame.png --prompt "缓缓升空" --output ./output/launch.mp4

python scripts/video.py --mode edit --video ./src.mp4 --prompt "给人物加上红色外套" --output ./output/edit.mp4
python scripts/video.py --mode extend --video ./src.mp4 --prompt "镜头转向群山" --output ./output/ext.mp4
python scripts/video.py --prompt "test" --dry-run
```

### 音频（TTS / STT）

```bash
python scripts/audio.py tts --text "你好，欢迎使用 HelloMedia" --language zh --voice eve --output ./output/hello.mp3
python scripts/audio.py stt --audio ./voice.mp3 --format-text --language en
python scripts/audio.py voices
python scripts/audio.py tts --text "test" --dry-run
```

### 诊断

```bash
python scripts/doctor.py --dry-run
python scripts/doctor.py --vision-only
python scripts/doctor.py --video-only
python scripts/doctor.py --audio-only
```

> 理解类默认 stdout。生成类写入 `./output/`，禁止写桌面等用户目录。

## 规则

- **主模型优先**：含媒体消息先让宿主试；失败再调本技能
- **vision.py**：按 priority 尝试渠道；429/5xx/超时按 `retry_count` 重试；永久 4xx 切换下一渠道
- **vision.py**：可选 Pillow 大图压缩（`HELLOMEDIA_COMPRESS_*`）；`--no-compress` 关闭
- **generate.py**：
  - 端点：`responses` / `images` / `images/edits` / `chat` / `sd-webui` / `fal`；`api_format` 可自动映射
  - **多渠道级联**：当前 generate 渠道失败后按 `priority` 尝试下一渠道
  - 语义画布比例、自适应超时、cooldown、thinking/seed
  - Codex/Hermes/OpenClaw 凭据发现；`wire_api` 与本地 auth 代理影响端点顺序与请求头
  - 安全落盘：`./output/` 或 skill runtime，拒绝 Desktop/Downloads 等
- **video.py**：I2V / reference / text / edit / extend；异步轮询
- **audio.py**：xAI TTS/STT，可回退 OpenAI 兼容 `/v1/audio/*`
- 本技能不做联网搜索；用宿主 web 工具或独立搜索技能

## 环境变量（可选）

| 变量 | 默认 | 含义 |
|------|------|------|
| `HELLOMEDIA_COMPRESS_MIN_BYTES` | 51200 | 超过才尝试压缩 |
| `HELLOMEDIA_COMPRESS_MAX_SIDE` | 1536 | 最长边像素 |
| `HELLOMEDIA_COMPRESS_JPEG_QUALITY` | 75 | JPEG 质量 |
| `OPENAI_API_KEY` / `GPT_API_KEY` | — | 生图 API Key |
| `OPENAI_BASE_URL` / `GPT_BASE_URL` | — | 生图 Base URL |
| `OPENAI_IMAGE_MODEL` | — | 生图模型 |
| `HELLOMEDIA_CLIENT_VERSION` / `HELLOMEDIA_ORIGINATOR` | — | Codex 账户流归因头 |
