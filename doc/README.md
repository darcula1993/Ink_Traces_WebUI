# Ink Traces WebUI

<p align="center">
  <img src="../Banner.png" alt="Ink Traces WebUI Banner" width="100%" />
</p>

<p align="center">
  <strong>面向 Gemini、Seedream 和 Seedance 的 AI 图片 / 视频生成工作站。</strong>
</p>

<p align="center">
  <a href="../README.md">English</a> · 中文
</p>

---

## 项目概览

Ink Traces WebUI 是一个本地运行的 AI 图片 / 视频生成工作站。它使用 React/Vite 构建前端，Flask 提供后端 API，支持多 Provider 切换、SQLite 任务队列、Prompt Vault、本地结果恢复，并把真实密钥和本地 Prompt 数据排除在 Git 仓库之外。

<p align="center">
  <img src="../screenshot.png" alt="Ink Traces WebUI Screenshot" width="100%" />
</p>

## 功能亮点

| 模块 | 支持能力 |
|---|---|
| 图片生成 | 文生图和图生图共用一个工作流，自动识别是否有参考图 |
| 视频生成 | 支持首尾帧模式，以及图片、视频、音频参考模式 |
| Provider | Google Vertex AI、Google AI Studio、BytePlus Ark Seedream 5.0 Pro、Ark/Jiekou Seedance |
| Prompt 工作流 | Prompt Vault、全屏编辑器、多标签页、收藏复用 |
| 任务历史 | SQLite 任务队列，支持图片/视频结果记录、恢复和删除 |
| 参数控制 | 宽高比、分辨率、思考深度、Google 搜索增强、Chat 模式 |
| 隐私边界 | 真实 `config.json`、Prompt Vault、日志、输出、上传文件和数据库均不进入 Git |

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | React 18、Vite、Tailwind CSS、Framer Motion、Lucide Icons |
| 后端 | Python Flask、Flask-CORS、Pillow、Requests |
| 存储 | SQLite 任务数据库 + 本地输出目录 |
| AI API | Gemini 图片生成、Ark Seedream 图片生成、Seedance 视频生成 |

## 快速开始

### 环境要求

- Python 3.8+
- Node.js 18+
- 至少准备一个 Provider 的 API 凭据

### 安装并启动

```bash
# 从仓库内的模板创建本地配置
cp config.json.example config.json

# 编辑 config.json，填入 Provider 凭据

# 启动前后端服务
./start.sh
```

浏览器访问：

```text
http://localhost:4545
```

停止服务：

```bash
./stop.sh
```

## 配置说明

仓库只提交模板文件，真实运行文件会被 Git 忽略。

| 文件 | 用途 | Git 状态 |
|---|---|---|
| `config.json.example` | 公开配置模板，所有凭据为空 | 已提交 |
| `config.json` | 本地密钥、端口、Provider、认证配置 | 已忽略 |
| `.flask_secret_key` | 未在配置中设置 secret 时自动生成的本地 Flask session 密钥 | 已忽略 |
| `prompts/video_prompt_rewriter.md` | 视频 Prompt 快速一键重写使用的 system prompt | 已提交 |
| `prompts/video_prompt_optimizer.md` | 交互式视频 Prompt Agent 使用的 skill 风格 system prompt | 已提交 |
| `server/prompts.json.example` | Prompt Vault 示例数据 | 已提交 |
| `server/prompts.json` | 旧版 Prompt Vault 数据，首次使用时导入 SQLite | 已忽略 |

最小图片 Provider 配置示例：

```json
{
  "api": {
    "default_provider": "ark",
    "ark": {
      "api_key": "<your-byteplus-ark-key>",
      "model": "seedream-5-0-pro",
      "endpoint": "https://ark.ap-southeast.bytepluses.com",
      "request_timeout_seconds": 600
    }
  }
}
```

Ark 图片生成的上游接口是同步请求，耗时可能超过两分钟。读取超时会被视为“结果未知”且不会自动重放，避免 Provider 已接收原始 POST 时产生重复生成。

如果使用 Ark 视频参考素材上传，需要配置 `server.public_host`、`server.public_port` 和 `server.public_scheme`，确保外部服务能够下载参考视频文件。

受控部署时建议设置 `auth.secret_key` 或环境变量 `INK_TRACES_SECRET_KEY`。如果都未设置，后端会自动创建已忽略的 `.flask_secret_key`，避免重启后浏览器 session 失效，也不会把密钥提交进仓库。

视频 Prompt 优化需要在 `config.json` 中设置 `openai.api_key`，或导出 `OPENAI_API_KEY`。Quick Fix 使用 `prompts/video_prompt_rewriter.md`；Prompt Agent 使用 `prompts/video_prompt_optimizer.md` 中的 skill 风格工作流。

## 项目结构

```text
Ink_Traces_WebUI/
├── README.md                    # 英文 GitHub 首页 README
├── config.json.example          # 公开配置模板
├── start.sh / stop.sh           # 服务启停脚本
├── clean.sh                     # 本地清理脚本
├── client/                      # React 前端
│   └── src/
│       ├── App.jsx              # 主界面、多标签、图片/视频工作流
│       └── components/          # 上传、结果展示、Vault、任务队列组件
├── server/
│   ├── app.py                   # Flask API 与 Provider 适配
│   ├── worker.py                # 带 lease 的图片执行与视频轮询 Worker
│   ├── tasks.py                 # SQLite 任务、资产、Prompt 与 Worker 状态
│   ├── storage.py               # 媒体原子写入与生命周期清理
│   ├── maintenance.py           # 清理、旧数据瘦身与 VACUUM 工具
│   ├── prompts.json.example     # 公开 Prompt Vault 示例
│   └── requirements.txt
├── doc/
│   ├── README.md                # 中文 README
│   ├── Agents.md                # 开发说明
│   ├── image_doc.md             # 图片 API 说明
│   ├── video_doc.md             # 视频 API 说明
│   └── price.md                 # 价格说明
└── output/                      # 本地生成结果，已忽略
```

## API 概览

| 接口 | 用途 |
|---|---|
| `GET /api/health` | 兼容健康检查 |
| `GET /api/live` / `GET /api/ready` | 进程与依赖就绪检查 |
| `GET/POST /api/provider` | 获取或切换图片 Provider |
| `GET/POST /api/model` | 获取或切换图片模型 |
| `POST /api/generate` | 提交异步图片任务；Chat 模式保持同步 |
| `GET/POST /api/prompts` | 读取或保存 Prompt Vault |
| `PUT/DELETE /api/prompts/:id` | 编辑或删除 Prompt Vault 条目 |
| `GET/POST /api/video/provider` | 获取或切换视频 Provider |
| `POST /api/video/generate` | 提交视频生成任务 |
| `GET /api/video/task` | 兼容旧客户端的本地视频状态查询 |
| `GET /api/tasks` | 查看本地任务历史 |
| `GET/DELETE /api/tasks/:id` | 恢复或删除本地任务 |
| `POST /api/upload_video` | 上传供外部 Provider 下载的参考视频 |

## 运行时数据

以下路径会被 Git 忽略：

- `config.json`
- `.flask_secret_key`
- `server/prompts.json`
- `tasks.db`、`tasks.db-shm`、`tasks.db-wal`
- `output/`
- `upload_video/`
- `error_logs/`
- `*.log`
- `node_modules/`
- `client/dist/`

这可以避免 API 密钥、Prompt 收藏、生成结果、日志、上传素材和本地任务历史进入仓库。

停止服务后可以执行后端维护：

```bash
python3 server/maintenance.py all --grace-hours 24
```

该命令会清理过期或孤立媒体、移除旧任务中的 Base64、执行 WAL checkpoint，并压缩 SQLite 文件。

## 注意事项

- Chat 会话存储在后端内存中，Flask 进程重启后会丢失。
- 普通图片生成和视频轮询由 `start.sh` 启动的有界 SQLite lease Worker 执行。
- 生成媒体保存在文件系统，SQLite 只保存任务和资产元数据，不再保存 Base64 图片。
- Ark 参考视频工作流要求 Provider 能访问你的公网下载 URL。
- 后端默认只允许配置内或本机前端 Origin 跨域访问；如果前端部署在其他域名，需要设置 `server.cors_origins`。
- API 使用 Gunicorn，并与任务 Worker 分进程运行；整体仍面向本地或受控部署。
- `config.json` 可以调整安全过滤级别，但 Provider 侧仍可能有不可关闭的底线过滤。

## License

MIT
