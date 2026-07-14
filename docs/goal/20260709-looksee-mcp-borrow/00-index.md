# 借鉴方案：looksee-mcp → hellomedia

## 借鉴目标

在**保持 hellomedia 为 Skill 形态**的前提下，从 looksee-mcp 吸收对视觉链路真正有用的工程能力（大图压缩、瞬时错误重试、连通性诊断、失败场景路由指引），不引入 web 搜索/抓取，不把项目整体改造成 MCP。

## 来源

| 项 | 值 |
|----|-----|
| Source | https://github.com/zaoann8/looksee-mcp（本地分析副本：`%TEMP%\looksee-mcp`） |
| 关键证据 | `src/looksee_mcp/server.py`（~544 行，单文件 MCP stdio） |
| 许可证 | Apache-2.0（与 target 同为 Apache-2.0，可借鉴思想并重写实现） |
| Target | `D:\GitHub\dev\skills\hellomedia`（v0.3.2） |

## 形态结论（战略决策）

**继续保持 Skill，不改成 MCP。** 详见同目录 `01-analysis.md`。

| 选项 | 结论 |
|------|------|
| 整体改造成 MCP | ❌ 不推荐 |
| Skill 与 MCP 双形态并行维护 | ⚠️ 成本高，仅在有明确多宿主分发需求时再做 |
| 保持 Skill + 有选择地吸收工程点 | ✅ 推荐 |

## 对 target 的改造方式

**融入 / 优化**（非重构、非改形态）：

1. `scripts/vision.py`：可选大图压缩 + 瞬时错误重试
2. 新增 `scripts/doctor.py`：渠道连通性诊断
3. `SKILL.md`：强化「主模型看图失败 → 技能接管」路由文案；补充 doctor 用法
4. `README.md`：变更日志与亮点补充

## 明确不借鉴

| 项 | 原因 |
|----|------|
| MCP 协议包装 / stdio 工具暴露 | 与 Skill 设计哲学冲突；生图编排不适合 MCP 常驻进程 |
| `web_search` / `web_fetch` / `get_sources` | 超出 multimodal 职责；search 实为「提示模型假装搜索」；宿主已有 web/hellosearch 能力 |
| 单端点 env 配置取代多渠道 | target 多渠道 fallback 是核心优势 |
| macOS `pngpaste` 剪贴板 | 用户主环境为 Windows；Claude/Grok 宿主通常已传附件路径；收益低、平台碎 |
| 自定义 MCP SDK-less 协议实现 | 无对应形态需求 |

## 执行顺序

```
P1  vision 可选大图压缩（可选依赖 PIL，无 PIL 时行为不变）
 │
 ├─► P2  vision 瞬时错误重试（429/5xx/timeout 指数退避）
 │
 └─► P3  doctor 连通性诊断脚本 + 文档接线
          │
          └─► P4  SKILL/README 路由与文档收口（依赖 P1–P3 完成再写变更说明）
```

依赖关系：

- P1、P2 可并行（均改 `vision.py`，落地时建议顺序：先 P1 再 P2，避免冲突）
- P3 独立，可与 P1/P2 并行
- P4 最后做，汇总文档

## 约束（不可破坏）

1. **保持 Skill 形态**：不得删除 `SKILL.md` 触发语义，不得强制改成 MCP 才能用
2. **默认零硬依赖**：不得把 PIL / curl_cffi 变成必需依赖；无可选包时功能降级而非报错退出
3. **保留多渠道 fallback**：不得改成单 `BASE_URL` 模型
4. **保留 Anthropic / OpenAI api_format**
5. **不扩展 web 搜索/抓取进本技能**（职责边界）
6. **生图链路 `generate.py` 本轮不动**（除非 doctor 只读探测）
7. **Windows UTF-8 / 路径归一化 / 输出路径安全** 必须保留
8. **借鉴思想重写代码**，不整段粘贴 looksee 源码（虽同 Apache-2.0，仍保持代码所有权清晰）

## 验收标准（整体）

- [ ] 形态决策文档存在且明确：保持 Skill
- [ ] `python scripts/vision.py` 在无 PIL 时行为与现网一致（功能不回退）
- [ ] 安装 Pillow 后，>50KB 图片会走压缩路径（可用日志/stderr 或 dry 探测验证）
- [ ] vision 对 429/5xx 会重试，对 401/403 等永久错误不重试同一渠道
- [ ] `python scripts/doctor.py` 可输出各 vision 渠道连通结果（JSON）
- [ ] `SKILL.md` 仍符合「消息含图触发 + 主模型优先 + 失败走技能」；并说明 doctor
- [ ] 无新增强制 pip 依赖；`config.example.json` 结构兼容

## 启动方式

```
/goal follow the instructions in docs/goal/20260709-looksee-mcp-borrow/00-index.md
```

按 `tasks/P1-*.md` → `P2` → `P3` → `P4` 顺序执行；每任务完成后跑该任务内的验证命令。

## 文档清单

| 文件 | 作用 |
|------|------|
| `00-index.md` | 本入口 |
| `01-analysis.md` | 全面对比、Skill vs MCP、优缺点、借鉴评估 |
| `tasks/P1-vision-compress.md` | 可选大图压缩 |
| `tasks/P2-vision-retry.md` | vision 瞬时重试 |
| `tasks/P3-doctor.md` | doctor 诊断脚本 |
| `tasks/P4-docs-routing.md` | 文档与路由收口 |
