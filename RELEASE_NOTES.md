# RELEASE NOTES — v0.5.1

> Full history: [CHANGELOG.md](./CHANGELOG.md)

## 中文

### 新特性

**Sub2API / Grok Imagine 中转契约对齐**
- 生图在 `api_format: xai` 时优先 `POST /v1/images/generations`，载荷使用 `aspect_ratio` + `resolution`（`1k`/`2k`），与 [happy-loki/grok-media-skill](https://github.com/happy-loki/grok-media-skill) 一致
- 图生视频：非官方 `api.x.ai` 主机默认 `image.image_url` 字段；官方主机仍用 `url`；可用 `video_image_url_field` 覆盖
- 媒体请求与下载默认浏览器式 `User-Agent`（`HELLOMEDIA_USER_AGENT` / `GROK_MEDIA_USER_AGENT` 可覆盖），降低 imgen/vidgen CDN 拒连概率
- 官方 xAI CDN 预检仅对 **官方** `api.x.ai` 强制；Sub2API 中转不再因本机访问不了官方 API 而拦截生视频

**媒体能力表与预检**
- 新增 `scripts/media_caps.py`：画幅、时长、分辨率、I2V/参考图模式等 POST 前校验
- `doctor.py --capabilities` 输出机器可读能力表；报告含 `version`、`overall_status` 与分渠道进度

**诊断与 CLI 契约**
- `understand.py` 支持 `--dry-run` / `--timeout` / `--retry-count`
- `audio` / `video` 更完整读取 `config.json` 的 `defaults`（含 `video_poll_timeout`）
- 视频下载失败保留 URL，支持 `--recover-url` 仅 GET 恢复（不重新生成）

**运行时凭据**
- Codex OAuth 刷新补齐 `post_json` / `RequestFailure`，避免 NameError

**测试**
- 新增离线 `tests/`：能力校验、代理、下载恢复、CLI dry-run、路径安全、Sub2API 字段契约等

### 修复

- 安全落盘：路径边界用 `relative_to`，修复前缀旁路（如 `hellomedia_evil/`）
- 生图 `--count` 限制为 1–10，禁止 `0`/`99` 假成功
- `defaults.video_poll_timeout` 在 CLI 未传 `--poll-timeout` 时生效
- 视频轮询对 401/403/404 等永久错误快速失败
- 下载仅允许 `http`/`https`（**默认允许 loopback/局域网**，不伤本地代理与测试）
- 大文件 data URL 先 `stat` 再读；下载分块写盘
- generate 与 video 落盘规则对齐（cwd / 技能树 / `.runtime`）

### 说明

- 视频生成脚本仍面向 **Grok Imagine / 兼容 REST**；识图/生图可多提供商（OpenAI 兼容、Anthropic 识图、SD WebUI、fal 等）
- 音频 TTS/STT 依赖中转是否暴露 `/v1/tts` 或 OpenAI 兼容 `/v1/audio/*`；无路由时返回 404 属环境能力，非密钥误配 alone

---

## English

### New features

**Sub2API / Grok Imagine relay contract**
- For `api_format: xai`, image gen prefers `POST /v1/images/generations` with `aspect_ratio` + `resolution` (`1k`/`2k`), aligned with [happy-loki/grok-media-skill](https://github.com/happy-loki/grok-media-skill)
- Image-to-video: default field `image.image_url` on non-official hosts; official `api.x.ai` keeps `url`; override via `video_image_url_field`
- Browser-like `User-Agent` for API and CDN downloads (`HELLOMEDIA_USER_AGENT` / `GROK_MEDIA_USER_AGENT`)
- Official CDN preflight only for **official** `api.x.ai`; Sub2API relays are not blocked when the workstation cannot reach official API hosts

**Media caps & doctor**
- New `scripts/media_caps.py` for pre-POST validation
- `doctor.py --capabilities`; reports include `version`, `overall_status`, per-channel progress

**CLI / defaults**
- `understand.py`: `--dry-run`, timeout/retry flags
- Config `defaults.video_poll_timeout` honored when CLI omits `--poll-timeout`
- Video download recovery via `--recover-url` (GET-only)

**Auth & tests**
- Codex OAuth refresh: define `post_json` / `RequestFailure`
- Offline `tests/` covering caps, proxy, download, CLI contracts, path safety, Sub2API fields

### Fixes

- Safe output paths use path-boundary checks (no string-prefix bypass)
- Image `--count` clamped to 1–10
- Video poll fails fast on permanent HTTP 4xx
- Downloads: http(s) only; **loopback/LAN remain allowed**
- Chunked media download; `stat` before large data-URL reads
- Unified safe-output roots across generate/video

### Notes

- Video scripting remains **Grok Imagine–oriented**; vision/image remain multi-provider
- TTS/STT depend on relay routes; 404 means missing audio endpoints on the relay
