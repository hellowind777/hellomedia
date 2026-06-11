# DeepSeek 用户也能看图生图了——我给 Claude Code 写了个多模态插件

Claude Code 很强，但前提是你得用 Claude 自家的模型。如果你用的是 DeepSeek（便宜、中文好），或者通过代理把 DeepSeek 映射成了 Opus，那视觉理解和生图能力就是零。

于是我写了一个 Skill：[HelloMultimodal](https://github.com/hellowind777/hello-multimodal)，在后台自动把多模态任务路由到 GPT。

---

## 一句话说清楚它干什么

**当主模型搞不定看图或生图时，自动切到 GPT 去处理，你无感。**

---

## 三个场景，直击痛点

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

Claude、DeepSeek、GPT-4o 这些文本模型统统不会生图。但只要配置了 `gpt-image-2` 渠道，生图需求就自动走 HelloMultimodal。生图引擎直接委托给 helloimage，继承它全部的端点 fallback 能力。

---

## 配置一次，永久生效

```json
{
  "channels": [
    {
      "name": "我的GPT渠道",
      "api_key": "sk-xxx",
      "model": "gpt-5.4",          // 视觉理解用
      "image_model": "gpt-image-2", // 生图用
      "image_api_key": "sk-img-yyy" // 生图独立key
    }
  ]
}
```

支持 3 个渠道自动 fallback，生图还可以用独立的 API key 和 base_url。

---

## 安装

```bash
git clone https://github.com/hellowind777/hello-multimodal.git
cp config.example.json config.json  # 填你的key
ln -s $(pwd) ~/.claude/skills/hello-multimodal
```

然后就像平常一样用 Claude Code。该看图看图，该生图生图。

---

- **GitHub**: https://github.com/hellowind777/hello-multimodal
- **许可证**: Apache 2.0
- **版本**: v0.1.0
