# HelloMedia

> Independent multimodal skill for Claude Code / Grok / Codex: **image · video · audio** understand + generate.
> **v0.5.0** — Pure stdlib, zero hard dependencies (Pillow optional).

[English](#english) | [中文](#中文)

---

> 🏅 This project is linked & recognized by the [LINUX DO](https://linux.do) community.

---

## English

A self-contained agent skill for **full multimodal** work through external APIs:

| Modality | Understand | Generate / Edit |
|----------|:----------:|:---------------:|
| **Image** | vision / understand | generate (text-to-image, edit) |
| **Video** | understand | video (text / image / reference / edit / extend) |
| **Audio** | STT + optional LLM summary | TTS |

**Fully self-contained — pure Python stdlib.** Optional [Pillow](https://pypi.org/project/Pillow/) for large-image compression.

### Design Philosophy

Anthropic Agent Skills style: describe **when** to invoke. Host model tries native media first; this skill is the reliable fallback. Generation always goes through the skill.

### Highlights

- **True multimodal** — image + video + audio in one skill
- **Bring your own providers** — multi-channel `config.json` with per-capability flags (`vision` / `generate` / `video` / `audio`)
- **Image generation** — OpenAI-compatible image APIs, xAI Imagine image, SD WebUI (A1111), fal endpoints, multi-channel cascade, Codex/Hermes/OpenClaw runtime credentials
- **Video generation** — currently built around **xAI Grok Imagine** REST (T2V / I2V / reference / edit / extend)
- **Audio** — xAI Voice TTS/STT, with OpenAI-compatible `/v1/audio/*` fallback
- **Vision understanding** — OpenAI / Anthropic / xAI and many OpenAI-compatible relays (Kimi, MiniMax, Gemini proxy, Ollama, vLLM, …)
- **Safe outputs** — blocks Desktop/Downloads/Documents; default `./output/`
- **Windows-friendly** — UTF-8 stdout, path normalization

### Provider matrix (what you can self-configure)

| Capability | How you configure | Typical providers (see `config.example.json`) |
|------------|-------------------|-----------------------------------------------|
| **Vision** (understand images) | channel `vision: true` + `model` + `api_format` | xAI, OpenAI, Claude, Kimi, MiniMax, Gemini proxy, Ollama, vLLM, … |
| **Image generate/edit** | channel `generate: true` + `image_model` / `api_format` (or CLI/Codex) | OpenAI `gpt-image-2`, xAI image models, SD WebUI (`api_format: sd-webui`), fal (`api_format: fal`), OpenAI-compatible relays; failed channels fall through by `priority` |
| **Video generate/edit** | channel `video: true` + `video_model` | **xAI Grok Imagine** family (`grok-imagine-video`, `…-1.5`, …) |
| **Audio TTS/STT** | channel `audio: true` | xAI Voice; OpenAI-compatible speech/transcription endpoints |

Grok/xAI is a **full-stack example** (vision + image + video + audio), not the only supported backend. Image/vision/audio are intentionally multi-provider; video scripting today targets Grok Imagine.

### Quick Start

```bash
cp config.example.json config.json
# Edit config.json — set api keys; turn generate/vision/video/audio on per channel
ln -s "$(pwd)" ~/.claude/skills/hellomedia
```

Enable image generation on any channel you own:

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

Optional: `image_base_url` / `image_api_key` if image traffic should not reuse the chat vision credentials.

### Usage

#### Understand

```bash
python scripts/vision.py --image screenshot.png --prompt "Describe this UI"
python scripts/understand.py --video ./clip.mp4 --prompt "Summarize scenes and speech"
python scripts/audio.py stt --audio ./meet.mp3 --format-text
```

#### Generate image (any configured generate channel)

```bash
# Uses priority-sorted config.json channels with generate: true
python scripts/generate.py --prompt "A safety infographic" --output ./output/chart.png
python scripts/generate.py --prompt "oil painting" --image ./sketch.png --output ./output/paint.png
python scripts/generate.py --channel 2 --prompt "force a specific channel priority" --output ./output/c2.png

# Explicit provider / CLI (no need for that channel in config)
python scripts/generate.py --provider fluxcode --prompt "..." --output ./output/via-codex.png
python scripts/generate.py --base-url https://api.openai.com --api-key sk-... --model gpt-image-2 --prompt "..." --dry-run
python scripts/generate.py --endpoint-mode sd-webui --base-url http://localhost:7860 --prompt "anime" --output ./output/sd.png
```

#### Generate video (xAI Grok Imagine path)

```bash
python scripts/video.py --prompt "Crystal rocket launching from Mars" --duration 10 --resolution 720p --output ./output/rocket.mp4
python scripts/video.py --prompt "Water crashes down" --image ./still.png --duration 12 --output ./output/water.mp4
python scripts/video.py --prompt "Add a red jacket" --video ./src.mp4 --output ./output/edit.mp4
```

#### Audio

```bash
python scripts/audio.py tts --text "Hello from HelloMedia" --voice eve --language en --output ./output/hello.mp3
python scripts/audio.py stt --audio ./voice.mp3
```

#### Doctor

```bash
python scripts/doctor.py --dry-run
```

### Image credential order

1. CLI flags (`--base-url`, `--api-key`, `--model`, `--provider`, …)
2. Environment variables
3. Skill `config.json` generate channels (`generate: true`, optional `image_model` / `image_base_url`)
4. Codex / Hermes / OpenClaw runtime discovery (`--no-runtime-auth` to disable)

### Repository

```text
hellomedia/
├── SKILL.md
├── README.md
├── LICENSE
├── VERSION
├── agents/openai.yaml
├── config.example.json
├── config.json              # gitignored
└── scripts/
    ├── _common.py
    ├── _auth_discovery.py   # Codex / Hermes / OpenClaw auth
    ├── vision.py
    ├── understand.py
    ├── generate.py          # image generation (complete)
    ├── video.py
    ├── audio.py
    └── doctor.py
```

### Changelog

#### v0.5.0

- Skill identity: **hellomedia** (HelloMedia)
- Image generation is self-contained: multi-channel skill config **plus** Codex/Hermes/OpenClaw runtime credentials
- Endpoint style probing for local OpenAI-auth proxies; attribution headers for Codex account flows

#### v0.4.0

- Video generate/edit/extend + audio TTS/STT + media understand
- `doctor.py` multi-capability checks

### License

Apache 2.0 — see [LICENSE](./LICENSE)

---

## 中文

独立完整的 Agent 多模态技能：**图 / 视 / 音** 理解与生成。纯标准库，Pillow 可选。

### 亮点

- **真·多模态** — 图 / 视 / 音一体
- **自备提供商** — `config.json` 多渠道，按 `vision` / `generate` / `video` / `audio` 分别开关
- **生图** — OpenAI 兼容 / xAI / SD WebUI / fal；多渠道按 priority 级联；Codex 等 runtime 凭据
- **视频** — 当前实现以 **xAI Grok Imagine** REST 为主（文生 / 图生 / 参考图 / 编辑 / 延长）
- **理解** — 识图可接 OpenAI / Claude / xAI / 各类 OpenAI 兼容中转与本地 VL
- **语音** — xAI Voice；可回退 OpenAI 兼容 `/v1/audio/*`
- **安全落盘** — 默认 `./output/`

> README 示例常写 Grok，是因为它一条渠道能覆盖视/图/视/音；**生图与识图并不绑定 Grok**。完整模板见 `config.example.json`。

### 能力与自配方式

| 能力 | 配置要点 | 常见后端 |
|------|----------|----------|
| 识图 | `vision: true` + `model` | xAI / OpenAI / Claude / Kimi / MiniMax / Gemini 代理 / Ollama / vLLM … |
| 生图 | `generate: true` + `image_model`（或 CLI/Codex） | `gpt-image-2`、xAI 图模、SD WebUI、fal、任意 OpenAI 兼容生图中转 |
| 生视频 | `video: true` + `video_model` | **Grok Imagine** 系列 |
| 语音 | `audio: true` | xAI Voice；OpenAI 兼容 TTS/STT |

### 快速开始

```bash
cp config.example.json config.json
# 按需打开各渠道的 vision/generate/video/audio 并填 key
ln -s "$(pwd)" ~/.claude/skills/hellomedia
```

自备生图渠道示例：

```json
{
  "name": "我的生图中转",
  "base_url": "https://your-relay.example.com",
  "api_key": "sk-...",
  "image_model": "gpt-image-2",
  "api_format": "openai",
  "generate": true,
  "priority": 1
}
```

### 使用示例

```bash
python scripts/vision.py --image screenshot.png --prompt "描述 UI"
python scripts/generate.py --prompt "安全信息图" --output ./output/chart.png
python scripts/generate.py --channel 2 --prompt "指定渠道 priority" --output ./output/c2.png
python scripts/generate.py --base-url https://api.openai.com --api-key sk-... --model gpt-image-2 --prompt "..." --dry-run
python scripts/generate.py --endpoint-mode sd-webui --base-url http://localhost:7860 --prompt "anime" --output ./output/sd.png
python scripts/video.py --prompt "火星升起的水晶火箭" --duration 10 --output ./output/rocket.mp4
python scripts/audio.py tts --text "你好" --language zh --voice eve --output ./output/hello.mp3
python scripts/doctor.py --dry-run
```

### 生图凭据顺序

1. CLI（`--base-url` / `--api-key` / `--model` / `--provider` …）  
2. 环境变量  
3. `config.json` 中 `generate: true` 的渠道（可用 `image_model` / `image_base_url`）  
4. Codex / Hermes / OpenClaw（可用 `--no-runtime-auth` 关闭）

### 更新日志

#### v0.5.0

- 技能正式名为 **hellomedia**
- 生图链路自洽完整：技能渠道 + 运行时凭据发现
- 本地 OpenAI-auth 代理路径探测与 Codex 归因头

#### v0.4.0

- 视频 / 音频 / 理解扩展

### 许可证

Apache 2.0 — 见 [LICENSE](./LICENSE)

---

> 🏅 此项目已链接认可 [LINUX DO](https://linux.do) 社区。
