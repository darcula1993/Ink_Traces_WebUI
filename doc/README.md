# Ink Traces WebUI

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="License: MIT" />
  <img src="https://img.shields.io/badge/version-2.5.0-1f6feb?style=flat-square" alt="Version 2.5.0" />
  <img src="https://img.shields.io/badge/stack-React%2018%20%2B%20Flask%20%2B%20SQLite-24292f?style=flat-square" alt="Tech Stack: React 18 + Flask + SQLite" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/node-18%2B-339933?style=flat-square" alt="Node.js 18+" />
</p>

<p align="center">
  <strong>自托管、桌面优先的 AI 图片、视频、音频生成与图层编辑工作台，按「项目 → 画布 → 节点」组织创作。</strong>
</p>

<p align="center">
  <a href="../README.md">English</a> · 中文 · <a href="../CHANGELOG.md">更新日志</a> · <a href="../INSTALL.md">安装指南</a>
</p>

<p align="center">
  <img src="../Banner.png" alt="Ink Traces WebUI Banner" width="100%" />
</p>

<p align="center">
  <img src="../screenshot.png" alt="Ink Traces WebUI Workspace Screenshot" width="100%" />
</p>

## 为什么选择 Ink Traces？

面向需要多镜头、多素材协作创作的个人 AI 短剧创作者与开发者，Ink Traces 聚焦本地私有可控、费用透明与显式工作流：

- **本地私有部署，零平台订阅**：单机部署于 Linux / macOS，采用本地 SQLite（WAL）与本地媒体存储。素材、提示词、角色卡与 API 密钥完全掌握在自己手中，只直接向所选服务商付费。
- **显式可控，杜绝盲目烧钱**：绝不暗中连锁自动生成——只有你主动点击生成、运行所选或运行节点组时才会发起任务。图片、视频与图层分解提交前均展示 3 位小数 USD 费用预估；请求超时且结果未知（`result_unknown`）时**永不**自动重放，避免重复计费。
- **画布、素材库与任务生命周期闭环**：所有项目共用一个按内容去重的全局素材库，画布按 ID 直接引用不留冗余副本；生成历史与任务回收站、删除预览联动，而移出到其他文件夹的复制件通过硬链接独立保留且不额外占空间。
- **网页统一管理多账号 Key，改配免重启**：在浏览器内直接维护多套 BytePlus Ark 与 Cupsy 账号、模型与密钥——严格掩码不回显、支持同服务商 Key 一键同步、自定义与系统默认均可安全软删除，且已提交任务自动冻结不可变配置修订。

## 核心功能总览

### 项目 → 多画布 → 节点工作流
- **曜黑琥珀烟熏液态玻璃工作台与 URL 路由持久化**：全站采用纯黑曜石底（`#050507`）+ `14px` 全圆角烟熏液态玻璃卡片与琥珀金主强调色，媒体预览区保持 100% 纯中性暗底，配「墨痕启幕」开机过渡、48px 窄图标栏与可钉住弹出面板（画布、素材库、角色卡、提示词库、本画布任务）、浏览器 URL 路由持久化（`?project=…&canvas=…`）、左下角小地图与撤销/重做控制。
- **统一右侧属性面板与可靠性护栏**：画布与独立图片/视频/音频四页共享统一右侧参数栏（44px 图标顶栏、36px 带前缀图标单栏控件、可折叠高级参数抽屉、吸底紧凑 3 位小数 USD 预估），内置 Seedance 视频参考/延长 `ratio=adaptive` 前置护栏、报错展开复制与白名单中文修复提示，框选多节点切换为**运行所选**。
- **卡片内提示词、`@角色卡` 折叠徽章与动态参考口**：任意缩放下均可直接在卡片内编辑提示词（前导 `@角色卡` 块默认折叠为 1 行徽章，提交明文逐字节不变），支持 `@图片N` / `@视频N` / `@音频N` 提及与按类型着色的动态参考口（口序号即参考与视频首尾帧顺序）。
- **短剧镜头迭代与结构复用**：单节点支持 2–4 份候选**并排对比**（图片联动缩放、视频默认静音同步播放）、节点与版本**「定稿」**标记及侧栏「仅看定稿」筛选；视频节点一键**「延长此视频 / 编辑此视频」**建下游节点（自动预置 `adaptive`，不自动扣费）；支持将节点组保存为可复用**结构模板**（`/api/canvas/templates`，无内置预设、失效接口只提示不自动换号）以及服务端托管**「运行组内全部」**。
- **场次交付打包与只读连播预览**：顶栏一键**导出本场素材包**（流式 `ZIP_STORED` 按镜号命名媒体 + 脱敏 `shotlist.csv/json`，零凭据/签名 URL/本机路径泄漏，不做合成），并支持纯浏览器只读**「镜头序列连播预览」**弹窗（按序连播视频 + 可选叠 1 条音频，不做剪辑或成片导出）。
- **节点工具条、无损视频分割与上传进度提示**：图片、视频生成、音频及视频素材节点上方均配备快捷操作条——视频素材节点支持**视频分割**弹窗（`ffmpeg` 帧级准确按时间轴自定义切点或按时长均分，无损存为独立新素材并回填画布右侧）、下载、预览、历史版本与更多操作；拖放/粘贴/上传画布素材时实时展示上传进度浮窗；全部项目支持多选批量删除与自动瘦身/孤立磁盘 GC。

### 全局素材库与结果生命周期
- **单一全局库与生成历史溯源筛选**：所有项目共享一个本地素材库，按子文件夹管理（预建 `音效` / `角色` / `场景` / `物品` / `风格`，系统锁定文件夹 `生成历史` 按 `图片` / `视频` / `音频` 归类并支持按项目/画布/定稿只读筛选与脱敏悬停溯源），支持 SHA-256 查重与按需 `ffmpeg` 视频缩略图。
- **任务与生成历史同生命周期**：任务移入回收站时，其在「生成历史」中的结果同步隐藏，恢复任务即重新显示；彻底删除任务或一键清空回收站前，先预览全部受影响的画布、素材组与角色卡，确认后删除生成历史原项并在引用节点留下可替换的「已删除」占位。
- **硬链独立复制件**：从「生成历史」移出/复制到其他文件夹会以硬链接创建独立库项（不额外占用磁盘空间），后续删除任务或清空回收站均不影响该复制件。
- **画布侧栏高效协同**：支持全局素材组（仅引用不复制文件）、侧栏勾选框与 `Ctrl/Cmd` / `Shift` 多选（批量移动/复制、带预览删除、一次拖拽多个素材到画布）、跨画布与跨标签页自动静默刷新、服务端全选与重命名。
- **角色卡与内置图片编辑器**：**角色卡**支持**人物**与**物件**两种模板（新建一步选图保存、描述、最多 8 张参考图、可选最长 30 秒语音参考），在提示词中用 `@` 插入结构化块并支持更新同步；内置**图片编辑器**支持裁剪、90° 旋转、翻转、画笔标注与撤销/重做，另存为新 PNG 不覆盖原图。

### 统一接口管理（网页维护、免重启生效）
- **平等化接口配置与「默认配置」**：首次启动自动将 `config.json` 基础项幂等导入数据库（不改写 `config.json`）；所有配置平等对待（取消“系统默认”区分），每类型可任选一条启用项作为**「默认配置」**用于首次预选，并支持对 Ark `ep-` 接入点显式声明底层模型版本（Seedream 5.5 / 5.0 Pro）。
- **网页内自由增删改与零计费预检**：在**接口管理**页面可直接新增、编辑、启停或删除配置及 API Key，保存即时生效无需重启，并支持零计费静态预检（`POST /api/provider-profiles[/<id>]/check`）。
- **严格密钥边界与一键同步**：API Key 严格掩码展示（`••••••••`），`ep-` ID 在报错与账本中统一脱敏；修改或清除密钥支持一键同步同服务商适配器下的全部配置。
- **安全软删除与历史修订冻结**：任意配置均可安全软删除——释放名称支持同名重建，写入墓碑防止重启重新导入或回退旧 `config.json` 密钥，同时保留历史不可变修订确保在途任务、重试与 Cupsy 素材引用稳定完成。

### 计费安全、成本透明与创作工具
- **防重复计费与真实阶段遥测**：请求超时或结果未知（`result_unknown`）绝不自动重放，签名 URL 绝不暴露给浏览器；长任务展示真实子阶段（`uploading` → `queued` → `generating` → `downloading`）、近 30 天本机同类模型 P50 参考耗时与并行任务数，杜绝假进度条。
- **费用预估、项目费用账本与预算软提醒**：画布、独立工具页与图层工作台统一展示 3 位小数 USD 预估；项目费用账本展示可读配置名并支持设置项目预算软提醒线（超阈黄字提醒不阻断，缺少官方定价的能力单列为**未知**，绝不当作 `$0.000`）。
- **图层工作台（Layer Studio）**：基于 BytePlus Ark Seedream 5.5 将单张图片分解为 2–100 个可编辑图层（默认最大 12 层并给出区间估价），支持选择 Ark 接口配置、从画布直达分解自动归属项目账本、可选 OCR、版本恢复、原分辨率 PNG/JPEG 或 ZIP 导出，以及合成图一键回写原画布。详见 [图层工作台说明](layer-studio.md)。
- **全局任务中心与 Prompt Vault**：全站聚合任务中心（全部/图片/视频/音频/图层）支持服务端搜索、分页、收藏、统一回收站与删除影响预览、批量下载、Prompt Vault 提示词库与全屏提示词编辑器。

## 支持的 Provider 能力矩阵

| 能力 | BytePlus Ark | Cupsy | 说明 |
|---|---|---|---|
| **图片生成** | `Seedream 5.5` | `Seedream 5.0 Pro` | 支持参考图、预设与自定义尺寸、3 位小数 USD 预估 |
| **视频生成** | `Seedance 2.0`、`Seedance 2.5`（需填写 `ep-…` 接入点 ID） | `Seedance 2.5`、`Seedance 2.5 Moderated` | 支持图/视/音参考、按参考口顺序决定首尾帧、480p/720p/1080p、3 位小数 USD 预估 |
| **音频生成** | — | `Seed Audio 1.0` | 支持 MP3 / WAV / OGG Opus，最长 120 秒，支持音色与音频/图像参考（费用记为未知） |
| **图层分解** | `Seedream 5.5`（复用 BytePlus 图片模型） | — | 2–100 个可编辑图层、可选 OCR、原分辨率合成导出与 ZIP 导出 |

> **Provider 配置提示**
> - **BytePlus Seedance 2.5** 需要填写你在 BytePlus 控制台创建的接入点 ID（`ep-…`），可在网页**接口管理**或 `providers.byteplus.endpoint_ids.seedance_2_5` 中配置。
> - **Cupsy** 需要通过公网 HTTP(S) 回源拉取参考素材（配置 `deployment.cupsy_source.base_url`，推荐 HTTPS），详见 [Cupsy 适配说明](cupsy_compatibility.md)。

## 3 步快速启动

**运行环境**：Python 3.10+、Node.js 18+、`ffmpeg`（`PATH` 中可执行 `ffprobe`），以及至少一个 Provider（BytePlus Ark 或 Cupsy）的 API 凭据。

### 1. 准备 `config.json`

```bash
cp config.json.example config.json
```

`config.json` 采用 v2 格式（`"config_version": 2`，已被 Git 忽略，切勿提交）。日常只需在这里配置服务运行与部署项（监听端口、可选登录项 `auth`，以及使用 Cupsy 或 Ark 视频参考时所需的公网回源地址 `deployment`）：
- **推荐在网页配 Key**：`providers.*.api_key` 可先留空，启动后直接进入网页**接口管理**新增或编辑各服务商密钥与模型，保存即生效、无需重启。
- **或预先写入 `config.json`**：首次启动前填入的 Provider 密钥会自动导入 SQLite 作为可编辑的系统默认配置。

可随时使用 `python3 server/config_v2.py check` 校验配置格式。

### 2. 安装依赖

```bash
./setup.sh
```

### 3. 启动服务

```bash
./start.sh
```

在桌面浏览器打开 **<http://localhost:4545>** 即可开始创作；停止服务运行 `./stop.sh`。

完整启停、HTTPS / Nginx 自动化与日常维护请查阅 [INSTALL.md](../INSTALL.md)。已有旧版本升级请遵循 [2.x 升级至 2.2 步骤](../INSTALL.md#6-upgrade-an-existing-2x-installation-to-22) 或 [1.x 升级至 2.0 全局素材库迁移](../INSTALL.md#7-upgrade-from-1x-to-20)。

## 架构与目录概览

Ink Traces 采用单机三组件架构：**React 18 + Vite + Tailwind CSS** 前端（`client/`）、**Flask + Gunicorn** API 服务与独立多池后台 **Worker**（`server/`），底层使用 **SQLite（WAL 模式）** 与本地媒体存储（流式 I/O + 硬链接快照）。运行时性能机制详见 [性能说明](performance.md)。

| 路径 | 内容 |
|---|---|
| `client/` | React 18 + Vite + Tailwind CSS 前端（画布、素材库、图层工作台、任务中心） |
| `server/` | Flask API、独立任务 Worker、SQLite 存储、Provider 适配与后端测试 |
| `deploy/` | Nginx / Certbot / HTTPS 辅助脚本与模板 |
| `scripts/` | 提交前凭据扫描脚本（`secret-scan.sh`）与 1.x → 2.0 素材库迁移脚本 |
| `doc/` | 中文文档与专题指南（`layer-studio.md`、`cupsy_compatibility.md`、`performance.md`） |
| `config.json.example` | 配置文件模板（`config_version: 2`） |
| `setup.sh` `start.sh` `stop.sh` `clean.sh` | 初始化、启停与缓存清理脚本 |

## 开发与测试

自动化测试默认全部使用 mock Provider，绝不发起付费请求。后端测试在检出目录存在真实 `config.json` 时会拒绝运行，请在无 `config.json` 的干净检出目录或 worktree 中执行：

```bash
# 运行后端测试
pip install -r server/requirements-dev.txt
pytest

# 前端生产构建校验
cd client && npm install && npm run build

# 开发模式（前端热更新）
NANOBANANA_FRONTEND_MODE=dev ./start.sh

# 提交前扫描暂存区是否意外包含密钥或凭据
bash scripts/secret-scan.sh
```

## License

本项目采用 **MIT 许可证**发布，详见 [LICENSE](../LICENSE)。
