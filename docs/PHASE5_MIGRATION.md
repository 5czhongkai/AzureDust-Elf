# Phase 5 多设备迁移说明

目标：把 Content Agent OS 从一台本地设备迁移到另一台设备，并保持控制台、运行产物、备份/恢复和人工审核边界可用。

## 迁移范围

必须迁移：

- 项目源码目录。
- `outputs/`：包含 workflow run 产物、`outputs/runs/_state/workflow_state.sqlite` 状态库和 restore logs。
- `outputs/runs/_state/console_jobs.sqlite`：durable job queue，保存 console/worker/scheduler 的 job handoff 状态。
- `backups/`：包含 `content_agent_os_backup_*.zip` 本地备份包。
- 本地环境变量配置：从 `.env.example` 重新创建 `.env`，或在 shell / 启动器里注入同名环境变量。

可选迁移：

- `logs/`：仅用于排查历史运行。
- `data/`：仅当后续阶段在其中放入本地数据库或人工素材登记文件时迁移。

不要迁移到仓库或公开渠道：

- `OPENAI_API_KEY`
- `SILICONFLOW_API_KEY`
- `CONTENT_AGENT_OS_TTS_API_KEY`
- 平台 cookie、登录态、上传凭证或人工素材授权凭证
- 未确认版权或未审核的外部素材

## 源设备收口

在源设备先跑：

```bash
make validate
make validate-phase5-console
make validate-phase5-migration
make validate-phase5-setup
make validate-phase5-profiles
make validate-phase5-job-queue
```

启动控制台并创建最新备份：

```bash
make console
```

控制台默认地址是 `http://127.0.0.1:8080`。在 Backups 区域创建备份后，确认 `backups/content_agent_os_backup_*.zip` 已生成。

## 迁移文件

把以下内容复制到新设备的项目目录：

```text
outputs/
backups/
```

如果要继续 resume 旧 run，必须确认以下文件也在 `outputs/` 内一起迁移：

```text
outputs/runs/_state/workflow_state.sqlite
outputs/runs/_state/console_jobs.sqlite
```

不要直接复用旧设备上的真实 `.env` 文件，除非它通过安全本地渠道传输。推荐在新设备从 `.env.example` 重新创建，并只填入当前设备需要的 secret。

## 新设备启动

在新设备项目目录执行：

```bash
make validate
make validate-phase5-console
make validate-phase5-migration
make validate-phase5-setup
make validate-phase5-profiles
make validate-phase5-job-queue
make console
```

控制台首页的 Setup Check 区块会显示本机 Python、workflow、五平台集合、`outputs/`、`backups/`、resume 状态库、最新备份和 secret presence。也可以直接调用：

```http
GET /api/setup-check
```

该接口只返回 secret 名称和 present/missing 状态，不返回 secret 值。若 `status=bad`，先修复 workflow 或平台集合；若 `status=warn`，通常是新设备还没有 `outputs/`、`backups/`、状态库、备份或本地 secret。

如果新设备只拿到了 `backups/`，没有拿到完整 `outputs/`，先启动控制台，使用备份区的 `Dry-Run Restore` 查看将恢复的文件和覆盖数量。实际恢复必须输入精确确认短语：

```text
RESTORE <backup-name>
```

也可以通过 API 做同样操作：

```http
POST /api/restore-dry-run
{"backup":"content_agent_os_backup_YYYYMMDDTHHMMSSffffffZ_xxxxxxxx.zip"}
```

```http
POST /api/restore
{"backup":"content_agent_os_backup_YYYYMMDDTHHMMSSffffffZ_xxxxxxxx.zip","confirmation":"RESTORE content_agent_os_backup_YYYYMMDDTHHMMSSffffffZ_xxxxxxxx.zip"}
```

restore 只恢复备份包里安全路径内的 `outputs/runs/` 文件，并写入 `outputs/runs/_restore_logs/`。如果 dry-run 显示 `safe_to_restore=false`，不要恢复该备份。

## Worker / Scheduler Profiles

迁移后可先跑 profile dry-run 验收：

```bash
make validate-phase5-profiles
make validate-phase5-job-queue
make scheduler-once
```

`make scheduler-once` 默认只写 `outputs/runs/_scheduler/scheduler_tick_*.json`，不创建 workflow run，也不写 queued job。确认本机 topic、secret 和素材边界都准备好后，才把 `CONTENT_AGENT_SCHEDULER_DRY_RUN` 或 `SCHEDULER_DRY_RUN` 设为 `0`。关闭 dry-run 后，scheduler 只 enqueue run job，真正执行由 `make worker` 或 `make worker-once` 消费 durable job queue 完成。

Docker 可用时，可额外验证：

```bash
docker compose --profile worker up worker
docker compose --profile scheduler up scheduler
```

## Docker 状态

Docker 不是本地迁移的必需条件。没有 Docker 时，使用：

```bash
make console
```

如果新设备有 Docker，可额外验证 Compose 控制台：

```bash
docker compose up console
```

当前本机没有 Docker，所以 Compose 实机启动仍是可选的外部环境验证项，不阻塞 Python 本地控制台和备份/恢复迁移。

## 迁移验收标准

迁移完成后应满足：

- `make validate` 通过。
- `make validate-phase5-console` 通过。
- `make validate-phase5-migration` 通过。
- `make validate-phase5-setup` 通过。
- `make validate-phase5-profiles` 通过。
- `make validate-phase5-job-queue` 通过。
- 控制台 `/healthz` 为 `ok`。
- `/api/setup-check` 返回 `schema_version=phase5.setup_check.v1`，并且不包含任何 secret 值。
- `/api/env` 只显示 secret 是否存在，不显示 secret 值。
- Backups 区域能看到迁移过来的备份包。
- `Dry-Run Restore` 能列出文件数量、覆盖数量和路径安全结果。
- 任何实际 restore 都必须先输入精确 `RESTORE <backup-name>` 确认短语。

## 失败处理

- 如果 `make validate-phase5-console` 失败，先检查 Python 版本、`PYTHONPATH=src`、`outputs/` 和 `backups/` 是否存在。
- 如果 `make validate-phase5-setup` 失败，先打开控制台 Setup Check 或调用 `GET /api/setup-check`，按 `bad` 项优先修复。
- 如果旧 run 不能 resume，检查 `outputs/runs/_state/workflow_state.sqlite` 是否已迁移。
- 如果 restore dry-run 报 unsafe entries，保留备份文件但不要恢复。
- 如果 secret 显示 missing，在新设备本地重新注入环境变量，不要把 secret 写入文档、README 或备份包。
