# DeepSeek 用户也能看图生图了——我给 Claude Code 写了个多模态插件

Claude Code 的多模态能力依赖当前使用的模型。如果你用的是 DeepSeek（成本低、中文好），或者通过代理把 DeepSeek 映射成了 Opus，视觉理解和生图就无法使用。

于是我写了 HelloMultimodal，在后台把多模态任务路由到 GPT。

---

## 它做什么

主模型不支持视觉理解或图片生成时，HelloMultimodal 自动把任务交给配置好的 GPT 多模态模型处理。

---

## 适用场景

**1. DeepSeek 用户看图**

```
你："分析这张截图的 UI 布局"
Claude Code 发现当前模型没有 vision → 自动调 HelloMultimodal → GPT-5.4 看图 → 返回结果
全程你没有切换模型，也没有报错。
```

**2. 代理映射陷阱**

one-api 把 DeepSeek 映射成 `claude-opus-4`，Claude Code 看到模型名以为有 vision，实际没有，直接报错。

HelloMultimodal 不认模型名，认**实际能力**。发请求 → 失败 → 自动降级。代理怎么映射都不影响。

**3. 生图**

Claude、DeepSeek 等文本模型不支持原生图片生成。配置 `gpt-image-2` 后，生图需求自动走 HelloMultimodal。生图引擎委托给 helloimage，继承其全部端点 fallback 能力。

---

## 配置

```json
{
  "channels": [
    {
      "name": "GPT渠道",
      "api_key": "sk-xxx",
      "model": "gpt-5.4",
      "image_model": "gpt-image-2",
      "image_api_key": "sk-img-yyy"
    }
  ]
}
```

支持最多 3 个渠道按优先级 fallback。生图可以单独配置 api_key 和 base_url，适配独立计费分组。

---

## 安装

```bash
git clone https://github.com/hellowind777/hello-multimodal.git
cp config.example.json config.json  # 填你的key
ln -s $(pwd) ~/.claude/skills/hello-multimodal
```

配置完成后正常使用 Claude Code，视觉和生图任务会自动路由。

---

- **GitHub**: https://github.com/hellowind777/hello-multimodal
- **许可证**: Apache 2.0
- **版本**: v0.1.0
