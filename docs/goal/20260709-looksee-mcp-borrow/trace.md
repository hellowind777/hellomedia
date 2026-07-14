# Trace — looksee borrow + multimodal expansion

日期：2026-07-09

## 已完成

### Borrow P1–P4

| 任务 | 状态 | 落地 |
|------|------|------|
| P1 可选大图压缩 | ✅ | `scripts/vision.py` `load_image_payload` + `--no-compress` |
| P2 vision 瞬时重试 | ✅ | `RETRY_STATUS_CODES` / 指数退避 / `defaults.retry_count` |
| P3 doctor | ✅ | `scripts/doctor.py`（含 video/audio 能力位） |
| P4 文档路由 | ✅ | `SKILL.md` / `README.md` v0.4.0 |

### 多模态扩展（用户追加需求）

| 能力 | 脚本 | 备注 |
|------|------|------|
| 视频生成/编辑/延长 | `scripts/video.py` | xAI Imagine 异步 API |
| 音频 TTS/STT | `scripts/audio.py` | xAI Voice + OpenAI 兼容回退 |
| 图/视/音理解 | `scripts/understand.py` | 视频 chat 多 shape；音频 STT→LLM |
| 共享工具 | `scripts/_common.py` | 配置/HTTP/安全路径 |

### 形态决策

**保持 Skill**，未改 MCP。

### 验证

- 全部 `scripts/*.py` AST 语法通过
- `doctor.py --dry-run` OK
- `video.py --dry-run` / `audio.py tts|stt --dry-run` OK（无 key 可预览）
- 真实视频/音频调用需用户在 `config.json` 填入 xAI `api_key`
