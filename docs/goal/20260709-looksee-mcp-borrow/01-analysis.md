# 全面对比分析：looksee-mcp vs hellomedia

分析日期：2026-07-09  
Source 证据以 `server.py` 为准；文档与代码冲突时以代码为准。

---

## 1. 项目画像

### 1.1 hellomedia（Target）

| 维度 | 现状 |
|------|------|
| 形态 | Claude Code / Agent **Skill**（`SKILL.md` + 脚本） |
| 职责 | **视觉理解** + **图片生成** |
| 入口 | 主模型先处理图片；失败后 agent 调 `scripts/vision.py`；生图始终走 `scripts/generate.py` |
| 配置 | `config.json` 多渠道 `priority` 排序 fallback |
| 协议 | OpenAI chat/completions、Anthropic messages、生图多端点（responses/images/edits/chat/SD WebUI） |
| 依赖 | **纯标准库硬依赖** |
| 体量 | `vision.py` ~229 行；`generate.py` ~1400+ 行 |
| 平台 | Windows 友好（UTF-8 reconfigure、路径 `\`→`/`、安全输出路径） |
| 版本 | 0.3.2，Apache-2.0 |

### 1.2 looksee-mcp（Source）

| 维度 | 现状 |
|------|------|
| 形态 | **MCP Server**（自实现 JSON-RPC stdio，无官方 `mcp` SDK） |
| 职责 | **视觉理解** + **伪联网搜索** + **网页抓取** |
| 入口 | 7 个 MCP tools 常驻暴露 |
| 配置 | 5 个环境变量，**单端点** |
| 协议 | 仅 OpenAI 兼容 `/chat/completions` |
| 依赖 | 硬依赖 stdlib；可选 PIL（压缩）、curl_cffi（抓取 TLS） |
| 体量 | 单文件 `server.py` ~544 行 |
| 平台 | 剪贴板强依赖 macOS `pngpaste`；其余跨平台 |
| 版本 | README 1.0.0 / serverInfo 1.1.0，Apache-2.0，仓库仅 2 commits 量级 |

---

## 2. 能力矩阵

| 能力 | hellomedia | looksee-mcp | 重叠？ |
|------|:---:|:---:|:---:|
| 单图视觉分析 | ✅ `vision.py --image` | ✅ `vision_file` | **是** |
| 目录批量视觉 | ✅ `--image-dir` | ✅ `vision_dir` | **是** |
| 剪贴板看图 | ❌ | ✅ macOS only | 弱相关 |
| 多渠道 vision fallback | ✅ priority | ❌ 单 key | target 更强 |
| Anthropic 原生视觉 | ✅ | ❌ | target 更强 |
| 大图自动压缩 | ❌ | ✅ 可选 PIL | **可借鉴** |
| vision 瞬时重试 | ❌（一试即切渠道） | ✅ retries=3 退避 | **可借鉴** |
| 连通性诊断 doctor | ❌ | ✅ | **可借鉴** |
| 图片生成 / 编辑 | ✅ 完整编排 | ❌ | target 独有 |
| SD WebUI / 多生图端点 | ✅ | ❌ | target 独有 |
| 语义画幅分析 | ✅ | ❌ | target 独有 |
| web 搜索 | ❌（职责外） | ⚠️ 见下文 | 表面重叠 |
| web 抓取 + HTML 清洗 | ❌ | ✅ 真实抓取 | 职责外 |
| 搜索源分页 get_sources | ❌ | ⚠️ 见下文 | 虚 |
| 输出路径安全 | ✅ | ❌ | target 更强 |
| Windows 路径/编码 | ✅ | 弱 | target 更强 |
| 宿主优先再 fallback | ✅ Skill 设计 | ❌ MCP 直接 tool | 哲学不同 |

---

## 3. looksee 关键实现审计（代码级）

### 3.1 视觉（真实能力）

证据：`server.py` `_from_file` / `vision` / `_chat` / `_compress`。

- 读文件 → 可选 PIL 缩略图 768×768 JPEG q65（>50KB 才压）
- base64 data URL 走 OpenAI 风格 `image_url`
- 重试：429/502/503/504 与 timeout/connection 指数退避
- **无** 多图一次请求；`vision_dir` 是逐文件串行再拼接文本

### 3.2 web_search（名不副实）

证据：`web_search()` → 仅 `_chat(SEARCH_MODEL, system+user)`。

```text
不是：搜索引擎 / 浏览器 / 检索 API
而是：把「你是联网搜索助手」塞给 LLM，指望后端模型自带搜索或幻觉作答
```

若后端是普通 `gpt-4o-mini`（无实时检索工具），输出**不是**可靠联网结果。  
`get_sources` 把该次 LLM 回复塞进 LRU 缓存成「一条 source」，分页基本无实义。

### 3.3 web_fetch（真实但与 multimodal 无关）

- urllib 浏览器头 → 可选 curl_cffi → 拦截页启发式
- stdlib HTMLParser 去 script/style
- 可选 FETCH_MODEL 做摘要

这是通用「读网页」MCP 能力，与「看图/生图」技能正交。

### 3.4 doctor（真实、小而美）

- 查 `/models`
- 对 search/vision model 各打一条「回复 OK」
- 输出 JSON 文本

### 3.5 MCP 协议实现

- 手写 `initialize` / `tools/list` / `tools/call` / `prompts/*`
- 无 resources、无 sampling、无官方 schema 校验
- 适合「轻量单文件」，不适合作为长期协议兼容基座

---

## 4. Skill vs MCP：应否改形态？

### 4.1 决策框架

| 问题 | hellomedia 答案 | 倾向 |
|------|----------------------|------|
| 是否需要**常驻**工具进程？ | 否；看图是偶发 fallback，生图是按需 CLI | Skill |
| 是否依赖**宿主路由语义**（先试主模型）？ | 是；写在 SKILL description | Skill |
| 是否需要**复杂参数/编排/落盘**？ | 生图：是（size/quality/count/endpoint/trace） | Skill/CLI |
| 是否需要**跨宿主统一 tool schema**？ | 当前以 Claude Code skill 为主；Grok 也有 skill | Skill 足够 |
| 是否主要卖「剪贴板即分析」？ | 否；用户 Windows；附件多半已是文件 | 不必 MCP |
| 能力是否被宿主原生能力覆盖？ | Grok/Claude 常自带 vision/search | Skill 作补强即可 |

### 4.2 改成 MCP 的收益（理论）

1. Tool schema 固定，模型更少「忘记跑脚本」
2. 一次注册，多会话常驻
3. 与 looksee 同类产品可对标分发

### 4.3 改成 MCP 的成本与损失（实际）

1. **丢失 Skill 的「主模型优先」产品哲学**：MCP tool 会诱导模型每次都调外部 vision，增加延迟与费用
2. **生图编排极不适配 MCP**：`generate.py` 的 CLI 面（dry-run、count、layout、endpoint-mode、安全路径）做成 tool 参数爆炸；或拆一堆 tools 维护成本高
3. **多渠道 config.json 与 MCP env 模型冲突**：要么在 MCP 内重实现整套 channel 逻辑，要么退化成 looksee 式单端点
4. **双宿主差异**：Claude Code / Grok / Codex 对 skill 与 MCP 支持深度不同；强绑 MCP 缩小可用面
5. **进程与密钥生命周期**：MCP 常驻占进程；skill 脚本用完即走
6. **与现有 hello 技能体系不一致**：hellomedia 已按 Anthropic Agent Skills 标准写好 description

### 4.4 混合方案何时才值得

仅当同时满足：

- 需要给**不会读 SKILL、只会调 MCP 的宿主**分发
- 且只要 **vision_file 级别**的薄封装
- 且愿意维护「脚本核心 + MCP 薄壳」双入口

否则 **不要拆成两个产品**。

### 4.5 结论

| 决策 | 说明 |
|------|------|
| **保持 Skill** | 形态与职责、宿主路由、生图编排、多渠道配置全部匹配 |
| **不整体 MCP 化** | 收益不足以覆盖职责分裂与维护成本 |
| **可借鉴的是工程点，不是产品壳** | 压缩、重试、doctor、失败路由文案 |

---

## 5. 优缺点对照

### 5.1 hellomedia

**优点**

- 职责清晰：vision + generate，不掺搜索
- 多渠道 + Anthropic + 代理/本地模型
- 生图工程深度远超同类「薄包装」
- 零硬依赖、Windows 打磨、路径安全
- Skill 标准触发：消息含图，不靠关键词

**缺点 / 缺口**

- 大图原样 base64，带宽/超时/费用风险
- vision 无瞬时重试（网络抖一下就切渠道）
- 无 doctor，配置排障靠猜
- agent 必须正确拼 shell；偶尔路径转义踩坑（已有 Windows 指引）
- 无剪贴板快捷路径（在「附件已落盘」场景下可接受）

### 5.2 looksee-mcp

**优点**

- 单文件、上手快、env 极少
- MCP tool 对「不会跑脚本」的模型更友好
- 大图压缩、重试、doctor、fetch 降级链有工程自觉
- 搜+看+抓「一个进程」对极简用户有吸引力
- prompts 引导「Unsupported Image 时调 clipboard」体验好（macOS）

**缺点 / 风险**

- **web_search 不可靠**：无真实检索管线，文档却写「联网搜索」
- **get_sources 名不副实**：单条 LLM 文本缓存
- 无生图、无多渠道、无 Anthropic
- 剪贴板 macOS 锁定；Windows 用户核心卖点打折
- 自研 MCP 协议面窄，长期兼容性未知
- 仓库极新、社区验证少（star 极少、2 commits 级）
- 批量 vision 串行且可能 token/费用放大无策略

---

## 6. 借鉴评估（值得 + 有必要）

筛选规则：target 有缺口 + source 有证据 + 可落地 + 收益>成本 + 不破约束 + 可验收。

### 6.1 有必要借鉴（进入 tasks）

| ID | 项 | Source 证据 | Target 缺口 | 收益 | 成本 | 任务 |
|----|----|-------------|-------------|------|------|------|
| B1 | 可选大图压缩 | `_compress` L84–102 | 原图直传 | 降超时/费用/413 | 低（可选 PIL） | P1 |
| B2 | vision 瞬时重试 | `_chat` retries L135–167 | 一失败即切渠道 | 提高单渠道成功率 | 低 | P2 |
| B3 | doctor 诊断 | `doctor` L388–423 | 排障困难 | 配置自检 | 中低 | P3 |
| B4 | 失败路由文案 | `prompts/*` L476–486 | 路由可再写清 | 少「我看不到图」推诿 | 低 | P4 |

### 6.2 可借鉴但本轮不做（降级）

| 项 | 原因 |
|----|------|
| HTTPS keep-alive opener | 收益边际；urllib 短连接够用 |
| curl_cffi 抓取链 | 不做 web_fetch |
| macOS/Win 剪贴板 | 平台碎 + 宿主附件已覆盖主路径 |
| session_id 源缓存 | 绑定伪搜索，无意义 |
| MCP 薄壳 | 无明确分发需求 |

### 6.3 不借鉴

| 项 | 原因 |
|----|------|
| 改 MCP 形态 | 见 §4 |
| web_search / get_sources | 职责外 + 实现虚 |
| web_fetch | 职责外；宿主已有 fetch |
| 单端点 env 配置 | 削弱多渠道 |
| 去掉生图 | target 核心价值 |

---

## 7. 产品定位建议（一句话）

- **hellomedia**：Agent 多模态能力补强 Skill——**主模型看图失败时的可靠视觉通道 + 专业生图编排**。  
- **looksee-mcp**：面向 Claude Code 的轻量 MCP 瑞士军刀——**看图 +（伪）搜 + 抓网页**，极简单端点。

二者「看图」重叠，但 **定位、深度、边界不同**；应用对方的「壳」会丢掉自己的长板。

---

## 8. 风险与许可证

- 许可证同为 Apache-2.0：可参考实现思路，任务要求**重写**，避免整文件复制。
- 不运行 source 安装脚本；不引入不明二进制。
- 压缩质量（768 / q65）可能损失 OCR 细字：实现时应对「小图不压、可配置阈值」留开关（见 P1）。
