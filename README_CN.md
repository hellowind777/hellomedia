# HelloMedia

**面向 Agent 的多模态技能：图像 / 视频 / 音频的理解与生成** — 可用于 Claude Code、Grok Build、Codex，以及任何能运行 Python 脚本的宿主。

[English](./README.md) · [简体中文](./README_CN.md)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.5.1-green.svg)](./VERSION)
[![Python](https://img.shields.io/badge/python-3.10%2B%20stdlib-blue.svg)](./scripts)

> 已链接并获 [LINUX DO](https://linux.do) 社区认可。

---

## 概览

HelloMedia 是独立完整的 **Agent Skill** 包：何时调用写在 `SKILL.md`，实际工作由 `scripts/` 下**纯标准库** CLI 完成。可选安装 [Pillow](https://pypi.org/project/Pillow/) 用于识图前的大图压缩。

| 模态 | 理解 | 生成 / 编辑 |
|------|:----:|-------------|
| **图像** | `vision.py` / `understand.py` | `generate.py`（文生图、改图） |
| **视频** | `understand.py --video` | `video.py`（文生 / 图生 / 参考图 / 编辑 / 延长） |
| **音频** | STT（可再经 LLM 摘要） | TTS |

**适合：** 宿主读不了媒体、或必须把生成结果固定落盘，并需要多渠道 API 配置时。

**不适合：** 宿主已能原生理解媒体时仍强行绕过宿主；也不做联网搜索（请用搜索类技能）。

### 设计约定

1. **理解类优先宿主** — 消息里已有图/视/音时先让宿主模型处理；失败再调本技能。
2. **生成类一律走技能** — 生图 / 生视频 / TTS 使用 `generate.py` / `video.py` / `audio.py`。
3. **自备密钥** — `config.json` 多渠道 + 能力开关；识图/生图不绑定单一厂商。

---

## 功能

- **多渠道配置** — `vision` / `generate` / `video` / `audio` 开关、`priority` 级联，可选分能力凭据（`image_*` / `video_*` / `audio_*`）
- **生图** — OpenAI 兼容 images/responses、xAI/Sub2API Imagine（`aspect_ratio` + `resolution`）、SD WebUI（`api_format: sd-webui`）、fal（`api_format: fal`），以及 CLI/环境变量 + Codex/Hermes/OpenClaw 运行时凭据
- **视频** — xAI Grok Imagine REST（及 Sub2API 中转）：文生、图生（非官方主机默认 `image_url`）、多参考图、编辑、延长；异步轮询 + `--recover-url` 仅下载恢复
- **对齐 Grok Build** — 提供与宿主 `image_to_video` / `reference_to_video` 等价的 CLI（见下表）
- **音频** — xAI Voice TTS/STT，可回退 OpenAI 兼容 `/v1/audio/*`（中转需实际暴露路由）
- **识图** — OpenAI / Anthropic / xAI 及各类 OpenAI 兼容中转（Kimi、MiniMax、Gemini 代理、Ollama、vLLM 等）
- **安全与运维** — 边界安全的落盘（cwd / 技能树 / `.runtime`）；`HELLOMEDIA_PROXY` 与标准 `HTTP(S)_PROXY`（**允许本机 loopback**）；浏览器式 `User-Agent` 利于 CDN 下载；`doctor.py` 诊断
- **Windows 友好** — UTF-8 标准输出、路径归一
- **测试** — 离线友好的 `pytest`（能力校验、下载、代理、CLI dry-run、路径安全、Sub2API 契约等）

### 提供商矩阵

| 能力 | 配置要点 | 常见后端 |
|------|----------|----------|
| 识图 | `vision: true` + `model` + `api_format` | xAI、OpenAI、Claude、Kimi、MiniMax、Gemini 代理、Ollama、vLLM |
| 生图/改图 | `generate: true` + `image_model`（或 CLI/Codex） | `gpt-image-2`、xAI 图模、SD WebUI、fal、OpenAI 兼容中转 |
| 生视频/改视频 | `video: true` + `video_model` | **Grok Imagine**（`grok-imagine-video`、`grok-imagine-video-1.5` 等） |
| 语音 TTS/STT | `audio: true` | xAI Voice；OpenAI 兼容 speech/transcription |

xAI/Grok 是「一条渠道打满视/图/视/音」的示例，不是识图/生图/语音的唯一后端。**当前视频脚本面向 Grok Imagine。**

| Grok Build 宿主工具 | HelloMedia CLI |
|---------------------|----------------|
| `image_to_video` | `python scripts/video.py --mode image_to_video --image ...` |
| `reference_to_video` | `python scripts/video.py --mode reference_to_video --reference ...` |
| （无纯 T2V 宿主工具） | `python scripts/video.py --mode text_to_video` 或先生图再 I2V |

---

## 环境要求

- **Python 3.10+**（仅标准库；已在 3.13 验证）
- 能访问你所选的 API（或本机 Ollama / SD WebUI）
- 已开启能力对应的 API Key
- 可选：Pillow（识图大图压缩）

---

## 快速开始

### 1. 安装技能

克隆或复制本仓库，链到 Agent 技能目录（以 Claude Code 为例）：

```bash
# Linux / macOS
cp config.example.json config.json
# 编辑 config.json：填入密钥，按渠道打开 vision/generate/video/audio
ln -s "$(pwd)" ~/.claude/skills/hellomedia
```

```powershell
# Windows (PowerShell)
Copy-Item config.example.json config.json
# 编辑 config.json 后，可使用 Junction 或复制到 skills 目录：
# New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\hellomedia" -Target (Get-Location)
```

`config.json` 已 gitignore（真实密钥）。仓库模板为 `config.example.json`。

### 2. 最小生图渠道示例

```json
{
  "name": "My image provider",
  "base_url": "https://your-relay.example.com",
  "api_key": "sk-...",
  "image_model": "gpt-image-2",
  "api_format": "openai",
  "generate": true,
  "priority": 1
}
```

可选：`image_base_url` / `image_api_key`，避免生图与对话识图共用凭据。

### 3. 检查连通与 dry-run

```bash
python scripts/doctor.py --dry-run
python scripts/doctor.py --capabilities
python scripts/generate.py --prompt "test" --dry-run
python scripts/video.py --prompt "test" --dry-run
python scripts/audio.py tts --text "test" --dry-run
```

成功时 JSON 中应有 `"ok": true`，生成类 dry-run 带 `"dry_run": true`。在线探测：`python scripts/doctor.py`（会访问网络；默认不做昂贵的真·生图/生视频）。

### 4. 第一次真实产出

```bash
python scripts/generate.py --prompt "A flat solid blue square" --output ./output/swatch.png
python scripts/vision.py --image ./output/swatch.png --prompt "Describe this image in one sentence."
```

生图成功结果含绝对路径与 Markdown 图片标签，便于 Agent 展示成品。

---

## 使用

> **Windows 路径：** 在 bash 中优先正斜杠或单引号：`'C:/Users/you/img.png'`。

### 理解

```bash
python scripts/vision.py --image ./screenshot.png --prompt "Describe the UI"
python scripts/vision.py --image-dir ./pages/ --prompt "Batch analyze"
python scripts/understand.py --image ./shot.png --prompt "Extract visible text"
python scripts/understand.py --video ./clip.mp4 --prompt "Summarize scenes and speech"
python scripts/understand.py --audio ./meeting.mp3 --prompt "List action items"
python scripts/understand.py --image ./shot.png --prompt "x" --dry-run
python scripts/audio.py stt --audio ./meeting.mp3 --format-text
```

### 生图 / 改图

```bash
python scripts/generate.py --prompt "Safety infographic radar chart" --output ./output/chart.png
python scripts/generate.py --prompt "oil painting" --image ./sketch.png --output ./output/paint.png
python scripts/generate.py --prompt "concept" --count 3 --output ./output/variant.png
python scripts/generate.py --prompt-file ./prompts/hero.txt --output ./output/hero.png
python scripts/generate.py --thinking medium --prompt "complex composite" --output ./output/cmp.png

# 渠道 / CLI / 本地 SD
python scripts/generate.py --channel 2 --prompt "force priority" --output ./output/c2.png
python scripts/generate.py --provider fluxcode --prompt "..." --output ./output/via-codex.png
python scripts/generate.py --base-url https://api.openai.com --api-key sk-... --model gpt-image-2 --prompt "..." --dry-run
python scripts/generate.py --endpoint-mode sd-webui --base-url http://localhost:7860 --prompt "anime" --output ./output/sd.png
```

`--count` 范围为 **1–10**。输出路径须在项目/技能根下（策略上不写 Desktop/Downloads）。

### 生视频（Grok Imagine）

默认对齐 Build：`duration=6`、`resolution=480p`。`auto` 模式：有 `--image` → I2V；有 `--reference` → 参考图；仅 prompt → T2V。

```bash
python scripts/video.py --mode image_to_video --image ./still.png \
  --prompt "Camera slowly pulls back" --duration 6 --resolution 480p --output ./output/water.mp4

python scripts/video.py --mode reference_to_video \
  --reference ./char.png --reference ./outfit.png \
  --prompt "Model from <IMAGE_1> walks the runway in <IMAGE_2>" \
  --duration 10 --aspect-ratio 16:9 --output ./output/run.mp4

python scripts/video.py --mode text_to_video --prompt "Crystal rocket on Mars" --duration 6 --output ./output/rocket.mp4
python scripts/video.py --mode edit --video ./src.mp4 --prompt "Add a red jacket" --output ./output/edit.mp4
python scripts/video.py --mode extend --video ./src.mp4 --prompt "Pan to mountains" --output ./output/ext.mp4
python scripts/video.py --prompt "test" --dry-run
```

若生成已成功但本地下载失败，结果会保留 `video_url` / `download_error`。不要重新 POST，用 GET 恢复：

```bash
python scripts/video.py --recover-url "https://.../video.mp4" --output ./output/recovered.mp4
```

### 音频（TTS / STT）

```bash
python scripts/audio.py tts --text "Hello from HelloMedia" --language en --voice eve --output ./output/hello.mp3
python scripts/audio.py stt --audio ./voice.mp3 --format-text --language en
python scripts/audio.py voices
python scripts/audio.py tts --text "test" --dry-run
```

### 诊断

```bash
python scripts/doctor.py --dry-run
python scripts/doctor.py --capabilities
python scripts/doctor.py --xai-network
python scripts/doctor.py --vision-only
python scripts/doctor.py --video-only
python scripts/doctor.py --audio-only
```

---

## 配置

模板：[`config.example.json`](./config.example.json)。本地密钥：`config.json`（gitignore）。

| 字段 | 含义 |
|------|------|
| `model` | 视觉/理解模型 |
| `image_model` | 生图模型（缺省回退 `model`） |
| `video_model` | 视频模型 |
| `image_api_key` / `image_base_url` | 可选生图专用凭据 |
| `video_api_key` / `video_base_url` | 可选视频专用凭据 |
| `audio_api_key` / `audio_base_url` | 可选语音专用凭据 |
| `tts_voice` | 默认 TTS 音色 |
| `api_format` | `openai` / `anthropic` / `xai` / `sd-webui` / `fal` |
| `wire_api` | 为 `responses` 时生图优先 `/v1/responses` |
| `requires_openai_auth` | 本地 OpenAI-auth 代理 |
| `vision` / `generate` / `video` / `audio` | 能力开关 |
| `video_edit` / `video_extend` | 视频编辑/延长门闩 |
| `priority` | 越小越优先 |
| `defaults.max_tokens` | 理解默认 max tokens |
| `defaults.timeout_seconds` | 默认超时 |
| `defaults.retry_count` | 瞬时错误重试 |
| `defaults.video_poll_timeout` | CLI 未指定 `--poll-timeout` 时的轮询上限 |
| `defaults.max_resolution` | 生图分辨率天花板（如 `2k`） |
| `defaults.cooldown_seconds` | 生图请求间隔 |

### 生图凭据解析顺序

1. CLI：`--base-url` / `--api-key` / `--model` / `--provider` …
2. 环境变量：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_IMAGE_MODEL` …
3. 技能 `config.json` 中 `generate: true` 的渠道
4. 运行时发现：`~/.codex`、Hermes、OpenClaw（`--no-runtime-auth` 可关）

### 可选环境变量

| 变量 | 默认 | 含义 |
|------|------|------|
| `HELLOMEDIA_COMPRESS_MIN_BYTES` | 51200 | 超过才压缩识图输入 |
| `HELLOMEDIA_COMPRESS_MAX_SIDE` | 1536 | 压缩后最长边 |
| `HELLOMEDIA_COMPRESS_JPEG_QUALITY` | 75 | JPEG 质量 |
| `HELLOMEDIA_PROXY` | — | HTTP(S) 代理（http/https 共用） |
| `HELLOMEDIA_USER_AGENT` | 浏览器式 | 覆盖 API 与 imgen/vidgen CDN 的 UA |
| `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` | — | 标准代理环境变量 |
| `OPENAI_API_KEY` / `GPT_API_KEY` | — | 生图 API Key |
| `OPENAI_BASE_URL` / `GPT_BASE_URL` | — | 生图 Base URL |
| `OPENAI_IMAGE_MODEL` | — | 生图模型 |
| `HELLOMEDIA_CLIENT_VERSION` / `HELLOMEDIA_ORIGINATOR` | — | Codex 账户流归因头 |

---

## 仓库结构

```text
hellomedia/
├── SKILL.md                 # Agent 路由与规则（技能主入口）
├── README.md                # 英文
├── README_CN.md             # 中文（本文件）
├── RELEASE_NOTES.md         # 中英发布说明
├── CHANGELOG.md             # 版本历史
├── LICENSE                  # Apache-2.0
├── VERSION                  # 0.5.1
├── agents/openai.yaml       # Codex/OpenAI 技能元数据
├── config.example.json      # 多提供商模板
├── config.json              # 本地密钥（gitignore）
├── scripts/
│   ├── _common.py           # 共用 HTTP、代理、路径、下载
│   ├── _auth_discovery.py   # Codex / Hermes / OpenClaw 凭据
│   ├── media_caps.py        # 参数能力表与视频预检
│   ├── vision.py            # 识图
│   ├── understand.py        # 图/视/音理解
│   ├── generate.py          # 生图与改图
│   ├── video.py             # 视频生成/编辑/延长/恢复
│   ├── audio.py             # TTS / STT / 音色列表
│   └── doctor.py            # 连通性与能力表
├── tests/                   # pytest（偏离线）
└── output/                  # 生成物（gitignore）
```

运行测试：

```bash
python -m pytest tests/ -v
```

---

## 故障排查

| 现象 | 常见原因 | 处理 |
|------|----------|------|
| `config.json not found` | 未从模板复制 | `cp config.example.json config.json` |
| 识图/生图 401/403 | 密钥错误或分组权限 | 检查 key；Imagine「not enabled for this group」需账号开通产品，不是 CLI 契约错误 |
| 视频 dry-run 正常、live 403 | 中转/账号无 Imagine | 换具备 Imagine 权限的渠道 |
| Sub2API 被网络预检拦住 | 旧逻辑 / 主机判断 | 官方 CDN 预检仅针对 `api.x.ai`；中转用中转 `base_url` 或 `--skip-network-check` |
| TTS/STT 在中转上 404 | 中转无 `/v1/tts` 或 OpenAI audio 路由 | 将 `audio_base_url` 指到支持语音的端点 |
| Unsafe output path | 路径不在 cwd/技能/`.runtime` | 写到 `./output/` |
| 有 URL 但下载失败 | 瞬时网络/CDN | `video.py --recover-url …`（仅 GET）；确认代理可达 imgen/vidgen |
| 代理异常 | 不支持 SOCKS | 仅使用 HTTP(S) 代理 |

更完整的路由规则见 [`SKILL.md`](./SKILL.md)。发布说明见 [`RELEASE_NOTES.md`](./RELEASE_NOTES.md)。

---

## 更新日志

完整历史见 **[CHANGELOG.md](./CHANGELOG.md)**。摘要：

### v0.5.1

- Sub2API / Grok Imagine 契约：xAI 生图载荷、I2V `image_url`、浏览器 UA、仅官方主机 CDN 预检
- `media_caps.py`、离线测试、安全落盘、`--count` 1–10、配置侧 poll timeout
- doctor `version`/进度；understand `--dry-run`；下载恢复路径

### v0.5.0

- 技能标识 **hellomedia**；生图链路自洽 + 运行时凭据发现
- 本地 OpenAI-auth 代理探测；Codex 归因请求头

### v0.4.0

- 视频生成/编辑/延长、音频 TTS/STT、媒体理解、多能力 doctor

---

## 许可证

Apache License 2.0 — 见 [LICENSE](./LICENSE)。