# RELEASE NOTES — v0.5.2

> Full history: [CHANGELOG.md](./CHANGELOG.md)

## 中文

### 行为变更

**多模态默认走技能（技能优先）**
- 默认假设宿主主模型 **不能看图 / 不能可靠处理多模态**
- 识图、读视频/音频、生图/改图、生视频/改视频/延长、TTS/STT **直接使用 HelloMedia**，不要先尝试主模型识图

**粘贴图闭环（OS 剪贴板）**
- 新增 `scripts/_clipboard.py`：Windows（Pillow / PowerShell）、macOS（Pillow / pngpaste / osascript）、Linux（Pillow / wl-paste / xclip）
- `vision.py --from-clipboard`、可重复 `--image`；`understand.py --from-clipboard`
- `doctor.py --clipboard` / `--clipboard-capture`
- 抓取落盘至技能 `.runtime/clipboard/`（gitignore）
- **不能**解析宿主内部的 `[Image #N]` 附件 token：需磁盘路径，或用户重新「复制图像」到系统剪贴板后再 `--from-clipboard`
- 空/占用剪贴板返回可恢复错误码（如 `clipboard_empty`）与 recovery 提示

**识图大图压缩：偏清晰度**
- 共享 `load_image_payload`（`vision.py` 与 `understand.py --image`）
- 默认：≤**256KB** 原样发送；最长边 **>2048** 才缩边；JPEG 质量 **90**；未超长边但 ≥**2MB** 才允许仅重编码
- RGBA/透明图 JPEG 前铺白底；仅当压缩结果更小时才替换原图；`--no-compress` 可关

### 修复

- 剪贴板占用 / 打不开时后端回退，最终归为可恢复的 empty 语义，而非含糊 hard-fail
- Anthropic 识图请求与 OpenAI 路径统一浏览器式 `User-Agent`
- `understand` 本地路径归一化与缺失文件错误

### 说明

- 视频生成仍面向 **Grok Imagine / 兼容 REST**；识图/生图可多提供商
- 剪贴板抓取依赖本机工具与权限；WSL/SSH 往往读不到 Windows 本机剪贴板

---

## English

### Behavior

**Skill-first multimodal**
- Default assumption: host main model has **no vision**
- Route understand + generate (image/video/audio) through HelloMedia; do not try host vision first

**Paste-image path (OS clipboard)**
- New `scripts/_clipboard.py` with platform backends (Pillow / PowerShell / pngpaste / osascript / wl-paste / xclip)
- `vision.py --from-clipboard` (multi `--image`); `understand.py --from-clipboard`
- `doctor.py --clipboard` / `--clipboard-capture`
- Captures under skill `.runtime/clipboard/` (gitignored)
- Host `[Image #N]` chips are **not** readable by skill scripts — use a file path, or re-copy the image to the **OS clipboard** then `--from-clipboard`
- Empty/busy clipboard returns recoverable codes (e.g. `clipboard_empty`) with recovery hints

**Clarity-first vision compress**
- Shared `load_image_payload` for `vision.py` and `understand.py --image`
- Defaults: skip ≤**256KB**; resize only if long edge **>2048**; JPEG **q=90**; re-encode-only if ≥**2MB** without oversize edge
- Flatten alpha onto white before JPEG; replace original only when compressed payload is smaller; `--no-compress` disables

### Fixes

- Clipboard open/busy errors fall through backends instead of opaque hard-fail
- Anthropic vision uses the same browser-like `User-Agent` as OpenAI path
- Local path normalize + clear missing-file errors in `understand`

### Notes

- Video scripting remains **Grok Imagine–oriented**; vision/image remain multi-provider
- Clipboard capture needs local tools/permissions; WSL/SSH often cannot see the Windows clipboard
