# Ink Traces WebUI

<p align="center">
  <img src="../Banner.png" alt="Ink Traces WebUI Banner" width="100%" />
</p>

> Where words become pixels — AI image generation powered by Google Gemini.

[English](./README_EN.md) · 中文

---

一个赛博朋克风格的 AI 图片生成工作站。输入 prompt 生成图片，上传参考图迭代修改。底层调用 Google Gemini 多模态大模型，前端 React，后端 Flask，开箱即用。

## 核心特性

<p align="center">
  <img src="../screenshot.png" alt="Ink Traces WebUI Screenshot" width="100%" />
</p>

| 特性 | 说明 |
|---|---|
| **文生图 / 图生图一体化** | 有参考图自动走图生图，没有就走文生图，零切换 |
| **多轮对话** | Chat 模式下持续迭代，逐步逼近你想要的画面 |
| **思考深度可调** | Minimal（快）/ High（深度推理），按需切换 |
| **Prompt Vault** | 收藏、编辑、搜索常用 prompt，一键复用 |
| **全屏编辑器** | 双击标签页打开 IDE 风格全屏编辑器，带行号，内置 Vault 侧栏 |
| **双 Provider** | Vertex AI / Google AI Studio 运行时一键切换 |
| **双模型** | Gemini 3.1 Flash（快速）/ Gemini 3 Pro（高质量） |
| **Google 搜索增强** | 可选开启，用实时搜索结果辅助生成 |
| **14 种宽高比 x 4 种分辨率** | 从 1:1 到 21:9，从 0.5K 到 4K，自由组合 |
| **可拖拽布局** | 左侧面板宽度随意拖拽，适配不同屏幕 |

## 技术栈

```
Frontend    React 18 · Vite · Tailwind CSS · Framer Motion · Lucide Icons
Backend     Python Flask
AI Engine   Google Gemini API (Vertex AI / AI Studio)
```

## 快速开始

### 前置要求

- Python 3.8+
- Node.js 18+
- Google Gemini API 密钥（[Vertex AI](https://cloud.google.com/vertex-ai) 或 [AI Studio](https://aistudio.google.com/)）

### 启动

```bash
# 1. 配置 API 密钥
cp config.json.example config.json
# 编辑 config.json，填入你的密钥

# 2. 启动（自动安装依赖）
./start.sh

# 3. 打开浏览器 → http://localhost:4545
```

### 停止

```bash
./stop.sh
```

### config.json 示例

```json
{
  "api": {
    "default_provider": "vertex",
    "vertex": {
      "key": "<your-vertex-api-key>",
      "project_id": "<your-gcp-project-id>",
      "endpoint": "aiplatform.googleapis.com"
    },
    "ai_studio": {
      "key": "<your-ai-studio-api-key>",
      "endpoint": "generativelanguage.googleapis.com"
    }
  }
}
```

## 项目结构

```
ink-traces/
├── config.json.example      # 配置示例
├── config.json              # 本地配置（被 .gitignore 忽略）
├── start.sh / stop.sh       # 一键启停
├── server/
│   ├── app.py               # Flask 后端 — 统一 /api/generate 接口
│   ├── prompts.json.example  # Vault 收藏示例数据
│   ├── prompts.json          # 本地 Vault 数据（被 .gitignore 忽略）
│   └── requirements.txt
├── client/
│   └── src/
│       ├── App.jsx           # 主组件（布局、状态、API 调用）
│       └── components/
│           ├── TextToImage.jsx      # Prompt 输入区
│           ├── ImageToImage.jsx     # 参考图上传（最多 14 张）
│           ├── ResultDisplay.jsx    # 画布输出 + 全屏灯箱
│           └── PromptCollection.jsx # Vault 收藏库
└── error_logs/              # API 错误日志（自动记录）
```

## API

统一生成接口，自动判断模式：

```
POST /api/generate
```

| 请求方式 | 触发模式 |
|---|---|
| JSON body（无文件） | 文生图 |
| multipart/form-data（带图片） | 图生图 |

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `prompt` | string | — | 图片描述（必填） |
| `aspect_ratio` | string | `1:1` | 宽高比 |
| `resolution` | string | `2K` | 分辨率 |
| `think_level` | string | `minimal` | 思考深度：`minimal` / `high` |
| `use_search` | bool | `false` | 启用 Google 搜索增强 |
| `enable_chat` | bool | `false` | 启用多轮对话 |
| `session_id` | string | — | Chat 会话 ID |
| `images` | file[] | — | 参考图片（最多 14 张） |

**其他接口：**

| 接口 | 说明 |
|---|---|
| `GET/POST /api/provider` | 获取 / 切换 Provider |
| `GET/POST /api/model` | 获取 / 切换模型 |
| `GET/POST /api/prompts` | 获取 / 收藏 Prompt |
| `PUT/DELETE /api/prompts/:id` | 编辑 / 删除收藏 |

## FAQ

**Q: Vertex AI 和 AI Studio 有什么区别？**
A: AI Studio 是 Google 提供的免费开发者平台，适合个人实验，有速率限制。Vertex AI 是 GCP 的企业级服务，按量计费，速率更高，支持更多配置项（如 `personGeneration`）。两者调用的是同一个 Gemini 模型。

**Q: 为什么生成失败了？**
A: 常见原因：(1) API 密钥无效或过期；(2) Gemini 的安全过滤器拦截了内容（即使 `BLOCK_NONE` 也有底线过滤）；(3) 模型返回了文本但没有图片（换个 prompt 重试）。所有错误会自动记录到 `error_logs/` 目录。

**Q: Chat 模式和普通模式有什么区别？**
A: 普通模式每次请求独立，没有上下文。Chat 模式会保留对话历史，你可以在前一张图的基础上说"把背景换成蓝色"这样的增量修改。会话存在服务器内存中，重启后丢失。

**Q: think_level 设成 High 有什么效果？**
A: High 模式下模型会进行更深入的推理，生成质量通常更好，但耗时更长。Minimal 适合快速迭代，High 适合最终出图。思考过程会显示在画布左上角的 Runtime Log 中。

**Q: 最多能上传多少张参考图？**
A: 14 张。图片会被转为 base64 编码发送给 Gemini API，过多图片会增加请求体积和处理时间。建议控制在 3-5 张以内获得最佳效果。

**Q: 支持哪些图片格式？**
A: PNG、JPG、WebP。上传后会统一转为 PNG 格式发送给 API。单次请求总文件大小限制 100MB。

**Q: 如何调整安全过滤级别？**
A: 编辑 `config.json` 中的 `safety` 字段。可选值：`BLOCK_NONE`（不过滤）、`BLOCK_ONLY_HIGH`、`BLOCK_MEDIUM_AND_ABOVE`、`BLOCK_LOW_AND_ABOVE`。注意即使设为 `BLOCK_NONE`，Gemini 仍有不可关闭的底线过滤。

**Q: 可以部署到远程服务器吗？**
A: 可以。`config.json` 中 `server.host` 和 `client.host` 默认是 `0.0.0.0`，已经监听所有网络接口。确保防火墙放行 4545 和 5000 端口即可。生产环境建议加 Nginx 反向代理和 HTTPS。

## 已知限制

- Chat 会话存储在内存中，服务重启后丢失
- 安全过滤默认全部关闭（`BLOCK_NONE`），可在 `config.json` 中调整
- 后端为单进程模式，不适合高并发场景

## License

MIT
