# Agents.md — Ink Traces WebUI 开发指南

## 项目概述

Ink Traces WebUI 是一个多 Provider AI 图片/视频生成 Web 应用。前后端分离，前端 React，后端 Python Flask。支持 Google Gemini（Vertex AI / AI Studio）和 BytePlus Ark（Seedream 图片 / Seedance 视频）。

GitHub: `darcula1993/Ink_Traces_WebUI`

---

## 架构

```
浏览器 (localhost:4545)
  ↓ Vite dev server proxy /api → localhost:5000
Flask 后端 (localhost:5000)
  ↓ REST API (HTTPS)
  ├── Google Gemini API (Vertex AI 或 AI Studio) — 图片生成
  ├── BytePlus Ark (Seedream 5.0 Lite) — 图片生成
  └── BytePlus Ark (Seedance 2.0) — 视频生成
```

- Vite 开发服务器将 `/api` 请求代理到 Flask 后端（见 `client/vite.config.js`，timeout 300s）
- 所有运行配置集中在本地 `config.json`；仓库只提交 `config.json.example`
- `start.sh` / `stop.sh` 管理前后端进程生命周期
- `clean.sh` 清理临时文件（upload_video/, output/, error_logs/, tasks.db, logs）

---

## 关键文件

| 文件 | 职责 |
|---|---|
| `config.json.example` | 全局配置示例：API 密钥、Provider、模型、端口、安全设置、认证 |
| `server/prompts.json.example` | Prompt Vault 示例数据；本地 `server/prompts.json` 被忽略 |
| `server/app.py` (~1620行) | Flask 后端，所有 API 路由、Gemini/Ark 调用、视频轮询 |
| `server/tasks.py` | SQLite 任务队列 CRUD |
| `client/src/App.jsx` (~1140行) | 主组件，图片/视频双模式、状态管理、API 调用 |
| `client/src/components/TextToImage.jsx` | Prompt 输入 textarea |
| `client/src/components/ImageToImage.jsx` | 参考图上传（点击/粘贴），最多14张 |
| `client/src/components/ResultDisplay.jsx` | 画布输出、全屏灯箱、Runtime Log |
| `client/src/components/VideoResultDisplay.jsx` | 视频结果展示、last frame 显示 |
| `client/src/components/PromptCollection.jsx` | Vault 收藏库 CRUD |
| `client/src/App.jsx` 内联 `LoginPage` | 登录页面 |
| `client/src/App.jsx` 内联 `AuthGate` | 认证守卫（包裹 App） |

---

## 认证系统

- Flask session-based，`@before_request` 中间件检查
- 免认证路径：`/api/login`、`/api/auth/check`、`/api/health`、`/api/upload_video/*`（供 Ark 下载）
- 非 `/api` 路径不拦截（静态资源）
- `config.json` 中 `auth.username` 为空则禁用认证
- 前端 `AuthGate` 与 `LoginPage` 目前内联在 `client/src/App.jsx`，由 `main.jsx` 渲染默认导出的 `AuthGate`

---

## 图片生成

### Provider 切换

三个 Provider 循环切换（前端 NODE 按钮）：
- `vertex` — Google Vertex AI
- `ai_studio` — Google AI Studio
- `ark` — BytePlus Ark (Seedream 5.0 Lite, 0.22元/张)

### 统一生成接口

```
POST /api/generate
```

- 无文件 → 文生图（JSON body）
- 有文件 → 图生图（multipart/form-data）
- Gemini: 支持 14 种宽高比 × 4 种分辨率、思考深度、搜索增强、Chat 模式
- Ark: 仅支持 2K/3K 分辨率，无 think/search/chat

### 图片处理

所有上传图片统一处理：`f.seek(0) → f.read() → Image.open(io.BytesIO(raw)) → convert('RGB') → PNG base64`。确保无论来源（本地上传、fetch URL blob）都能正确转为 PNG。

---

## 视频生成

### Provider

- `ark` — BytePlus Ark (Seedance 2.0)
- `jiekou` — 自定义接口

### 工作流

1. 前端上传参考视频 → `POST /api/upload_video` → 保存到 `upload_video/` 目录 → 返回公网 URL
2. 前端提交生成请求 → `POST /api/video/generate` → 调用 Ark API → 返回 task_id
3. 后台线程轮询 Ark 任务状态 → 完成后下载视频/尾帧到 `output/video/{task_id}/`
4. 前端轮询 `/api/video/task` 获取状态和结果

### 视频模式

- `keyframe` — 首帧/尾帧驱动（上传 first_frame / last_frame 图片）
- `reference` — 参考视频/图片/音频驱动（最多 3 个视频、9 张图片、3 个音频）

### 参考视频预上传

- 文件保存到 `upload_video/` 目录，文件名为 UUID
- 公网 URL 通过 `config.server.public_host/port/scheme` 构建
- `/api/upload_video/<filename>` 路径免认证（Ark 需要直接下载）
- **注意**：Ark 服务器需要能访问到该公网 URL，否则报 `resource download failed`

### 任务恢复

- 服务启动时 `_recover_processing_tasks()` 自动恢复所有 `processing` 状态的视频任务轮询
- 解决服务重启后轮询线程丢失的问题

### 价格估算

前端参数栏右侧显示实时价格估算：
- token 用量 = (输入视频时长 + 输出视频时长) × 宽 × 高 × 帧率 / 1024
- 单价根据模型（2.0/Fast）、分辨率、是否含参考视频区分

---

## 任务队列 (Task Queue)

- SQLite 存储（`tasks.db`），支持图片和视频任务
- 图片任务：同步完成后记录结果
- 视频任务：异步轮询，后台线程更新状态
- 前端 Queue 面板：查看历史、恢复任务、删除任务
- 删除任务时清理关联的 output 目录和上传的视频文件

### 从 Queue 恢复任务

- 图片任务：恢复 prompt、参数、参考图（`local_refs` URL）、生成结果
- 视频任务：恢复 prompt、参数、参考视频 URL、lastFrame（从结果中）
- 参考图提交时有三级 fallback：`file` → `data: URL 解码` → `fetch URL → blob`

---

## 前端状态持久化

- `videoTabs` 通过 `useLocalStorage` 持久化
- `File` 对象无法序列化，恢复后丢失；`preview`（data URL）保留
- 页面加载时：有 `taskId` 的 tab 恢复轮询；无 `taskId` 但 `loading: true` 的强制清除

---

## config.json.example 结构

```json
{
  "auth": { "username": "", "password": "" },
  "server": {
    "host": "0.0.0.0", "port": 5000,
    "public_host": "your-ip", "public_port": 5000, "public_scheme": "http"
  },
  "client": { "host": "0.0.0.0", "port": 4545 },
  "api": {
    "default_provider": "vertex",
    "vertex": { "key": "", "project_id": "", "endpoint": "aiplatform.googleapis.com" },
    "ai_studio": { "key": "", "endpoint": "generativelanguage.googleapis.com" },
    "ark": { "api_key": "", "model": "", "endpoint": "https://ark.ap-southeast.bytepluses.com" }
  },
  "video": {
    "default_provider": "ark",
    "ark": { "api_key": "", "model": "dreamina-seedance-2-0-260128", "endpoint": "..." },
    "jiekou": { "endpoint": "" }
  },
  "safety": "BLOCK_NONE",
  "model": "gemini-3.1-flash-image-preview"
}
```

---

## 开发注意事项

1. **config.json 不要提交真实密钥** — 仓库只保留 `config.json.example`，本地 `config.json` 被 `.gitignore` 忽略
2. **双仓库工作流** — `/root/Nanobanana/`（dev 分支开发）→ rsync 同步到 `/root/Ink_Traces_WebUI/`（排除 config.json、server/prompts.json）→ push GitHub
3. **Ark 视频参考下载** — `public_host` 必须配置为 Ark 可访问的公网地址，`/api/upload_video/` 免认证
4. **图片格式** — 所有上传图片强制转 PNG（Ark 不接受 JPEG 格式的 keyframe）
5. **服务重启** — `./stop.sh && ./start.sh`，视频任务会自动恢复轮询
6. **后端单进程** — Flask debug 模式，不适合高并发
7. **Chat 会话无持久化** — 存在内存中，重启丢失
8. **Vite proxy timeout** — 设为 300s，视频生成可能耗时较长
9. **安全过滤** — Gemini 即使 `BLOCK_NONE` 仍有底线过滤
