# DeepSeek 能看图、Claude Code 能生图——我给 CC 写了个多模态插件

Claude Code 的多模态能力依赖当前使用的模型。如果你用 DeepSeek（成本低、中文好），视觉理解就用不了。即使原生 Claude 模式也不支持图片生成——这跟模型无关，是能力边界问题。

HelloMultimodal 解决的就是这个：给没有 vision 的模型补上视觉理解，给 Claude Code 补上生图能力。

---

## 它做什么

两件事：给 DeepSeek 等模型补上视觉理解能力，给 Claude Code 补上图片生成能力。主模型不支持时自动路由到 GPT 多模态模型处理。

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

**3. Claude Code 生图**

Claude Code 不管用哪个模型，本身都不支持图片生成。HelloMultimodal 补上了这个缺口——生图需求自动交给 gpt-image-2，引擎委托给 helloimage，继承其全部端点 fallback。

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
