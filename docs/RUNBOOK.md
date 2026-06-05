# 运行手册

## 本地校验

```bash
make validate
```

校验内容：

- 必要目录存在
- 必要文件存在
- JSON Schema 可被解析
- agent registry 包含 V0 要求的 agent
- plugin registry 包含 V0 要求的平台
- 示例 workflow 包含五个平台产出步骤

## Phase 5 控制台

```bash
make console
```

默认会在 `http://127.0.0.1:8080` 启动本地控制台。可通过以下变量覆盖：

- `CONSOLE_HOST`
- `CONSOLE_PORT`
- `OUTPUT_ROOT`
- `BACKUP_ROOT`
- `PLATFORMS`

控制台提供：

- `GET /healthz`：服务健康状态。
- `GET /api/env`：环境变量状态；secret 只显示 present/missing，不返回值。
- `GET /api/setup-check`：本地配置向导检查；覆盖 Python、workflow、五平台集合、`outputs/`、`backups/`、resume 状态库、最新备份和 secret presence。
- `GET /api/runs` 与 `GET /api/runs/{run_id}`：查看 run 列表和监督摘要。
- `POST /api/runs`：后台发起新 workflow run；当前要求使用完整五平台集合，以保持 Phase 4 三端视频交付链路完整。
- `POST /api/runs/{run_id}/resume`：后台恢复既有 run。
- `POST /api/backups`：把 `outputs/runs/` 打成 `backups/content_agent_os_backup_*.zip`。
- `POST /api/restore-dry-run`：读取指定备份包的恢复预检，返回将恢复文件、覆盖数量和路径安全检查结果，不解压、不覆盖文件。
- `POST /api/restore`：必须提供精确 `RESTORE <backup-name>` 确认短语，才会恢复该备份中安全路径内的 `outputs/runs/` 文件，并写入 `_restore_logs/`。

Docker Compose 启动同一控制台：

```bash
docker compose up console
```

边界：

- 控制台不会登录平台、上传文件、发布内容或执行 external mirror sync。
- `.env.example` 只提供变量名；真实 secret 通过环境变量或本地 `.env` 注入，不能提交到仓库。
- 备份包只包含 `outputs/runs/` 文件，不包含环境变量或 secret 值。
- restore dry-run 只读取备份 ZIP 文件清单，不执行恢复写入。
- confirmed restore 只接受备份目录中的 `content_agent_os_backup_*.zip`，拒绝逃逸路径，并且必须先给出精确确认短语。
- 2026-06-03 本机 Playwright 自带浏览器不可用，控制台 UI 改用 HTTP/HTML/API 验证；本机缺少 Docker 命令，`docker compose up console` 仍需在 Docker 可用环境实机验证。

验收：

```bash
make validate-phase5-console
```

## Phase 5 控制台入口

本地控制台现在分成两个中文界面：

- `http://127.0.0.1:8080/`：创作工作台，用于输入选题、上传文本/图片/视频素材、查看队列状态、预览和下载平台生成内容。
- `http://127.0.0.1:8080/admin`：后端控制台，用于管理本机状态、配置检查、队列维护、队列任务、备份恢复和环境变量安全状态。

桌面 App 会默认进入创作工作台；需要运维时，从顶部的“后端控制台”进入 `/admin`。

## Phase 5 本地配置向导

后端控制台 `/admin` 的配置检查区块和 `GET /api/setup-check` 会返回 `schema_version=phase5.setup_check.v1`，并把本地启动状态归为 `ok`、`warn` 或 `bad`：

- `bad`：workflow 文件或五平台集合这类阻塞项不满足。
- `warn`：新设备常见的非阻塞缺口，例如还没有 `outputs/`、`backups/`、`outputs/runs/_state/workflow_state.sqlite`、本地备份或 secret。
- `ok`：基础运行、迁移和 secret presence 检查均满足。

该接口只展示 secret 名称和 present/missing 状态，不返回 secret 值。推荐本地验收：

```bash
make validate-phase5-setup
```

如果 setup check 提示缺少 secret，在新设备本地重新注入环境变量；不要把真实 secret 写入 README、runbook、迁移文档或备份包。

## Phase 5 Local Runtime

本机运行不需要 Docker。Docker Compose 是 optional 部署形态，本机主路径是 Python + make commands；这个区块就是 Phase 5 local runtime 的操作入口。

后端控制台 `/admin` 的本机状态区块和 `GET /api/local-runtime` 会返回：

- `make console`：启动本地控制台。
- `make worker-once`：消费一个 queued job 后退出。
- `make worker`：长期消费 durable job queue。
- `make scheduler-once`：写入一次 dry-run scheduler tick。
- `make scheduler`：长期 scheduler，默认 dry-run。
- `docker compose up console`：optional，不影响本机运行 readiness。

本机验收：

```bash
make validate-phase5-local-runtime
```

如果 `Docker` 显示 unavailable，只代表当前设备未安装 Docker；只要 Local Runtime 为 `ok`，仍可继续使用本机 console、worker 和 scheduler。

## Phase 5 Desktop App

macOS 本机可以生成一个可双击启动的桌面 App，不需要先打开浏览器预览：

```bash
make build-macos-app
```

生成位置：

```text
自媒体内容创作.app
```

双击 `自媒体内容创作.app` 后，启动器会先检查 `http://127.0.0.1:8091/healthz`；如果本机服务还没运行，会自动在项目目录执行 `make console CONSOLE_PORT=8091`，然后在原生窗口中进入中文工作台。启动日志写入：

```text
outputs/runs/_state/desktop_app_console.log
```

验收：

```bash
make validate-phase5-desktop-app
```

如果要改端口，可以在启动 App 前设置 `CONTENT_AGENT_CONSOLE_PORT`；如果把 App 移出项目目录，需要设置 `CONTENT_AGENT_PROJECT_ROOT` 指回本项目目录。

## Phase 5 Worker / Scheduler Profiles

本地 worker 消费 durable job queue。队列数据库位于：

```text
outputs/runs/_state/console_jobs.sqlite
```

长期 worker：

```bash
make worker
```

只消费一个 queued job 并退出：

```bash
make worker-once
```

本地 scheduler 默认 dry-run，只写一次 scheduler tick，不创建 workflow run：

```bash
make scheduler-once
```

长期 scheduler：

```bash
make scheduler SCHEDULE_INTERVAL_SECONDS=86400
```

默认 `SCHEDULER_DRY_RUN=1`，等价于环境变量 `CONTENT_AGENT_SCHEDULER_DRY_RUN=1`。只有显式设置为 `0`，或直接运行 `python3 -m content_agent_os.scheduler --execute`，scheduler 才会按 tick enqueue 一个 run job。真正执行由 worker claim 后完成。

Docker Compose profiles：

```bash
docker compose --profile worker up worker
docker compose --profile scheduler up scheduler
```

profile 验收：

```bash
make validate-phase5-profiles
```

该验收会检查 worker/scheduler Compose profiles、`.env.example` 调度变量、Makefile targets、文档登记和 scheduler dry-run tick。当前本机没有 Docker，因此 Compose profile 实机启动仍需在 Docker 可用环境验证。

durable job queue / worker handoff 验收：

```bash
make validate-phase5-job-queue
```

该验收会检查 console enqueue 后 job 可跨 runtime restart 保留，worker 能消费 queued run/resume job，scheduler dry-run 不入队，scheduler execute mode 只 enqueue，随后由 worker 执行。

queue observability / operations panel 验收：

```bash
make validate-phase5-queue-ops
```

后端控制台 `/admin` 的队列任务面板会显示 queue health、job DB path、worker id、started/ended/updated 时间、error 和操作按钮。API：

- `GET /api/queue-health`
- `GET /api/jobs?status=QUEUED`
- `GET /api/jobs/{job_id}/audit`
- `POST /api/jobs/{job_id}/cancel`
- `POST /api/jobs/{job_id}/retry`
- `POST /api/jobs/{job_id}/mark-failed`

操作边界：Cancel 只允许 `QUEUED` job，Retry 只允许 `FAILED` / `CANCELED` job，Mark Failed 只允许 `RUNNING` job。所有操作都会写入本地 audit log，retry 会创建新的 queued job，不会重写旧 job。

queue history / retention / cleanup 验收：

```bash
make validate-phase5-queue-retention
```

Retention 配置：

- `CONTENT_AGENT_JOB_RETENTION_DAYS`：terminal job 历史保留天数，默认 30。
- `CONTENT_AGENT_AUDIT_RETENTION_DAYS`：audit log 保留天数，默认 90。

Cleanup API：

- `POST /api/jobs/cleanup-dry-run`：预览将删除的 terminal jobs 和 audit rows，不执行删除。
- `POST /api/jobs/cleanup`：必须提交精确确认短语 `CLEANUP JOBS`。

Cleanup 只处理 `DONE` / `FAILED` / `CANCELED` 历史，永远不删除 `QUEUED` / `RUNNING` job。

## Phase 5 多设备迁移

迁移说明见：

```text
docs/PHASE5_MIGRATION.md
```

迁移文档验收：

```bash
make validate-phase5-migration
```

该验收会检查迁移说明是否覆盖 `outputs/`、`backups/`、`outputs/runs/_state/workflow_state.sqlite`、secret 边界、新设备启动命令、setup check、restore dry-run、显式 `RESTORE <backup-name>` 确认和 Docker 可选验证。

## 真实 Workflow Runner

```bash
make run TOPIC="AI内容创作自动化系统"
```

该命令会读取 `workflows/one_topic_multi_platform.yaml`，按 step 依赖顺序执行，并在 `outputs/runs/{run_id}/` 下写入：

- `workflow_run.json`
- `artifact_manifest.json`
- `logs/tasks/*.json`
- `asset_plan.json`
- `cover_prompts.md`
- `assets/asset_generation_tasks.json`
- `assets/media_asset_manifest.json`
- `assets/asset_ingest_guide.md`
- `assets/{platform}/cover/cover.png`
- `assets/{platform}/cover/cover_metadata.json`
- `assets/{platform}/storyboard/storyboard_preview.png`
- `assets/{platform}/storyboard/storyboard_preview_metadata.json`
- `assets/{platform}/storyboard/{shot_id}.png`
- `assets/{platform}/materials/material_manifest.json`
- `assets/{platform}/materials/README.md`
- `assets/{platform}/materials/{asset_id}_reference.png`
- `assets/{platform}/licensed_media/ingest_manifest.json`
- `assets/{platform}/licensed_media/README.md`
- `assets/{platform}/licensed_media/review_handoff.md`
- `assets/{platform}/licensed_media/proxy_manifest.json`
- `assets/{platform}/licensed_media/replacement_suggestions.json`
- `assets/{platform}/licensed_media/proxy/README.md`
- `assets/{platform}/licensed_media/proxy/{asset_id}_proxy.*`（仅当人工登记素材已审核可替换时生成）
- `assets/{platform}/edit/replacement_instructions/instruction_manifest.json`
- `assets/{platform}/edit/replacement_instructions/replacement_commands.json`
- `assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml`
- `assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md`
- `assets/{platform}/edit/replacement_instructions/README.md`
- `assets/{platform}/edit/replacement_execution/execution_manifest.json`
- `assets/{platform}/edit/replacement_execution/execution_plan.json`
- `assets/{platform}/edit/replacement_execution/execution_audit_log.json`
- `assets/{platform}/edit/replacement_execution/human_execution_approval_request.md`
- `assets/{platform}/edit/replacement_execution/README.md`
- `assets/{platform}/edit/mutation_sandbox/mutation_manifest.json`
- `assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml`
- `assets/{platform}/edit/mutation_sandbox/mutation_diff.json`
- `assets/{platform}/edit/mutation_sandbox/rollback_manifest.json`
- `assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json`
- `assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md`
- `assets/{platform}/edit/mutation_sandbox/README.md`
- `assets/{platform}/edit/software_import_executor/import_executor_manifest.json`
- `assets/{platform}/edit/software_import_executor/import_plan.json`
- `assets/{platform}/edit/software_import_executor/import_commands.json`
- `assets/{platform}/edit/software_import_executor/software_import_audit_log.json`
- `assets/{platform}/edit/software_import_executor/rollback_safety_report.json`
- `assets/{platform}/edit/software_import_executor/isolated_execution_request.md`
- `assets/{platform}/edit/software_import_executor/README.md`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json`
- `assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json`
- `assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md`
- `assets/{platform}/edit/software_real_runner_sandbox/README.md`
- `{platform}/timed_subtitles.json`
- `{platform}/timed_subtitles.srt`
- `assets/{platform}/voiceover/voiceover.wav`
- `assets/{platform}/voiceover/voiceover_manifest.json`
- `assets/{platform}/edit/edit_timeline.json`
- `assets/{platform}/edit/edit_manifest.json`
- `assets/{platform}/edit/draft_cut.edl`
- `assets/{platform}/edit/project.fcpxml`
- `assets/{platform}/edit/import_readme.md`
- `assets/{platform}/edit/offline_media_report.json`
- `assets/{platform}/edit/export_manifest.json`
- `assets/{platform}/bundle/project_bundle.zip`
- `assets/{platform}/bundle/project_bundle_manifest.json`
- `assets/{platform}/bundle/file_manifest.json`
- `assets/{platform}/bundle/README.md`
- 五个平台的草稿产物
- `final/content_package_manifest.json`
- `final/video_production_package.json`
- `final/materialization_manifest.json`
- `final/licensed_media_ingest_manifest.json`
- `final/licensed_media_proxy_manifest.json`
- `final/editor_replacement_instruction_manifest.json`
- `final/editor_replacement_execution_manifest.json`
- `final/editor_project_mutation_manifest.json`
- `final/editor_software_import_manifest.json`
- `final/editor_software_real_runner_manifest.json`
- `final/editor_software_run_evidence_manifest.json`
- `final/edit_project_manifest.json`
- `final/export_project_manifest.json`
- `final/project_bundle_manifest.json`
- `final/delivery_index.json`
- `final/delivery_readme.md`
- `artifact_store/artifact_store_manifest.json`
- `artifact_store/README.md`
- `artifact_store/download_index.md`
- `artifact_store/checksums.sha256`
- `artifact_store/downloads/{platform}_project_bundle.zip`
- `artifact_store/external_mirror_plan.json`
- `artifact_store/sync_command_preview.md`
- `artifact_store/human_distribution_approval_request.md`
- `artifact_store/external_mirror_readme.md`
- `final/review_report.md`

V1 step 7 中，`research-agent`、`topic-agent`、`outline-agent`、`wechat-article-agent`、`xiaohongshu-note-agent`、`douyin-video-agent`、`shipinhao-video-agent` 和 `bilibili-video-agent` 已经通过 `run_agent(task_spec)` 执行。V1 step 8 统一了视频号 agent 命名为 `shipinhao-video-agent`，并把它保留在默认 workflow 与默认平台列表中，`shipinhao/` 输出契约不变。Phase 4 step 1 后，`asset-agent` 也已接入真实 handler，视频平台会额外输出 shot list、B-roll list、cover prompt，并汇总到 `final/video_production_package.json`。Phase 4 step 2 后，素材层会额外生成素材任务包和媒体资产清单，但仍不自动生成、下载、导入或剪辑媒体。Phase 4 asset materialization 后，`asset-materialization-agent` 会为 B-roll 槽位生成本地自制 reference PNG、material manifest 和 README，并由 `final/materialization_manifest.json` 汇总三端素材实物化状态；这些 reference 只用于审核和剪辑替换参考，最终 licensed media 仍需人工提供。Phase 4 licensed media ingest 后，`licensed-media-ingest-agent` 会根据 reference PNG 生成本地授权素材接收清单、README 和 review handoff，并由 `final/licensed_media_ingest_manifest.json` 汇总三端人工素材交接状态；该层不搜索、下载、购买、上传、发布或打开剪辑软件。Phase 4 licensed media proxy 后，`licensed-media-proxy-agent` 会把 `human_media_registry.json` 中已审核的本地人工素材推进为 `replacement_suggestions.json` 和本地 proxy copy，并由 `final/licensed_media_proxy_manifest.json` 汇总三端替换建议状态；该层只复制本地人工登记素材，不搜索、下载、购买、上传、发布或打开剪辑软件。Phase 4 editor replacement instructions 后，`editor-replacement-instructions-agent` 会把 `replacement_suggestions.json` 转成 FCPXML 导入模板、dry-run replacement commands、人工确认 checklist 和 README，并由 `final/editor_replacement_instruction_manifest.json` 汇总三端指令状态；该层不打开剪辑软件、不修改工程文件、不执行替换。Phase 4 editor replacement execution 后，`editor-replacement-execution-agent` 会把 dry-run commands 转成执行预检计划、审计日志和人工执行批准请求，并由 `final/editor_replacement_execution_manifest.json` 汇总三端预检状态；默认无 `human_execution_approval.json` 时全部阻断，即使存在有效批准也只标记 `ready_for_manual_execution`，仍不打开剪辑软件、不修改工程文件、不执行替换。Phase 4 editor project mutation sandbox 后，`editor-project-mutation-sandbox-agent` 会把显式批准后的 ready execution plan 推进为 patched FCPXML 沙盒副本、diff、rollback manifest、audit log 和最终人工审核 checklist，并由 `final/editor_project_mutation_manifest.json` 汇总三端工程副本改写状态；默认无 `human_mutation_approval.json` 时只生成未改写副本，有效批准也只改写 `mutation_sandbox/patched_project.fcpxml`，不修改原始工程、不打开剪辑软件、不执行替换。Phase 4 editor software import executor 后，`editor-software-import-executor-agent` 会生成隔离导入计划、dry-run/manual command preview、rollback safety report 和人工导入请求，并由 `final/editor_software_import_manifest.json` 汇总三端导入计划状态；有效批准也只标记 `ready_for_isolated_manual_import`，仍不打开剪辑软件、不执行导入、不修改工程。Phase 4 editor software real runner sandbox 后，`editor-software-real-runner-sandbox-agent` 会生成环境快照、launch plan、command preview、evidence manifest 和 human real-run approval request，并由 `final/editor_software_real_runner_manifest.json` 汇总三端真实软件启动前状态；有效批准也只标记 `ready_for_manual_external_sandbox_launch`，仍不 spawn 进程、不打开剪辑软件、不执行导入。Phase 4 editor software run evidence 后，`editor-software-run-evidence-agent` 会接收人工外部真实运行后的 `human_real_run_result.json` 和证据文件，生成 `real_run_evidence_manifest.json`、validation report、rollback decision、post-launch checklist 和 README，并由 `final/editor_software_run_evidence_manifest.json` 汇总三端 closeout 状态；该层只 ingest 人工证据，仍不 spawn 进程、不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。Phase 4 step 3 后，封面图会由本地 Pillow 适配器生成 PNG 草图，写入 `assets/{platform}/cover/cover.png` 和 `assets/{platform}/cover/cover_metadata.json`，仍保持待人工审核。Phase 4 step 4 后，`storyboard-preview-agent` 会为三个视频平台生成分镜关键帧预览图、preview metadata 和逐帧 keyframe PNG，写入 `assets/{platform}/storyboard/`，仍保持待人工审核。Phase 4 step 5 后，`subtitle-timing-agent` 会把原始 `subtitles.srt` 校正为贴合 storyboard shot window 的 `timed_subtitles.json` 和 `timed_subtitles.srt`，作为后续 TTS 或剪辑时间轴输入。Phase 4 step 6 后，`voiceover-tts-agent` 会读取 `timed_subtitles.json`，默认生成本地配音草轨 WAV 和 `voiceover_manifest.json`；显式设置 `CONTENT_AGENT_OS_TTS_PROVIDER=openai` 或 `CONTENT_AGENT_OS_TTS_PROVIDER=siliconflow` 且提供有效 API key 时，可调用外部自然语音 TTS provider，并在 manifest 中记录 provider、audio_generation_mode、rights_status 和人工审核边界。Phase 4 step 7 后，`edit-project-agent` 会把 storyboard keyframes、timed subtitles、voiceover 和 B-roll 槽位组装成本地剪辑时间线 JSON、edit manifest 和 EDL 草稿，并由 `final/edit_project_manifest.json` 汇总三端交付物。Phase 4 step 8 后，`export-project-agent` 会把剪辑时间线导出为本地 FCPXML 草稿工程、导入说明和 offline media report，并由 `final/export_project_manifest.json` 汇总三端工程交付物。Phase 4 step 9 后，`project-bundle-agent` 会把工程交付物、replacement instructions、replacement execution 预检文件、mutation sandbox、software import executor、real runner sandbox 和 run evidence closeout 文件打成本地 ZIP 包、文件清单和 bundle README，并由 `final/project_bundle_manifest.json` 汇总三端 ZIP 交付物。Phase 4 step 10 后，`delivery-index-agent` 会生成 `final/delivery_index.json` 和 `final/delivery_readme.md`，记录每个 ZIP 的路径、大小、SHA-256 和人工交付边界。

Phase 4 step 11 后，`artifact-store-agent` 会把 delivery index 中的 ZIP 复制到 `artifact_store/downloads/`，生成 `artifact_store_manifest.json`、download index、checksum 文件、README 和 delivery index 副本；该层只做本地文件复制，不同步外部存储、不登录、不上传、不发布。

Phase 4 step 12 后，`external-mirror-plan-agent` 会读取 artifact store，重新校验本地 ZIP，生成 `external_mirror_plan.json`、`sync_command_preview.md`、`human_distribution_approval_request.md` 和 README；该层只做计划和命令预览，不同步外部存储、不登录、不上传、不发布、不访问网络。

当前仍然不调用模型、不打开浏览器、不发布内容。

## Resume 与状态库

```bash
make resume RUN_ID="run_20260519T000000Z"
```

`resume` 会读取 `outputs/runs/_state/workflow_state.sqlite`，里面有两张表：

- `workflow_run`：一次运行的当前快照
- `task_ledger`：每个 step 的尝试记录和失败分类

当某次 run 失败后，先补齐缺失的上游文件或其他人工修复，再执行 `make resume`。当前实现会保留 `workflow_run.json` 作为快照，同时把历史尝试留在 SQLite 里，便于后续恢复和排错。

## 运行监督与故障可视化

每次 `make run` 或 `make resume` 都会自动刷新监督文件：

- `monitor/supervision_snapshot.json`：给程序读取的监督快照
- `monitor/supervision_report.md`：给人阅读的运行报告，包含 Mermaid workflow failure map
- `monitor/failure_dashboard.html`：本地 HTML 故障看板

也可以单独刷新某次运行：

```bash
make monitor RUN_ID="run_20260519T000000Z"
make logs RUN_ID="run_20260519T000000Z"
```

如果 `RUN_ID` 为空，默认读取最新的 `outputs/runs/run_*`。监督快照会汇总：

- workflow 当前状态、完成进度和失败数量
- 每个 step 的 agent、平台、状态、尝试次数、耗时、日志路径
- 每个 step 声明产物是否存在
- 失败分类、失败消息、恢复建议
- 下一步建议命令，例如 `make resume RUN_ID="..."`

## Stale Task Detector

Phase 3 step 2 后，监督层会自动识别卡住或中断的 `RUNNING` task：

- 默认阈值：30 分钟，可通过 `CONTENT_AGENT_OS_STALE_AFTER_MINUTES` 调整。
- `monitor` 会把超过阈值的 `RUNNING` task 标记为 `stale`，并作为可恢复故障写入监督报告。
- `resume` 会把上一次遗留的 `RUNNING` attempt 识别为 `stale` 或 `interrupted`，先转成 `ENV_ERROR` 可恢复失败，再重跑该 step。
- 检测结果会写入 `monitor/supervision_snapshot.json` 的 `stale_detector` 和每个 task 的 `health` 字段。

可单独运行验收脚本，验证 health 分类、监督快照接线和 `resume` 转换逻辑：

```bash
make validate-stale-detector
```

## Retry Policy

Phase 3 step 3 后，`resume` 会把 stale detector 标出的可恢复故障按策略自动补跑：

- 默认开启：`CONTENT_AGENT_OS_RETRY_POLICY_ENABLED=1`
- 默认预算：每个 step 最多自动补跑 1 次，可通过 `CONTENT_AGENT_OS_MAX_AUTO_RETRIES` 调整。
- 默认只自动补跑 `ENV_ERROR` 且 `recovery_state` 为 `stale` 或 `interrupted` 的可恢复故障。
- `POLICY_ERROR`、`PERMISSION_ERROR`、`SCHEMA_ERROR`、`QUALITY_ERROR` 和 `DATA_ERROR` 默认不自动补跑，保留人工处理。
- 每次自动补跑会写入 `retry_events`，并在 task log 的 `retry_policy` 字段中保留决策。
- 超出预算后会记录 `blocked` / `budget_exhausted`，workflow 保持 `FAILED`，等待人工判断。

```bash
make validate-retry-policy
```

## Repair Agent 与 Repair Log

Phase 3 step 4 后，不可自动重试的失败会进入诊断链路：

- `repair-agent` 会读取失败信息、失败 task spec 和 retry policy 决策。
- 输出 `repair/{step_id}_repair_plan.md` 与 `repair/{step_id}_repair_plan.json`。
- 总 repair 索引写入 `repair/repair_log.json`，同时进入 `workflow_run.json` 和监督快照。
- 当前 repair-agent 只提供 root cause hypothesis 和 recommended actions，不自动 patch、不自动发布。
- `manual_required=true` 的修复建议会把 workflow 暂停到 `NEEDS_HUMAN`，必须先执行 `make approve-repair RUN_ID="..." REPAIR_ID="..."`，再执行 `make resume`。
- 审批记录会写入 `repair/repair_log.json`，并刷新 `monitor/supervision_snapshot.json` 与 `monitor/failure_dashboard.html`。

```bash
make validate-repair-agent
make validate-human-approval-gate
```

## Phase 3 总验收

Phase 3 step 6 后，可以用一个入口完成监督与修复闭环演练：

```bash
make validate-phase3
```

该命令会串联 stale detector、retry policy、repair-agent、repair log、human approval gate 和 approval 后 resume replay。通过后，Phase 3 的核心故障恢复链路视为可进入 Phase 4。

## Phase 4 视频生产包

Phase 4 step 1 后，默认 workflow 会把文字内容包升级为视频生产包：

- `visual_assets` step 调用 `asset-agent` 生成 `asset_plan.json` 与 `cover_prompts.md`。
- `douyin-video-agent`、`shipinhao-video-agent`、`bilibili-video-agent` 会读取 `asset_plan.json`。
- 每个视频平台都应有脚本、分镜、字幕、shot list、B-roll list 和封面提示。
- `final/video_production_package.json` 汇总每个平台的可交付项、素材规划、生产检查清单和边界说明。
- 仍然不自动下载素材、不自动剪辑、不登录、不上传、不发布。

```bash
make validate-phase4-video-package
make validate-phase4-assets
make validate-phase4-asset-materialization
make validate-phase4-licensed-media-ingest
make validate-phase4-licensed-media-proxy
make validate-phase4-editor-replacement-instructions
make validate-phase4-editor-replacement-execution
make validate-phase4-editor-project-mutation-sandbox
make validate-phase4-editor-software-import-executor
make validate-phase4-editor-software-real-runner-sandbox
make validate-phase4-editor-software-run-evidence
make validate-phase4-cover-adapter
make validate-phase4-storyboard-adapter
make validate-phase4-subtitle-timing
make validate-phase4-voiceover-tts
make validate-phase4-voiceover-tts-siliconflow
make validate-phase4-edit-project
make validate-phase4-export-project
make validate-phase4-project-bundle
make validate-phase4-delivery-index
make validate-phase4-artifact-store
make validate-phase4-external-mirror-plan
```

`make validate-phase4-video-package` 会构造一次只包含抖音、视频号、B站的平台 run，并验收 asset-agent、视频平台产物和最终视频生产包。

`make validate-phase4-assets` 会进一步验收素材生成/导入层：

- `assets/asset_generation_tasks.json` 中每个素材任务都保持 `planned`。
- `assets/media_asset_manifest.json` 中每个素材都保持 `planned`，版权状态为 `pending_human_review`。
- B-roll 目标素材路径仍只作为导入槽位记录，不会被 runner 自动生成文件。
- storyboard 关键帧会在 Phase 4 step 4 由 storyboard preview adapter 落地，并继续保持人工审核边界。
- `final/video_production_package.json` 会把各平台的素材任务和媒体资产清单嵌入到对应平台包中。

`make validate-phase4-asset-materialization` 会验收本地素材实物化层：

- `asset-materialization-agent` 必须在 `visual_assets` 和各平台视频脚本之后运行。
- 三个视频平台各自生成 `assets/{platform}/materials/material_manifest.json`、`README.md` 和 B-roll reference PNG。
- reference PNG 会被写入 edit timeline 的 B-roll placeholder、offline media report 和 project bundle ZIP 的 `materials/` 目录。
- `final/materialization_manifest.json` 汇总三端素材实物化状态，并标记未搜索外部素材、未下载、未上传、未发布。
- reference PNG 只是本地审核参考，最终发布素材仍必须替换为自制或授权媒体。

`make validate-phase4-licensed-media-ingest` 会验收授权素材接收与审核交接层：

- `licensed-media-ingest-agent` 必须在各平台 asset materialization 之后运行。
- 三个视频平台各自生成 `assets/{platform}/licensed_media/ingest_manifest.json`、`README.md` 和 `review_handoff.md`。
- edit timeline 和 offline media report 必须带上 ingest manifest、review handoff、intake status 和人工审核状态。
- project bundle ZIP 必须把交接文件放入 `licensed_media/` 目录。
- `final/licensed_media_ingest_manifest.json` 汇总三端授权素材接收状态，并保持未搜索、未下载、未购买、未上传、未发布、未打开剪辑软件。

`make validate-phase4-licensed-media-proxy` 会验收人工登记素材到剪辑替换建议和代理素材拷贝层：

- `licensed-media-proxy-agent` 必须在各平台 licensed media ingest 之后运行。
- 默认没有 `human_media_registry.json` 时，只生成 proxy manifest、replacement suggestions 和 proxy README，不复制任何素材文件。
- 当 `human_media_registry.json` 提供本地已审核素材时，proxy 层会复制到 `assets/{platform}/licensed_media/proxy/{asset_id}_proxy.*`。
- edit timeline、offline media report 和 project bundle ZIP 必须携带 proxy manifest、replacement suggestions、proxy README 和 ready proxy media path。
- `final/licensed_media_proxy_manifest.json` 汇总三端 proxy 状态，并保持未搜索、未下载、未购买、未上传、未发布、未打开剪辑软件。

`make validate-phase4-editor-replacement-instructions` 会验收剪辑替换导入模板和人工确认门：

- `editor-replacement-instructions-agent` 必须在各平台 export project 和 licensed media proxy 之后运行。
- 三个视频平台各自生成 `instruction_manifest.json`、`replacement_commands.json`、`editor_import_template.fcpxml`、`human_confirmation_checklist.md` 和 README。
- `replacement_commands.json` 必须全部保持 dry-run、`execution_status=not_executed`、`human_confirmation_required=true`。
- FCPXML 导入模板必须是 well-formed XML，但仅用于人工确认后的候选素材导入。
- project bundle ZIP 必须包含 `replacement_instructions/` 五件套。
- `final/editor_replacement_instruction_manifest.json` 汇总三端指令状态，并保持未执行替换、未打开剪辑软件、未修改工程文件。

`make validate-phase4-editor-replacement-execution` 会验收剪辑替换执行预检和显式人工批准门：

- `editor-replacement-execution-agent` 必须在各平台 editor replacement instructions 之后运行。
- 三个视频平台各自生成 `execution_manifest.json`、`execution_plan.json`、`execution_audit_log.json`、`human_execution_approval_request.md` 和 README。
- 默认无 `human_execution_approval.json` 时，所有命令必须保持 blocked pending explicit human approval。
- 有效批准文件只能把对应命令标记为 `ready_for_manual_execution`，仍不得打开剪辑软件、修改工程文件或执行替换。
- project bundle ZIP 必须包含 `replacement_execution/` 五件套。
- `final/editor_replacement_execution_manifest.json` 汇总三端执行预检状态，并保持未执行替换、未打开剪辑软件、未修改工程文件。

`make validate-phase4-editor-project-mutation-sandbox` 会验收工程副本改写沙盒：

- `editor-project-mutation-sandbox-agent` 必须在各平台 editor replacement execution 之后运行。
- 三个视频平台各自生成 `mutation_manifest.json`、`patched_project.fcpxml`、`mutation_diff.json`、`rollback_manifest.json`、`mutation_audit_log.json`、`human_final_review_checklist.md` 和 README。
- 默认无 `human_mutation_approval.json` 时，patched project 必须是原始 FCPXML 的未改写沙盒副本。
- 有效批准文件只能让 ready execution item 写入 `mutation_sandbox/patched_project.fcpxml`，仍不得修改原始 `project.fcpxml`、打开剪辑软件或执行替换。
- project bundle ZIP 必须包含 `mutation_sandbox/` 七件套。
- `final/editor_project_mutation_manifest.json` 汇总三端 mutation sandbox 状态，并保持原始工程未改写、替换未执行、剪辑软件未打开。

`make validate-phase4-editor-software-import-executor` 会验收剪辑软件隔离导入执行器：

- `editor-software-import-executor-agent` 必须在各平台 editor project mutation sandbox 之后运行。
- 三个视频平台各自生成 `import_executor_manifest.json`、`import_plan.json`、`import_commands.json`、`software_import_audit_log.json`、`rollback_safety_report.json`、`isolated_execution_request.md` 和 README。
- 默认无 `human_software_import_approval.json` 时，所有 import item 必须 blocked。
- 有效批准文件只能把匹配 patched project sha256 的 item 标记为 `ready_for_isolated_manual_import`。
- project bundle ZIP 必须包含 `software_import_executor/` 七件套。
- `final/editor_software_import_manifest.json` 汇总三端 software import executor 状态，并保持不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。

`make validate-phase4-editor-software-real-runner-sandbox` 会验收真实剪辑软件启动前的外部沙盒运行门：

- `editor-software-real-runner-sandbox-agent` 必须在各平台 editor software import executor 之后运行。
- 三个视频平台各自生成 `runner_sandbox_manifest.json`、`runner_environment_snapshot.json`、`runner_launch_plan.json`、`runner_command_preview.json`、`runner_audit_log.json`、`runner_evidence_manifest.json`、`human_real_run_approval_request.md` 和 README。
- 默认无 `human_real_run_approval.json` 时，所有 runner item 必须 blocked。
- 有效批准文件只能把匹配 patched project sha256 的 item 标记为 `ready_for_manual_external_sandbox_launch`。
- project bundle ZIP 必须包含 `software_real_runner_sandbox/` 八件套。
- `final/editor_software_real_runner_manifest.json` 汇总三端 real runner sandbox 状态，并保持不 spawn 进程、不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。

`make validate-phase4-editor-software-run-evidence` 会验收人工外部真实运行后的证据接收和 closeout 层：

- `editor-software-run-evidence-agent` 必须在各平台 editor software real runner sandbox 之后运行。
- 三个视频平台各自生成 `real_run_evidence_manifest.json`、`evidence_validation_report.json`、`rollback_decision_report.json`、`post_launch_evidence_checklist.md` 和 README。
- 默认无 `human_real_run_result.json` 时，所有 evidence item 必须 blocked pending human result。
- 有效人工结果文件只能把匹配 runner manifest sha256 且 runner 已 ready 的 item 标记为 `human_real_run_evidence_ingested`。
- project bundle ZIP 必须包含 `software_run_evidence/` closeout 文件。
- `final/editor_software_run_evidence_manifest.json` 汇总三端 evidence ingest 状态，并保持不 spawn 进程、不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。

`make validate-phase4-artifact-store` 会验收本地可下载 artifact store：

- `artifact-store-agent` 必须在 `delivery_index` 之后运行，并在 `fact_check` 之前完成。
- 三个视频平台的 project bundle ZIP 必须复制到 `artifact_store/downloads/`。
- 复制件字节和 SHA-256 必须匹配 `final/delivery_index.json`。
- `artifact_store/download_index.md`、`artifact_store/checksums.sha256` 和 README 必须存在。
- content package 必须引用 artifact store manifest、README、download index 和 checksum 文件。
- artifact store 必须保持不外部同步、不登录、不上传、不发布、不执行平台动作。

`make validate-phase4-external-mirror-plan` 会验收外部分发镜像计划层：

- `external-mirror-plan-agent` 必须在 `artifact_store` 之后运行，并在 `fact_check` 之前完成。
- 三个 artifact store ZIP 必须各自生成一个 blocked mirror plan item。
- mirror plan 必须重新校验本地 ZIP 的 SHA-256。
- `sync_command_preview.md` 只能作为注释化命令预览，不得执行同步。
- `human_distribution_approval_request.md` 必须明确人工批准前不得同步、上传或发布。
- content package 必须引用 external mirror plan、sync preview、approval request 和 README。
- external mirror plan 必须保持不外部同步、不登录、不上传、不发布、不访问网络、不执行平台动作。

`make validate-phase4-cover-adapter` 会验收封面图本地适配器：

- 三个视频平台各自产生一张本地 PNG 封面。
- 封面元数据标记 `generated_pending_review` 和 `pending_human_review`。
- 生成的封面会嵌入最终视频生产包的 `generated_assets`。

`make validate-phase4-storyboard-adapter` 会验收 storyboard 关键帧适配器：

- 三个视频平台各自生成 preview sheet、preview metadata 和逐帧 keyframe PNG。
- 关键帧元数据标记 `generated_pending_review` 和 `pending_human_review`。
- 生成的 storyboard 资产会嵌入最终视频生产包的 `generated_assets`。

`make validate-phase4-subtitle-timing` 会验收字幕时间轴校正：

- 三个视频平台各自生成 `timed_subtitles.json` 和 `timed_subtitles.srt`。
- 字幕总时长必须与 storyboard 总时长一致。
- 每条字幕必须绑定 `shot_id`，且不能跨越镜头边界。
- 结果会嵌入最终视频生产包，并标记为本地确定性校正、未调用 TTS。

`make validate-phase4-voiceover-tts` 会验收默认配音草轨生成：

- 三个视频平台各自生成 `assets/{platform}/voiceover/voiceover.wav`。
- 每条配音 segment 必须来自 `timed_subtitles.json`。
- WAV 总时长必须与 timed subtitles 总时长一致。
- 结果会嵌入最终视频生产包，并标记 provider、audio generation mode、rights status 和人工审核边界；默认仍为本地 draft。

`make validate-phase4-voiceover-tts-siliconflow` 会验收 SiliconFlow 真实 TTS provider smoke：

- 通过 workflow 环境变量 `SILICONFLOW_API_KEY` 或 `CONTENT_AGENT_OS_TTS_API_KEY` 读取密钥，优先使用 `SILICONFLOW_API_KEY`，不读取桌面文件，也不打印 secret。
- 如果 `SILICONFLOW_API_KEY` 已设置但失效，smoke 会降回本地草轨并失败；刷新或 unset 该变量后再重跑。
- 使用 `fnlp/MOSS-TTSD-v0.5` 和 `fnlp/MOSS-TTSD-v0.5:alex` 生成 1.5 秒短配音 WAV。
- manifest 必须标记 `provider_external=true`、`provider=siliconflow-audio-speech-api` 和 `audio_generation_mode=siliconflow_speech_api`。
- WAV 必须是 mono、16-bit、16000 Hz，并与 smoke timeline 对齐。

`make validate-phase4-edit-project` 会验收剪辑时间线：

- 三个视频平台各自生成 `edit_timeline.json`、`edit_manifest.json` 和 `draft_cut.edl`。
- `final/edit_project_manifest.json` 会汇总三端剪辑时间线、EDL 和校验状态。
- timeline 的视频 clip 数必须匹配 storyboard。
- voiceover audio clip 和 subtitle clip 必须与 timed subtitles 总时长一致。
- 结果会嵌入最终视频生产包，并标记为本地 draft、未打开剪辑软件。

`make validate-phase4-export-project` 会验收剪辑工程导出：

- 三个视频平台各自生成 `project.fcpxml`、`import_readme.md`、`offline_media_report.json` 和 `export_manifest.json`。
- FCPXML 必须是 well-formed XML，并引用已存在的 storyboard keyframes 和 voiceover WAV。
- B-roll 槽位必须保留在 offline media report 中，等待授权素材导入。
- 结果会嵌入最终视频生产包，并标记为本地 draft、未打开剪辑软件。

`make validate-phase4-project-bundle` 会验收本地 ZIP 工程交付包：

- 三个视频平台各自生成 `project_bundle.zip`、`project_bundle_manifest.json`、`file_manifest.json` 和 bundle README。
- ZIP 必须包含 FCPXML、导入说明、offline media report、export manifest、edit timeline、EDL、字幕 sidecar、配音 WAV 和分镜关键帧。
- ZIP 会把 B-roll reference PNG 放入 `materials/` 目录，作为剪辑替换参考。
- ZIP 会把 editor replacement instruction 五件套放入 `replacement_instructions/` 目录，作为人工确认后的剪辑导入参考。
- ZIP 会把 editor replacement execution 五件套放入 `replacement_execution/` 目录，作为显式人工批准前的执行预检参考。
- ZIP 会把 editor project mutation sandbox 七件套放入 `mutation_sandbox/` 目录，作为最终人工审核前的可回滚 FCPXML 副本。
- ZIP 会把 editor software import executor 七件套放入 `software_import_executor/` 目录，作为隔离导入前的 dry-run/manual command preview。
- ZIP 会把 editor software real runner sandbox 八件套放入 `software_real_runner_sandbox/` 目录，作为外部人工启动真实剪辑软件前的安全门和证据清单。
- `final/project_bundle_manifest.json` 必须汇总三端 bundle 状态。
- 结果会嵌入最终视频生产包，并标记为本地 draft、未打开剪辑软件。

`make validate-phase4-delivery-index` 会验收本地交付索引：

- `delivery-index-agent` 必须在所有 project bundle 之后运行。
- `final/delivery_index.json` 必须记录每个 ZIP 的路径、大小和 SHA-256。
- `final/delivery_readme.md` 必须包含可读的交付表格。
- 不执行外部存储同步、上传或发布。

## Demo 运行

```bash
make run-demo TOPIC="AI内容创作自动化系统"
```

该命令保留 V0 行为，只在 `outputs/demo-runs/` 下生成一次 demo request。

## 校验一次运行

```bash
make validate-run
```

默认校验最新的 `outputs/runs/run_*`。也可以指定：

```bash
make validate-run RUN_ID="run_20260518T000000Z"
```

当前 `validate-run` 会确认：

- workflow 状态是 `DONE`
- 每个执行 step 都有 task log
- 每个 task 声明的产物都存在
- `artifact_manifest.json` 中声明的产物都存在
- `research`、`topic_angles` 和 `master_outline` 必须是 `agent-local`
- `visual_assets` 必须是 `agent-local`，并生成 `asset_plan.json` 与 `cover_prompts.md`
- `visual_assets` 必须生成素材任务包、媒体资产清单和导入指南
- `douyin_cover_image`、`shipinhao_cover_image`、`bilibili_cover_image` 必须通过 `cover-image-agent` 运行
- `douyin_storyboard_preview`、`shipinhao_storyboard_preview`、`bilibili_storyboard_preview` 必须通过 `storyboard-preview-agent` 运行
- `douyin_asset_materialization`、`shipinhao_asset_materialization`、`bilibili_asset_materialization` 必须通过 `asset-materialization-agent` 运行
- `douyin_licensed_media_ingest`、`shipinhao_licensed_media_ingest`、`bilibili_licensed_media_ingest` 必须通过 `licensed-media-ingest-agent` 运行
- `douyin_licensed_media_proxy`、`shipinhao_licensed_media_proxy`、`bilibili_licensed_media_proxy` 必须通过 `licensed-media-proxy-agent` 运行
- `douyin_editor_replacement_instructions`、`shipinhao_editor_replacement_instructions`、`bilibili_editor_replacement_instructions` 必须通过 `editor-replacement-instructions-agent` 运行
- `douyin_editor_replacement_execution`、`shipinhao_editor_replacement_execution`、`bilibili_editor_replacement_execution` 必须通过 `editor-replacement-execution-agent` 运行
- `douyin_editor_project_mutation_sandbox`、`shipinhao_editor_project_mutation_sandbox`、`bilibili_editor_project_mutation_sandbox` 必须通过 `editor-project-mutation-sandbox-agent` 运行
- `douyin_editor_software_import_executor`、`shipinhao_editor_software_import_executor`、`bilibili_editor_software_import_executor` 必须通过 `editor-software-import-executor-agent` 运行
- `douyin_subtitle_timing`、`shipinhao_subtitle_timing`、`bilibili_subtitle_timing` 必须通过 `subtitle-timing-agent` 运行
- `douyin_voiceover_tts`、`shipinhao_voiceover_tts`、`bilibili_voiceover_tts` 必须通过 `voiceover-tts-agent` 运行
- `douyin_edit_project`、`shipinhao_edit_project`、`bilibili_edit_project` 必须通过 `edit-project-agent` 运行
- `angle_pack.json` 必须声明由 `topic-agent` 从 `research_report.md` 生成
- 当平台包含 `wechat` 时，`wechat_article` 必须是 `agent-local`
- `wechat/article.md` 必须包含来源状态、人工审核标记，并满足基础长度要求
- `wechat/title_options.json` 必须由 `wechat-article-agent` 生成，包含至少3个标题和来源说明
- 当平台包含 `xiaohongshu` 时，`xiaohongshu_note` 必须是 `agent-local`
- `xiaohongshu/note.json` 必须符合基础平台约束：标题不超过20字、5-8个标签、包含 `#AI生成内容`、要求人工审核
- 当平台包含 `douyin` 时，`douyin_video` 必须是 `agent-local`
- `douyin/script.md` 必须包含前三秒 hook、分镜清单、人工审核标记和不自动剪辑/上传/发布声明
- `douyin/storyboard.json` 必须包含可执行分镜，第一段必须是 3 秒 hook
- `douyin/subtitles.srt` 字幕块数量必须匹配分镜数量
- `douyin/timed_subtitles.json` 和 `douyin/timed_subtitles.srt` 必须存在，且时间轴必须贴合分镜
- `assets/douyin/voiceover/voiceover.wav` 和 `assets/douyin/voiceover/voiceover_manifest.json` 必须存在，且音频时长必须匹配 timed subtitles
- `assets/douyin/edit/edit_timeline.json`、`assets/douyin/edit/edit_manifest.json` 和 `assets/douyin/edit/draft_cut.edl` 必须存在，且 timeline 时长必须匹配配音与字幕
- `final/edit_project_manifest.json` 必须存在，且必须引用各视频平台的 edit timeline、manifest 和 EDL
- `assets/douyin/edit/project.fcpxml`、`assets/douyin/edit/import_readme.md`、`assets/douyin/edit/offline_media_report.json` 和 `assets/douyin/edit/export_manifest.json` 必须存在
- `final/export_project_manifest.json` 必须存在，且必须引用各视频平台的 FCPXML 工程交付物
- 当平台包含 `shipinhao` 时，`shipinhao_video` 必须是 `agent-local`
- 视频号内容仍写入 `shipinhao/` 目录，`shipinhao-video-agent` 是默认 workflow 中的 canonical agent
- 当平台包含 `bilibili` 时，`bilibili_video` 必须是 `agent-local`
- `bilibili/script.md` 必须包含标题备选、观众预期、章节、完整脚本、人工审核标记和不自动投稿声明
- `bilibili/chapters.json` 必须包含至少5个章节，并从 `00:00` 开始
- `bilibili/description.md` 必须包含时间轴、标签、人工审核标记和不自动上传/发布声明
- final package 必须要求人工审核
- Phase 4 run 必须生成 `final/video_production_package.json`
- Phase 4 run 的视频生产包必须引用素材任务包和媒体资产清单
- Phase 4 run 的视频生产包必须引用封面生成结果
- Phase 4 run 的视频生产包必须引用 storyboard preview 生成结果
- Phase 4 run 的视频生产包必须引用 materialization manifest 和 B-roll reference PNG
- Phase 4 run 的视频生产包必须引用 licensed media ingest manifest 和 review handoff
- Phase 4 run 的视频生产包必须引用 licensed media proxy manifest 和 replacement suggestions
- Phase 4 run 的视频生产包必须引用 editor replacement instruction manifest 和 dry-run commands
- Phase 4 run 的视频生产包必须引用 editor replacement execution manifest 和 execution plan
- Phase 4 run 的视频生产包必须引用 editor project mutation manifest 和 patched FCPXML 沙盒副本
- Phase 4 run 的视频生产包必须引用 editor software import manifest 和 isolated import dry-run commands
- Phase 4 run 的视频生产包必须引用 editor software real runner manifest 和 launch command preview
- Phase 4 run 的视频生产包必须引用 timed subtitle 结果
- Phase 4 run 的视频生产包必须引用 voiceover TTS 结果
- Phase 4 run 的视频生产包必须引用 edit project 结果
- Phase 4 run 的视频生产包必须引用 export project 结果
- Phase 4 run 的视频生产包必须引用 project bundle 结果
- Phase 4 run 的 content package 必须引用 materialization manifest、licensed media ingest manifest、licensed media proxy manifest、editor replacement instruction manifest、editor replacement execution manifest、editor project mutation manifest、editor software import manifest、editor software real runner manifest、delivery index 和 delivery README

后续真实运行形态会继续加入：

- `make resume RUN_ID="..."`
- `make logs RUN_ID="..."`
- `make repair RUN_ID="..."`

## 人工审批

以下操作不得默认自动执行：

- 登录平台
- 刷新 cookie
- 发布内容
- 上传视频
- 批量互动
- 删除产物
- 使用版权不明的素材
