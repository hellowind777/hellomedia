# P4：SKILL / README 路由与文档收口

## 目标

在 P1–P3 代码落地后，更新 `SKILL.md`、`README.md`（及可选 `VERSION`），明确：

1. **形态结论**：保持 Skill，不改 MCP
2. 视觉失败路由文案（借鉴 looksee prompts 意图，不照搬 MCP prompt）
3. 压缩 / 重试 / doctor 的用法
4. 与「不纳入 web 搜索」的边界声明

## 来源证据

- looksee-mcp `server.py` `prompts/list` / `prompts/get`（约 L476–486）：当出现 Unsupported Image 时**直接调工具**，不要声称看不见
- target `SKILL.md` 现有路由表（L11–19）与规则（L98–102）
- 本方案 `01-analysis.md` 决策

## 具体步骤

### 1. 更新 `SKILL.md` 工作流与规则

文件：`SKILL.md`

#### 1.1 路由图改为：

```markdown
## 路由

```
消息含图片 → 优先主模型处理
             ├── 成功 → 完成
             └── 无法处理（报错 / 无法读取 / 无法识别 / 格式错误 / 内容块缺失等）
                    → 使用本技能 scripts/vision.py（勿仅回复「我看不到图片」）

要求生图 → 使用本技能 scripts/generate.py

配置排障 → python scripts/doctor.py [--dry-run]
```
```

#### 1.2 在「视觉理解」命令块后追加：

```markdown
# 关闭大图压缩（默认：若已安装 Pillow 则自动压缩过大图片）
python scripts/vision.py --image ./big.png --prompt "..." --no-compress

# 渠道连通性诊断
python scripts/doctor.py --dry-run
python scripts/doctor.py --vision-only
```

#### 1.3 规则改为：

```markdown
## 规则

- vision.py：按 priority 升序尝试渠道；同一渠道内对 429/5xx/超时按 `retry_count` 重试；永久 4xx 或重试耗尽后切换下一渠道
- vision.py：可选 Pillow 大图压缩（环境变量 `HELLOMEDIA_COMPRESS_*` 可调）；`--no-compress` 关闭
- generate.py：每个端点按 `retry_count` 重试后切换到下一个端点，再切换到下一个渠道
- 所有渠道失败后输出错误详情
- 本技能不提供联网搜索/网页抓取；该类需求使用宿主 web 工具或独立搜索技能
```

#### 1.4 版本

若实施合并发版：将 frontmatter `version`  bump 到 `0.3.3`，同步 `VERSION` 文件（若存在）。

### 2. 更新 `README.md` 中英 Changelog

文件：`README.md`

在 Changelog 顶部增加 **v0.3.3**（或实施时的实际版本）：

- vision: optional Pillow compression for large images
- vision: transient retry aligned with generate defaults
- new: `scripts/doctor.py` connectivity checks
- docs: clarify host-first vision fallback; skill stays skill (not MCP)
- scope: explicitly no web search/fetch in this skill

Highlights 可补一句：

- **Optional large-image compression** — Pillow if present
- **Doctor** — `python scripts/doctor.py`

### 3. 不在文档中推荐安装 looksee-mcp 作为替代

可在 `docs/goal/.../01-analysis.md` 保留对比；面向用户的 README **不**写成「请改用 MCP」。

### 4. 可选：`config.example.json` defaults 注释性字段

不强制改 schema。若要加说明，仅在 README 表格加环境变量说明即可：

| Env | Default | Meaning |
|-----|---------|---------|
| `HELLOMEDIA_COMPRESS_MIN_BYTES` | 51200 | 超过才尝试压缩 |
| `HELLOMEDIA_COMPRESS_MAX_SIDE` | 1536 | 最长边 |
| `HELLOMEDIA_COMPRESS_JPEG_QUALITY` | 75 | JPEG 质量 |

## 安装依赖（如有）

无。

## 验证命令

```bash
cd D:/GitHub/dev/skills/hellomedia

# SKILL 仍声明 skill 形态与 vision/generate
findstr /i "vision.py doctor retry 搜索" SKILL.md

# 版本一致（若 bump）
type VERSION
findstr /i "version" SKILL.md
```

人工检查：

- [ ] description 仍是「消息含图 + 生图」，未改成 MCP 工具列表
- [ ] 无「必须安装 looksee」类错误指引

## 完成标准

- [ ] `SKILL.md` 路由含「不要只说看不到图 → 跑 vision.py」
- [ ] 规则正确描述「渠道内重试 + 渠道间 fallback」
- [ ] doctor 与 `--no-compress` 有文档入口
- [ ] 明确不提供 web search/fetch
- [ ] README changelog 记录本轮借鉴项
- [ ] 未把项目描述改成 MCP server
