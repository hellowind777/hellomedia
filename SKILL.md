---
name: hellomedia
description: "默认假设宿主主模型不能看图/读视频/听音频。用户消息含图片/截图/照片/视频/音频（含剪贴板粘贴、路径），或要求视觉理解、生图/改图、生视频/改视频/延长（含 image_to_video / reference_to_video）、TTS/STT 时，必须使用本技能。有磁盘路径用 --image；粘贴图/无路径用 vision.py --from-clipboard（需用户重新复制图片到系统剪贴板）或请用户保存路径。不要先尝试主模型识图。生图支持 skill config.json 与 Codex/Hermes/OpenClaw/env/CLI 凭据。"
version: 0.5.2
---


# HelloMedia

独立完整的多模态 Skill：**识图 / 生图 / 改图 · 读视频 / 生视频 / 改视频 · 读音频 / 生音频**。  
脚本默认 **纯标准库，零硬依赖**（Pillow 可选，用于识图前**温和**大图压缩，默认偏清晰度）。

## 与 Grok Build 内置工具的关系

Grok Build 会话里的 `image_to_video` / `reference_to_video` 是 **host 内置工具**（运行时注入）。  
其底层产品是 **xAI Imagine REST**。本技能提供跨宿主可用的 REST 等价实现：

| Grok Build host tool | 本技能 CLI |
|----------------------|-----------|
| `image_to_video` | `python scripts/video.py --mode image_to_video --image ...` |
| `reference_to_video` | `python scripts/video.py --mode reference_to_video --reference ...` |
| （无纯 T2V host tool） | `python scripts/video.py --mode text_to_video` 或先 `generate.py` 再 I2V |

**默认一律走本技能**（假设宿主主模型无视觉）。仅当用户明确要求使用 Grok Build 内置 `image_to_video` / `reference_to_video` / `image_gen` 等 host tool，或 host tool 明显更合适时，才可改用 host。  
中转若返回 403 `not enabled for this group` = 账号未开通 Imagine，不是脚本契约错误。

**Sub2API / 中转**（如 `base_url` 非 `api.x.ai` 但 `api_format: xai`）：
- 生图走 `POST /v1/images/generations`，载荷用 `aspect_ratio` + `resolution`（1k/2k），而非 OpenAI 的 `size/quality` 优先
- 图生视频 `image` 对象字段默认 `image_url`（官方 `api.x.ai` 仍用 `url`）；可用渠道字段 `video_image_url_field` 覆盖
- **不会**因本机访问不了 `api.x.ai` 而拦截中转生视频（官方 CDN 预检仅对 `api.x.ai`）
- 媒体下载使用浏览器式 `User-Agent`（可用 `HELLOMEDIA_USER_AGENT` 覆盖），避免 imgen/vidgen CDN 拒连
- 参考实现对齐：[happy-loki/grok-media-skill](https://github.com/happy-loki/grok-media-skill)

## 路由

**默认前提：宿主主模型不能看图 / 不能可靠处理多模态。**  
含媒体或生成类请求时 **直接使用本技能**，禁止先试主模型再失败，也禁止只说「看不到 / 听不到」。

```
消息含 图片/截图/照片（含粘贴、路径、附件）
  → 直接本技能识图（勿先试主模型）
  → 有磁盘路径：
       python scripts/vision.py --image <path> --prompt "..."
  → 用户粘贴进 CLI 但消息里只有 [Image #N] / 无路径：
       1) 请用户「重新复制」该图片到系统剪贴板（截图/Copy Image，不是只复制路径文字）
       2) python scripts/vision.py --from-clipboard --prompt "..."
       3) 若返回 clipboard_empty / text_only：引导重拷或保存为文件再 --image
  → 需要无损像素：加 --no-compress
  → 也可：scripts/understand.py --image / --from-clipboard

消息含 视频 / 音频
  → scripts/understand.py --video / --audio（或 audio.py stt）

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
      "video_edit": true,
      "video_extend": true,
      "audio": true,
      "priority": 1
    }
  ],
  "defaults": {
    "max_tokens": 4096,
    "timeout_seconds": 300,
    "retry_count": 2,
    "video_poll_timeout": 600,
    "max_resolution": "2k",
    "cooldown_seconds": 2.5
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
| `video_edit` / `video_extend` | 视频改/延长（默认 true；置 false 可关） |
| `priority` | 越小越优先 |
| `defaults.max_resolution` | 生图分辨率天花板（如 `2k`） |
| `defaults.cooldown_seconds` | 生图请求间隔 |
| `defaults.video_poll_timeout` | 视频轮询最长秒数（CLI `--poll-timeout` 未指定时生效） |

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
python scripts/vision.py --image ./a.png --image ./b.png --prompt "对比两图"
python scripts/vision.py --image-dir ./pages/ --prompt "批量分析"
python scripts/vision.py --from-clipboard --prompt "描述剪贴板中的截图"
python scripts/vision.py --image ./big.png --prompt "..." --no-compress
python scripts/understand.py --image ./shot.png --prompt "提取 UI 文案"
python scripts/understand.py --from-clipboard --prompt "提取 UI 文案"
```

> **粘贴图说明**：宿主把图贴进输入框后，技能**不能**直接读 `[Image #N]` 附件 token。  
> 闭环方式是 `--from-clipboard`（读 **当前 OS 剪贴板**）或 `--image <磁盘路径>`。  
> 若宿主粘贴时已清空剪贴板，需用户再复制一次图片。Windows 终端粘贴进 CLI 常用 `Alt+V`（Claude/Grok）。

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

### 诊断与能力表

```bash
python scripts/doctor.py --dry-run
python scripts/doctor.py --capabilities
python scripts/doctor.py --xai-network
python scripts/doctor.py --vision-only
python scripts/doctor.py --video-only
python scripts/doctor.py --audio-only
python scripts/doctor.py --clipboard
python scripts/doctor.py --clipboard --clipboard-capture
```

### 视频下载恢复（不重新生成）

```bash
python scripts/video.py --recover-url "https://.../video.mp4" --output ./output/recovered.mp4
```

> 理解类默认 stdout。生成类写入 `./output/`，禁止写桌面等用户目录。

## 规则

- **技能优先（默认）**：假设宿主主模型无视觉；识图/读视频/读音频/生图/生视频/TTS/STT **直接走本技能**，勿先尝试主模型识图
- **粘贴/剪贴板**：`vision.py --from-clipboard` / `understand.py --from-clipboard` 经 `scripts/_clipboard.py` 落盘到 `.runtime/clipboard/` 再识图；空剪贴板返回可恢复错误码（`clipboard_empty` 等）。**不能**解析宿主内部的 `[Image #N]` token
- **vision.py**：按 priority 尝试渠道；429/5xx/超时按 `retry_count` 重试；永久 4xx 切换下一渠道
- **vision.py 大图压缩（默认开启、偏清晰度）**：可选 Pillow；仅当文件较大且（超长边 **或** 体积极大）时才缩边/重编码；默认最长边 2048、JPEG q=90、小于 256KB 原样发送；`--no-compress` 关闭
- **generate.py**：
  - 端点：`responses` / `images` / `images/edits` / `chat` / `sd-webui` / `fal`；`api_format` 可自动映射
  - **多渠道级联**：当前 generate 渠道失败后按 `priority` 尝试下一渠道
  - 语义画布比例、自适应超时、cooldown、thinking/seed
  - Codex/Hermes/OpenClaw 凭据发现；`wire_api` 与本地 auth 代理影响端点顺序与请求头
  - 安全落盘：`./output/` 或 skill runtime，拒绝 Desktop/Downloads 等
- **video.py**：I2V / reference / text / edit / extend（`video_edit`/`video_extend` 渠道标志可关）；异步轮询；POST 前校验画幅/时长/分辨率
- **下载恢复**：生成已成功但本地下载失败时，结果含 `video_url`/`urls` + `download_error`；用 `video.py --recover-url <URL> --output ...` **仅 GET** 重下，禁止重新 POST 生成
- **audio.py**：xAI TTS/STT，可回退 OpenAI 兼容 `/v1/audio/*`
- **代理**：自动读取 `HELLOMEDIA_PROXY` 与标准 `HTTP(S)_PROXY` / 系统代理；不得把代理 URL/密码写入结果 JSON
- **诊断**：`doctor.py --capabilities` 无密钥能力表；`doctor.py --xai-network` 探测 xAI CDN
- 本技能不做联网搜索；用宿主 web 工具或独立搜索技能

### 创作收窄（可选，非强制）

仅当 **同时** 满足时启用逐轮澄清（每轮 1–3 题，可用 `1A 2B` 快答）：

1. 任务是 **生成类** 图片/视频；且  
2. 描述模糊（主体/风格/用途至少缺两项）；且  
3. 用户 **未** 提供完整可用 prompt、`--prompt-file`、或未说「直接生成 / 用默认」  

形成简报并确认后再调用 `generate.py` / `video.py`。  
**跳过问卷**：完整 prompt、批处理脚本、用户明确要求直接生成。

### 成品展示契约

命令成功且有本地文件时：

1. 确认文件存在且 size > 0  
2. 使用脚本返回的 **绝对路径**（正斜杠，如 `C:/proj/output/a.png`）  
3. 对每个成品输出 Markdown 媒体标签：`![desc](C:/abs/path.png)`，勿只打文件名  
4. 多结果逐个展示；路径含空格时用 `![desc](<C:/My Project/a.png>)`  
5. 若仅有 URL 且 `download_error`：展示 URL，并提示可用 `--recover-url` 恢复  

## 环境变量（可选）

| 变量 | 默认 | 含义 |
|------|------|------|
| `HELLOMEDIA_COMPRESS_MIN_BYTES` | 262144 (256KB) | 不超过则原样发送、不尝试压缩 |
| `HELLOMEDIA_COMPRESS_MAX_SIDE` | 2048 | 最长边超过才缩边（LANCZOS） |
| `HELLOMEDIA_COMPRESS_JPEG_QUALITY` | 90 | 需重编码时的 JPEG 质量（偏清晰） |
| `HELLOMEDIA_COMPRESS_REENCODE_MIN_BYTES` | 2097152 (2MB) | 未超长边但体积≥此值时才允许仅重编码 |
| `HELLOMEDIA_CLIPBOARD_MAX_BYTES` | 41943040 (40MB) | 剪贴板抓取体积上限 |
| `HELLOMEDIA_PROXY` | — | HTTP(S) 代理（同时用于 http/https） |
| `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` | — | 标准代理环境变量 |
| `OPENAI_API_KEY` / `GPT_API_KEY` | — | 生图 API Key |
| `OPENAI_BASE_URL` / `GPT_BASE_URL` | — | 生图 Base URL |
| `OPENAI_IMAGE_MODEL` | — | 生图模型 |
| `HELLOMEDIA_CLIENT_VERSION` / `HELLOMEDIA_ORIGINATOR` | — | Codex 账户流归因头 |
