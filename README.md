# AzureDust-Elf

AzureDust-Elf 是一个本地优先的自媒体内容创作自动化系统。它用统一的 workflow 和多 agent 分工，把一个选题拆解成微信公众号、小红书、抖音、视频号、B站任意所选平台的内容包，并提供中文创作工作台、后端控制台、任务队列、续跑修复、素材/视频生产包和本地交付目录。

项目默认只在本机生成内容和文件，不会自动发布到任何平台。除非你显式配置外部语音服务相关环境变量，系统也不会调用外部模型。

## 当前版本

当前版本：`v0.1.0`

### v0.1.0 更新说明（2026-06-08）

- 创作工作台支持单个平台、任意平台组合或五个平台全量生成；workflow 会按所选平台裁剪平台分支和视频生产链路。
- 完成任务的“查看”会打开完整生成内容页，支持下载全部内容和按平台下载，不再在工作台内嵌“生成内容预览”。
- “任务与队列状态”会在状态前标注平台名称，左右主卡片在桌面布局下保持顶部和底部对齐。
- 后端控制台新增平台 API Key 只写配置；保存后会刷新运行环境，备份包会排除本地 API Key store。
- Durable job queue、worker、CLI 输出和验收脚本已适配平台裁剪、内容查看页和安全配置路径。

## 主要功能

- 一个选题可生成单个平台、任意平台组合或五个平台全量内容：公众号文章、小红书笔记、短视频脚本、字幕、封面提示词、B站简介和章节等。
- 中文创作工作台：输入选题、选择平台、上传文本/图片/视频素材、查看队列状态，并在完整内容页下载生成结果。
- 中文后端控制台：管理本机状态、配置检查、队列维护、队列任务、备份恢复和环境变量安全状态。
- Durable job queue：支持 run/resume 入队、worker handoff、取消、重试、标记失败、审计日志和历史清理。
- Workflow 续跑与修复：支持 stale detector、retry policy、repair agent 和 human approval gate。
- 视频生产包：为抖音、视频号、B站生成素材任务、封面、分镜、字幕、配音草轨、剪辑工程、项目包和交付索引。
- macOS 桌面启动器：可生成 `自媒体内容创作.app`，像桌面 App 一样启动本地工作台。

## 环境要求

- Python 3.11 或更高版本。
- `make`。
- Python 依赖通过 `pip install -e .` 安装，当前主要依赖为 `Pillow`。
- Docker 是可选项，只用于 Compose 形态运行 console、worker、scheduler。
- macOS 桌面 App 构建需要本机具备 Swift / Xcode Command Line Tools。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
cp .env.example .env
```

`.env` 用于本机运行配置和可选外部服务密钥。不要把真实密钥提交到仓库。

## 启动 Web 控制台

```bash
make console
```

默认地址：

- 创作工作台：`http://127.0.0.1:8080/`
- 后端控制台：`http://127.0.0.1:8080/admin`

如果要指定端口：

```bash
make console CONSOLE_PORT=8091
```

创作工作台用于日常内容生成：输入选题，勾选需要生成的平台，点击 `+` 上传文本、图片或视频素材，加入生成队列，完成后点击“查看”完整阅读并下载内容。

后端控制台用于运维管理：查看本机运行状态、配置检查、队列数据库、任务取消/重试/标记失败、队列历史清理、备份和恢复。

常用后端 API：

- `GET /api/setup-check`：本地配置向导和迁移预检。
- `GET /api/local-runtime`：local runtime readiness，明确 Docker optional。
- `GET /api/queue-health`：queue observability 总览。
- `GET /api/jobs?status=QUEUED`：按状态查看 durable job queue。
- `GET /api/jobs/{job_id}/audit`：查看任务审计日志。
- `POST /api/jobs/cleanup-dry-run`：queue history 清理预览。
- `POST /api/jobs/cleanup`：queue history retention / cleanup，必须提交精确确认短语 `CLEANUP JOBS`。

## 命令行运行

生成一次内容包，默认生成五个平台：

```bash
make run TOPIC="AI内容创作自动化系统"
```

只生成部分平台时传入逗号分隔的平台 ID：

```bash
make run TOPIC="AI内容创作自动化系统" PLATFORMS="wechat,xiaohongshu"
```

续跑已有 run：

```bash
make resume RUN_ID="run_20260519T000000Z"
```

刷新监控报告：

```bash
make monitor RUN_ID="run_20260519T000000Z"
```

worker / scheduler：

```bash
make worker-once
make worker
make scheduler-once
make scheduler
```

Docker Compose 可选运行：

```bash
docker compose up console
docker compose --profile worker up worker
docker compose --profile scheduler up scheduler
```

## macOS 桌面 App

构建本地桌面启动器：

```bash
make build-macos-app
```

生成位置：

```text
自媒体内容创作.app
```

双击 App 后会检查本机控制台是否运行；如果没有运行，会自动执行 `make console CONSOLE_PORT=8091`，然后在原生窗口中打开中文创作工作台。

## 验证

基础验收：

```bash
make validate
```

Phase 5 控制台和本机运行验收：

```bash
make validate-phase5-console
make validate-phase5-migration
make validate-phase5-setup
make validate-phase5-profiles
make validate-phase5-job-queue
make validate-phase5-queue-ops
make validate-phase5-queue-retention
make validate-phase5-local-runtime
make validate-phase5-desktop-app
```

更多 Phase 3 / Phase 4 验收命令见 `Makefile` 和 `docs/IMPLEMENTATION_ROADMAP.md`。

## 输出目录

运行产物写入：

```text
outputs/runs/{run_id}/
```

本地备份写入：

```text
backups/
```

这些目录默认被 `.gitignore` 排除，不会提交到 GitHub。仓库只保存源码、schema、agent/plugin 配置、workflow、脚本和文档。

## 多设备迁移

多设备迁移说明见 `docs/PHASE5_MIGRATION.md`。迁移时需要带走源码、`outputs/`、`backups/`、`.env.example`，并在新设备本地重新注入真实 secret。迁移后建议依次运行：

```bash
make validate
make validate-phase5-console
make validate-phase5-migration
make validate-phase5-setup
make validate-phase5-profiles
make validate-phase5-job-queue
```

## 项目结构

```text
agents/                 Agent 能力定义
plugins/                五个平台插件
registry/               Agent / plugin 注册中心
workflows/              工作流定义
schemas/                JSON Schema
src/content_agent_os/   Python 源码
scripts/                验收和构建脚本
desktop/                macOS 桌面启动器源码
docs/                   设计文档、运行手册和阶段审计
examples/               示例输入
```

## 安全边界

- 控制台只显示 secret 是否存在，不显示真实 secret 值。
- 备份包不包含环境变量。
- Scheduler 默认 dry-run，不会自动创建 run；只有显式关闭 dry-run 或使用 execute 模式才会入队。
- 系统默认不发布内容到外部平台。

## License

MIT License. See `LICENSE`.
