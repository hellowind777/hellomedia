---
name: hello-multimodal
description: "视觉理解与图片生成。生图始终用此技能；看图时，如果当前会话模型不支持视觉、代理映射丢失视觉能力，或用户明确要求用 hello-multimodal，就改走本技能。对非视觉会话模型，不要让用户把图片直接作为聊天附件发送；改用本地图片路径、目录，或 Windows 剪贴板截图。"
argument-hint: "[image-path|dir:<folder>|clipboard|gen] [prompt]"
allowed-tools: Read Bash(python *) Bash(python3 *) Bash(py *) Bash(powershell *)
---

# HelloMultimodal

当前调用参数：$ARGUMENTS

## 先看这个限制

如果当前 Claude Code 会话模型**不支持视觉**，用户把图片直接作为聊天附件发送时，报错会发生在**技能路由之前**，常见错误：

```text
No endpoints found that support image input
```

这时 hello-multimodal **没有机会自动接管这张附件图**。正确做法不是继续重试附件，而是改成下面三种入口之一：

1. **本地图片路径**：`D:\path\to\image.png`
2. **图片目录**：`dir:D:\path\to\pages`
3. **Windows 剪贴板截图**：先截图到剪贴板，再用 `clipboard`

## 路由规则

```text
生图需求 → 始终用此技能

视觉理解
  ├─ 当前会话模型支持视觉，且用户已成功发图 → 主模型可直接处理
  └─ 当前会话模型不支持视觉 / 代理映射失效 / 已出现图片输入报错
       → 改用 hello-multimodal
       → 输入改为 路径 / 目录 / clipboard
```

## 你执行此技能时怎么做

### A. 视觉理解

优先识别用户给的是哪种输入：

- 单图路径：如 `D:\shots\ui.png`
- 目录：形如 `dir:D:\shots`
- 剪贴板：`clipboard`

然后执行对应命令：

```bash
python "${CLAUDE_SKILL_DIR}/scripts/vision.py" --image "D:\path\to\image.png" --prompt "描述图片内容"
python "${CLAUDE_SKILL_DIR}/scripts/vision.py" --image-dir "D:\path\to\pages" --prompt "逐张分析"
python "${CLAUDE_SKILL_DIR}/scripts/vision.py" --clipboard --prompt "描述刚复制到剪贴板的截图"
```

脚本会自动：

- 按 `config.json` 里的 `priority` 依次尝试视觉渠道
- 渠道失败时自动切下一个
- 返回结构化 JSON
- 在成功结果里附带 `_assistant_text`

回答用户时：

1. 优先使用 `_assistant_text`
2. 若没有 `_assistant_text`，再从原始 JSON 的文本内容提炼结果
3. 不把整段原始 API JSON 直接甩给用户，除非用户明确要原始响应

### B. 图片生成

生图始终走 `generate.py`：

```bash
python "${CLAUDE_SKILL_DIR}/scripts/generate.py" --prompt "施工质量评分雷达图" --output "./chart.png"
```

常见扩展：

```bash
python "${CLAUDE_SKILL_DIR}/scripts/generate.py" --prompt-file "./prompt.txt" --output "./design.png"
python "${CLAUDE_SKILL_DIR}/scripts/generate.py" --prompt "fantasy monster concept" --count 3 --output "./monster.png"
python "${CLAUDE_SKILL_DIR}/scripts/generate.py" --prompt "turn this sketch into a polished poster" --image "./sketch.png" --output "./poster.png"
python "${CLAUDE_SKILL_DIR}/scripts/generate.py" --prompt "technical diagram with labels" --thinking medium --output "./diagram.png"
```

## 用户直接调用本技能时的推荐写法

```text
/hello-multimodal "D:\shots\error.png" "帮我分析这张报错截图"
/hello-multimodal "dir:D:\pages" "逐张提取页面关键信息"
/hello-multimodal "clipboard" "看看我刚复制的截图里有什么问题"
```

如果用户已经发了附件图，但当前会话模型不支持视觉：

- 明确说明：**附件图这次无法被技能接管**
- 引导用户改用上面三种入口之一
- 不要假装已经看到那张附件

## 配置说明（config.json）

- `vision: true`：此渠道可用于视觉理解
- `generate: true`：此渠道可用于图片生成
- `priority`：数值越小越先尝试

## 默认原则

- 不依赖模型名判断视觉能力，优先看实际结果
- 生图始终由此技能处理
- 非视觉会话模型下，看图不要走聊天附件，走**路径 / 目录 / clipboard**
