# Changelog

All notable changes to **HelloMedia** (`hellomedia`) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

## [0.5.1] — 2026-07-14

### Added

- `scripts/media_caps.py` — shared image/video parameter constants and pre-POST validation.
- Offline `tests/` (media caps, proxy, download recovery, CLI dry-run, path safety, Sub2API field contract, auth helpers).
- Browser-like default `User-Agent` for API and CDN traffic; `HELLOMEDIA_USER_AGENT` / `GROK_MEDIA_USER_AGENT` override.
- `video_image_url_field` / `reference_url_field` channel knobs for Sub2API vs official xAI payloads.
- `doctor` fields: `version`, `overall_status`, per-channel stderr progress.
- `understand.py --dry-run`, `--timeout`, `--retry-count`.
- Codex OAuth `post_json` / `RequestFailure` in `_auth_discovery.py`.
- Bilingual docs pack: `README_CN.md`, `RELEASE_NOTES.md`, this `CHANGELOG.md`.

### Changed

- **xAI / Sub2API image path**: `api_format: xai` forces images endpoint; prefer `aspect_ratio` + `resolution` payloads (aligned with grok-media-skill).
- **I2V payload**: non-`api.x.ai` hosts default to `image.image_url` instead of `url`.
- **Network preflight**: only **official** `api.x.ai` requires xAI CDN reachability; Sub2API relays are not blocked by local `api.x.ai` failures.
- Image generate cascade skips responses/chat when `api_format` is `xai`.
- Shared download helper: chunked write, optional same-host Authorization, browser UA.
- Audio/video CLI defaults read more values from `config.json` `defaults`.
- Version badge and skill frontmatter: **0.5.1**.

### Fixed

- Output path prefix bypass (`…/hellomedia_evil` no longer treated as under `…/hellomedia`).
- `generate --count` outside 1–10 accepted as success.
- `defaults.video_poll_timeout` ignored because argparse defaulted to `600`.
- Video poll spun until timeout on permanent 4xx.
- `file_to_data_url` read entire file before size check.
- Generate vs video safe-output root mismatch.
- Missing `post_json` NameError on Codex token refresh path.

### Security

- Reject non-`http`/`https` schemes for media download (`file://` blocked).
- Loopback and LAN downloads remain **allowed** (local proxies and offline tests).
- `config.json` stays gitignored; secrets never belong in the tree.

---

## [0.5.0] — 2026-07-09

### Added

- Skill identity **hellomedia** (HelloMedia): full multimodal understand + generate surface.
- Self-contained image generation: skill `config.json` channels **plus** Codex / Hermes / OpenClaw runtime credentials.
- Video generate/edit/extend CLI and audio TTS/STT scripts (provider-dependent).
- Multi-channel doctor probes; local OpenAI-auth proxy awareness; Codex attribution headers.

### Changed

- Consolidated multimodal skill packaging for Claude Code / Grok / Codex hosts.

---

## [0.4.0] — prior

- Video generate/edit/extend, audio TTS/STT, media understand expansion.
- Multi-capability `doctor.py` checks.

---

## [0.3.x] — prior

- Agent Skills compliance, encoding/path fixes, safe output enforcement.
- Multi-provider vision & generation, stdlib-only baseline.

---

## [0.2.x] – [0.1.0] — prior

- Early generate timeout/retry calibration, img2img flows, initial skill packaging.
