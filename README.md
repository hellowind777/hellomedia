# HelloMedia

**Agent skill for multimodal understand + generate: image, video, and audio** — works with Claude Code, Grok Build, Codex, and any host that can run Python scripts.

[English](./README.md) · [简体中文](./README_CN.md)

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.5.1-green.svg)](./VERSION)
[![Python](https://img.shields.io/badge/python-3.10%2B%20stdlib-blue.svg)](./scripts)

> Linked & recognized by the [LINUX DO](https://linux.do) community.

---

## Overview

HelloMedia is a self-contained **Agent Skill** package: routing rules live in `SKILL.md`; work is done by **stdlib-only** CLI scripts under `scripts/`. Optional [Pillow](https://pypi.org/project/Pillow/) compresses large images for vision.

| Modality | Understand | Generate / edit |
|----------|:----------:|:----------------|
| **Image** | `vision.py` / `understand.py` | `generate.py` (text-to-image, image edit) |
| **Video** | `understand.py --video` | `video.py` (text / image / reference / edit / extend) |
| **Audio** | STT (+ optional LLM summary) | TTS |

**Best for:** agents that need a reliable API path when the host cannot read media, or when you must generate media to disk with multi-provider config.

**Not for:** replacing host-native tools when they already work (prefer host first for understand); general web search (use a search skill).

### Design rules

1. **Host first for understand** — if the message already includes image/video/audio, let the host model try; call this skill on failure.
2. **Generation always via skill** — image / video / TTS go through `generate.py` / `video.py` / `audio.py`.
3. **Bring your own keys** — multi-channel `config.json` with per-capability flags; no hard dependency on a single vendor for vision or image gen.

---

## Features

- **Multi-channel config** — `vision` / `generate` / `video` / `audio` flags, `priority` cascade, optional per-capability keys (`image_*` / `video_*` / `audio_*`)
- **Image generation** — OpenAI-compatible images & responses, xAI/Sub2API Imagine (`aspect_ratio` + `resolution`), SD WebUI (`api_format: sd-webui`), fal (`api_format: fal`), CLI/env + Codex/Hermes/OpenClaw runtime auth
- **Video generation** — xAI Grok Imagine REST (and Sub2API relays): text-to-video, image-to-video (`image_url` on non-official hosts), reference-to-video, edit, extend; async poll + `--recover-url` download-only recovery
- **Grok Build alignment** — CLI equivalents of host `image_to_video` / `reference_to_video` (see table below)
- **Audio** — xAI Voice TTS/STT with OpenAI-compatible `/v1/audio/*` fallback (relay must expose the routes)
- **Vision** — OpenAI / Anthropic / xAI and OpenAI-compatible relays (Kimi, MiniMax, Gemini proxy, Ollama, vLLM, …)
- **Safety & ops** — path-safe outputs (cwd / skill tree / `.runtime`); proxy via `HELLOMEDIA_PROXY` or `HTTP(S)_PROXY` (**loopback allowed**); browser-like `User-Agent` for CDN downloads; `doctor.py` probes
- **Windows-friendly** — UTF-8 stdout/stderr, path normalization
- **Tests** — offline `pytest` for caps, download, proxy, CLI dry-run, path safety, Sub2API contracts

### Provider matrix

| Capability | Config | Typical backends |
|------------|--------|------------------|
| Vision | `vision: true` + `model` + `api_format` | xAI, OpenAI, Claude, Kimi, MiniMax, Gemini proxy, Ollama, vLLM |
| Image gen/edit | `generate: true` + `image_model` (or CLI/Codex) | `gpt-image-2`, xAI image, SD WebUI, fal, OpenAI-compatible relays |
| Video gen/edit | `video: true` + `video_model` | **Grok Imagine** (`grok-imagine-video`, `grok-imagine-video-1.5`, …) |
| Audio TTS/STT | `audio: true` | xAI Voice; OpenAI-compatible speech/transcription |

xAI/Grok is a full-stack example, not the only backend for vision/image/audio. **Video scripting today targets Grok Imagine.**

| Grok Build host tool | HelloMedia CLI |
|----------------------|----------------|
| `image_to_video` | `python scripts/video.py --mode image_to_video --image ...` |
| `reference_to_video` | `python scripts/video.py --mode reference_to_video --reference ...` |
| (no pure T2V host tool) | `python scripts/video.py --mode text_to_video` or generate frame → I2V |

---

## Requirements

- **Python 3.10+** (stdlib only; tested on 3.13)
- Network access to your chosen API endpoints (or local Ollama / SD WebUI)
- API keys for the capabilities you enable
- Optional: Pillow for large-image compression in vision

---

## Quick Start

### 1. Install the skill

Clone or copy this repo, then link it into your agent skills directory (example for Claude Code):

```bash
# Linux / macOS
cp config.example.json config.json
# Edit config.json — set keys; enable vision/generate/video/audio per channel
ln -s "$(pwd)" ~/.claude/skills/hellomedia
```

```powershell
# Windows (PowerShell) — junction or copy into skills dir
Copy-Item config.example.json config.json
# Edit config.json, then:
# New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\hellomedia" -Target (Get-Location)
```

`config.json` is gitignored (real keys). Ship shape is `config.example.json`.

### 2. Minimal channel (image generate)

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

Optional: `image_base_url` / `image_api_key` when image traffic should not reuse chat credentials.

### 3. Verify wiring

```bash
python scripts/doctor.py --dry-run
python scripts/doctor.py --capabilities
python scripts/generate.py --prompt "test" --dry-run
python scripts/video.py --prompt "test" --dry-run
python scripts/audio.py tts --text "test" --dry-run
```

Expect JSON with `"ok": true` and `"dry_run": true` where applicable. Live probes: `python scripts/doctor.py` (uses network; skips costly gen by design).

### 4. First real outputs

```bash
python scripts/generate.py --prompt "A flat solid blue square" --output ./output/swatch.png
python scripts/vision.py --image ./output/swatch.png --prompt "Describe this image in one sentence."
```

Successful generate results include absolute paths and markdown image tags for the agent UI.

---

## Usage

> **Windows paths:** in bash, prefer forward slashes or single quotes: `'C:/Users/you/img.png'`.

### Understand

```bash
python scripts/vision.py --image ./screenshot.png --prompt "Describe the UI"
python scripts/vision.py --image-dir ./pages/ --prompt "Batch analyze"
python scripts/understand.py --image ./shot.png --prompt "Extract visible text"
python scripts/understand.py --video ./clip.mp4 --prompt "Summarize scenes and speech"
python scripts/understand.py --audio ./meeting.mp3 --prompt "List action items"
python scripts/understand.py --image ./shot.png --prompt "x" --dry-run
python scripts/audio.py stt --audio ./meeting.mp3 --format-text
```

### Generate / edit images

```bash
python scripts/generate.py --prompt "Safety infographic radar chart" --output ./output/chart.png
python scripts/generate.py --prompt "oil painting" --image ./sketch.png --output ./output/paint.png
python scripts/generate.py --prompt "concept" --count 3 --output ./output/variant.png
python scripts/generate.py --prompt-file ./prompts/hero.txt --output ./output/hero.png
python scripts/generate.py --thinking medium --prompt "complex composite" --output ./output/cmp.png

# Channel / CLI / local SD
python scripts/generate.py --channel 2 --prompt "force priority" --output ./output/c2.png
python scripts/generate.py --provider fluxcode --prompt "..." --output ./output/via-codex.png
python scripts/generate.py --base-url https://api.openai.com --api-key sk-... --model gpt-image-2 --prompt "..." --dry-run
python scripts/generate.py --endpoint-mode sd-webui --base-url http://localhost:7860 --prompt "anime" --output ./output/sd.png
```

`--count` is **1–10**. Outputs must stay under project/skill roots (not Desktop/Downloads by policy).

### Generate video (Grok Imagine)

Defaults align with Build: `duration=6`, `resolution=480p`. Mode `auto`: `--image` → I2V; `--reference` → reference; prompt only → T2V.

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

If generation succeeds but local download fails, the result keeps `video_url` / `download_error`. Recover without re-POST:

```bash
python scripts/video.py --recover-url "https://.../video.mp4" --output ./output/recovered.mp4
```

### Audio (TTS / STT)

```bash
python scripts/audio.py tts --text "Hello from HelloMedia" --language en --voice eve --output ./output/hello.mp3
python scripts/audio.py stt --audio ./voice.mp3 --format-text --language en
python scripts/audio.py voices
python scripts/audio.py tts --text "test" --dry-run
```

### Doctor

```bash
python scripts/doctor.py --dry-run
python scripts/doctor.py --capabilities
python scripts/doctor.py --xai-network
python scripts/doctor.py --vision-only
python scripts/doctor.py --video-only
python scripts/doctor.py --audio-only
```

---

## Configuration

Template: [`config.example.json`](./config.example.json). Local secrets: `config.json` (gitignored).

| Field | Role |
|-------|------|
| `model` | Vision / understand model |
| `image_model` | Image gen model (falls back to `model`) |
| `video_model` | Video model |
| `image_api_key` / `image_base_url` | Optional image-only credentials |
| `video_api_key` / `video_base_url` | Optional video-only credentials |
| `audio_api_key` / `audio_base_url` | Optional audio-only credentials |
| `tts_voice` | Default TTS voice |
| `api_format` | `openai` / `anthropic` / `xai` / `sd-webui` / `fal` |
| `wire_api` | Prefer `/v1/responses` for images when `responses` |
| `requires_openai_auth` | Local OpenAI-auth proxy |
| `vision` / `generate` / `video` / `audio` | Capability switches |
| `video_edit` / `video_extend` | Gate edit/extend (default on when video enabled) |
| `priority` | Lower runs first |
| `defaults.max_tokens` | Understand max tokens |
| `defaults.timeout_seconds` | Request timeout default |
| `defaults.retry_count` | Transient retries |
| `defaults.video_poll_timeout` | Video poll ceiling when CLI omits `--poll-timeout` |
| `defaults.max_resolution` | Image size ceiling (`2k` / …) |
| `defaults.cooldown_seconds` | Pause between image requests |

### Image credential order

1. CLI: `--base-url` / `--api-key` / `--model` / `--provider` …
2. Env: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_IMAGE_MODEL`, …
3. Skill `config.json` channels with `generate: true`
4. Runtime discovery: `~/.codex`, Hermes, OpenClaw (`--no-runtime-auth` to disable)

### Optional environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `HELLOMEDIA_COMPRESS_MIN_BYTES` | 51200 | Compress vision inputs above this size |
| `HELLOMEDIA_COMPRESS_MAX_SIDE` | 1536 | Max long edge after compress |
| `HELLOMEDIA_COMPRESS_JPEG_QUALITY` | 75 | JPEG quality |
| `HELLOMEDIA_PROXY` | — | HTTP(S) proxy for both schemes |
| `HELLOMEDIA_USER_AGENT` | browser-like | Override UA for API + imgen/vidgen CDN |
| `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` | — | Standard proxy env |
| `OPENAI_API_KEY` / `GPT_API_KEY` | — | Image API key |
| `OPENAI_BASE_URL` / `GPT_BASE_URL` | — | Image base URL |
| `OPENAI_IMAGE_MODEL` | — | Image model id |
| `HELLOMEDIA_CLIENT_VERSION` / `HELLOMEDIA_ORIGINATOR` | — | Codex account attribution headers |

---

## Repository layout

```text
hellomedia/
├── SKILL.md                 # Agent routing & rules (primary skill entry)
├── README.md                # English (this file)
├── README_CN.md             # Chinese
├── RELEASE_NOTES.md         # Bilingual release highlights
├── CHANGELOG.md             # Version history
├── LICENSE                  # Apache-2.0
├── VERSION                  # 0.5.1
├── agents/openai.yaml       # Codex/OpenAI skill metadata
├── config.example.json      # Multi-provider template
├── config.json              # Local secrets (gitignored)
├── scripts/
│   ├── _common.py           # Shared HTTP, proxy, paths, download
│   ├── _auth_discovery.py   # Codex / Hermes / OpenClaw auth
│   ├── media_caps.py        # Parameter caps & video preflight
│   ├── vision.py            # Image understand
│   ├── understand.py        # Image / video / audio understand
│   ├── generate.py          # Image generate & edit
│   ├── video.py             # Video generate / edit / extend / recover
│   ├── audio.py             # TTS / STT / voices
│   └── doctor.py            # Connectivity & capabilities
├── tests/                   # pytest (offline-friendly)
└── output/                  # Generated media (gitignored)
```

Run tests:

```bash
python -m pytest tests/ -v
```

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| `config.json not found` | Not copied from example | `cp config.example.json config.json` |
| Vision/gen fails with 401/403 | Bad key or provider group | Fix key; for Imagine “not enabled for this group”, enable product on the account (not a CLI bug) |
| Video dry-run OK, live 403 | Relay/account without Imagine | Use a channel with Imagine entitlement |
| Sub2API video blocked on network preflight | Old behavior / mis-set host | Official CDN preflight is only for `api.x.ai`; use relay `base_url` or `--skip-network-check` |
| TTS/STT 404 on relay | Relay lacks `/v1/tts` or OpenAI audio routes | Point `audio_base_url` at a voice-capable endpoint |
| Unsafe output path | Path outside cwd/skill/`.runtime` | Write under `./output/` |
| Download failed but has URL | Transient CDN/network | `video.py --recover-url …` (GET only); ensure proxy can reach imgen/vidgen |
| Proxy issues | SOCKS unsupported | Use HTTP(S) proxy only |

More routing detail: [`SKILL.md`](./SKILL.md). Release detail: [`RELEASE_NOTES.md`](./RELEASE_NOTES.md).

---

## Changelog

See **[CHANGELOG.md](./CHANGELOG.md)** for the full history. Highlights:

### v0.5.1

- Sub2API / Grok Imagine contract: xAI image payloads, I2V `image_url`, browser UA, official-only CDN preflight
- `media_caps.py`, offline tests, safer paths, `--count` 1–10, poll timeout from config
- Doctor `version` / progress; understand `--dry-run`; download recover path

### v0.5.0

- Skill identity **hellomedia**; self-contained image gen + runtime auth discovery
- Local OpenAI-auth proxy probing; Codex attribution headers

### v0.4.0

- Video generate/edit/extend, audio TTS/STT, media understand, multi-capability doctor

---

## License

Apache License 2.0 — see [LICENSE](./LICENSE).
