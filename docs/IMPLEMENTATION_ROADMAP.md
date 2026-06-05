# 实施路线图

## Phase 0: 当前骨架

目标：让项目具备清晰的结构和边界。

交付：

- docs
- schemas
- registry
- agents
- plugins
- workflow example
- validation script

## Phase 1: 最小内容生成闭环

目标：输入一个主题，生成五个平台的草稿内容包。

当前进度：

- Step 1 已实现真实 workflow runner：读取 workflow、按依赖执行、生成任务日志、写入 run 目录、输出内容包清单。
- Step 2 已新增 `run_agent(task_spec)` 接口，并接入 `research-agent` 和 `outline-agent` 的本地 agent handler。
- Step 3 已接入 `topic-agent` 的本地 agent handler，`angle_pack.json` 现在从 `research_report.md` 派生。
- Step 4 已接入第一个平台产出 agent：`xiaohongshu-note-agent`，小红书笔记与封面提示词现在从 `angle_pack.json` 和 `master_outline.md` 派生。
- Step 5 已接入 `wechat-article-agent`，微信公众号文章与标题备选现在从 `angle_pack.json`、`master_outline.md`、`research_report.md` 和 `sources.json` 派生。
- Step 6 已接入 `douyin-video-agent`，抖音短视频脚本、分镜和字幕现在从 `angle_pack.json` 和 `master_outline.md` 派生。
- Step 7 已接入 `bilibili-video-agent`，B站长视频脚本、章节和简介现在从 `angle_pack.json`、`master_outline.md` 和 `research_report.md` 派生。
- Step 8 已统一视频号 agent 命名为 `shipinhao-video-agent`，并将其保留在默认 workflow 与默认平台列表中。
- 五个平台的首版平台产出 agent 均已迁出模板模式。
- 当前 agent 执行还没有接入 LLM。

任务：

- 接入 OpenAI API 或本地模型适配层
- 实现 `research-agent`
- 实现 `outline-agent`
- 实现五个平台 agent 的初稿生成
- 将输出写入 `outputs/{run_id}/`
- validator 检查 schema 与基本质量

## Phase 2: 工作流持久化

目标：任何一步失败后可恢复、可重跑。

当前进度：

- 已接入 SQLite 状态库，默认写入 `outputs/runs/_state/workflow_state.sqlite`。
- 已实现 `workflow_run` 表与 `task_ledger` 表。
- 已实现 `make resume RUN_ID="..."`，可以在补齐缺失输入后继续同一 run。
- 已实现基础 failure classification，会把失败写入 `workflow_run.json` 和 SQLite ledger。

任务：

- 引入 SQLite/Postgres
- 实现 workflow_run 表
- 实现 task ledger
- 实现 `resume`
- 实现失败分类

## Phase 3: 监督和修复

目标：总控可以发现卡住的任务并触发修复。

当前进度：

- Step 1 已实现运行监督与故障可视化：每次 run/resume 自动生成 `monitor/supervision_snapshot.json`、`monitor/supervision_report.md` 和 `monitor/failure_dashboard.html`。
- 已新增 `make monitor` 与 `make logs`，可单独刷新指定 run 的监督报告。
- 监督快照会汇总 workflow 进度、task attempts、产物完整性、失败分类和下一步恢复建议。
- Step 2 已实现 stale task detector：`RUNNING` task 超过阈值会被标记为 `stale` 可恢复故障；`resume` 会把遗留的 `RUNNING` attempt 识别为 `stale` 或 `interrupted` 后再重跑。
- Step 3 已实现 retry policy：`resume` 会对 stale/interrupted 的 recoverable `ENV_ERROR` 按预算自动补跑，并记录 retry events。
- Step 4 已实现 repair-agent + repair log：不可自动重试的失败会生成 repair plan 与 repair_log，进入人工修复建议链路。
- Step 5 已实现 human approval gate：`manual_required=true` 的 repair plan 会暂停在 `NEEDS_HUMAN`，必须先 `make approve-repair` 再 `make resume`。
- Step 6 已实现端到端故障演练与 Phase 3 Completion Audit：`make validate-phase3` 会串联 stale、retry、repair、approval 和 resume replay。

任务：
- Phase 3 核心闭环已完成，后续只保留告警通道、Web UI 和更细审批体验作为增强项。

## Phase 4: 视觉与视频生产

目标：从文字内容包升级到视频生产包。

当前进度：

- Step 1 已接入 `asset-agent` 的真实 `run_agent(task_spec)` handler，生成 `asset_plan.json` 和 `cover_prompts.md`。
- 默认 workflow 已新增 `visual_assets` step，并让抖音、视频号、B站视频 agent 依赖统一素材规划。
- 抖音、视频号、B站现在会输出脚本、分镜、字幕、shot list、B-roll list 和封面提示。
- 最终输出已新增 `final/video_production_package.json`，作为剪辑前的视频生产包清单。
- 已新增 `make validate-phase4-video-package` 作为 Phase 4 视频生产包验收入口。
- Step 2 已新增素材生成/导入层：`assets/asset_generation_tasks.json`、`assets/media_asset_manifest.json` 和 `assets/asset_ingest_guide.md`。
- 视频生产包现在会嵌入每个平台的 asset tasks 和 media assets，并明确素材生成、下载、导入、版权确认都未自动执行。
- 已新增 `make validate-phase4-assets` 作为素材任务包验收入口。
- Asset materialization 已接入本地 B-roll reference 层：`asset-materialization-agent` 会为三个视频平台生成 `assets/{platform}/materials/material_manifest.json`、`README.md` 和 `{asset_id}_reference.png`。
- 视频生产包现在会嵌入 materialized asset 摘要，并生成 `final/materialization_manifest.json` 汇总三端 reference PNG、审核状态和安全边界。
- 已新增 `make validate-phase4-asset-materialization` 作为本地素材实物化验收入口。
- Licensed media ingest 已接入授权素材接收与审核交接层：`licensed-media-ingest-agent` 会为三个视频平台生成 `assets/{platform}/licensed_media/ingest_manifest.json`、`README.md` 和 `review_handoff.md`。
- 视频生产包现在会嵌入 licensed media ingest 摘要，并生成 `final/licensed_media_ingest_manifest.json` 汇总三端人工素材交接状态和安全边界。
- 已新增 `make validate-phase4-licensed-media-ingest` 作为授权素材接收与 review handoff 验收入口。
- Licensed media proxy 已接入人工登记素材到剪辑替换建议和代理素材拷贝层：`licensed-media-proxy-agent` 会为三个视频平台生成 `proxy_manifest.json`、`replacement_suggestions.json` 和 `proxy/README.md`。
- 当 `human_media_registry.json` 提供本地已审核素材时，proxy 层会复制到 `assets/{platform}/licensed_media/proxy/{asset_id}_proxy.*`，并把 `proxy_media_path` 写入 edit timeline、offline media report 和 project bundle。
- 视频生产包现在会嵌入 licensed media proxy 摘要，并生成 `final/licensed_media_proxy_manifest.json` 汇总三端替换建议状态和安全边界。
- 已新增 `make validate-phase4-licensed-media-proxy` 作为人工登记素材到 replacement suggestions / proxy copy 的验收入口。
- Editor replacement instructions 已接入剪辑导入模板和人工确认门：`editor-replacement-instructions-agent` 会为三个视频平台生成 `instruction_manifest.json`、`replacement_commands.json`、`editor_import_template.fcpxml`、`human_confirmation_checklist.md` 和 README。
- 视频生产包现在会嵌入 editor replacement instructions 摘要，并生成 `final/editor_replacement_instruction_manifest.json` 汇总三端 dry-run 指令、FCPXML 导入模板和人工确认状态。
- 已新增 `make validate-phase4-editor-replacement-instructions` 作为 replacement suggestions 到剪辑导入模板 / dry-run commands / 人工确认门的验收入口。
- Editor replacement execution 已接入显式人工批准前的执行预检层：`editor-replacement-execution-agent` 会为三个视频平台生成 `execution_manifest.json`、`execution_plan.json`、`execution_audit_log.json`、`human_execution_approval_request.md` 和 README。
- 默认无 `human_execution_approval.json` 时，execution 层全部阻断；即使存在有效批准，也只标记 `ready_for_manual_execution`，仍不打开剪辑软件、不修改工程文件、不执行替换。
- 视频生产包现在会嵌入 editor replacement execution 摘要，并生成 `final/editor_replacement_execution_manifest.json` 汇总三端执行预检状态。
- 已新增 `make validate-phase4-editor-replacement-execution` 作为显式人工批准门、执行预检计划和审计日志的验收入口。
- Editor project mutation sandbox 已接入可回滚工程副本改写层：`editor-project-mutation-sandbox-agent` 会为三个视频平台生成 `mutation_manifest.json`、`patched_project.fcpxml`、`mutation_diff.json`、`rollback_manifest.json`、`mutation_audit_log.json`、`human_final_review_checklist.md` 和 README。
- 默认无 `human_mutation_approval.json` 时，mutation sandbox 只生成未改写的 FCPXML 沙盒副本；有效批准也只改写 `assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml`，仍不修改原始工程、不打开剪辑软件、不执行替换。
- 视频生产包现在会嵌入 editor project mutation sandbox 摘要，并生成 `final/editor_project_mutation_manifest.json` 汇总三端沙盒副本改写状态。
- 已新增 `make validate-phase4-editor-project-mutation-sandbox` 作为显式人工批准后的 patched FCPXML 沙盒副本、diff、rollback 和最终人工审核清单验收入口。
- Editor software import executor 已接入真实剪辑软件隔离导入计划层：`editor-software-import-executor-agent` 会为三个视频平台生成 `import_executor_manifest.json`、`import_plan.json`、`import_commands.json`、`software_import_audit_log.json`、`rollback_safety_report.json`、`isolated_execution_request.md` 和 README。
- 默认无 `human_software_import_approval.json` 时，software import executor 会阻断所有 import item；有效批准也只标记 `ready_for_isolated_manual_import`，仍不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。
- 视频生产包现在会嵌入 editor software import executor 摘要，并生成 `final/editor_software_import_manifest.json` 汇总三端隔离导入计划状态。
- 已新增 `make validate-phase4-editor-software-import-executor` 作为 sandbox patched project 到真实剪辑软件隔离导入计划、dry-run/manual command preview、审计日志和 rollback safety report 的验收入口。
- Editor software real runner sandbox 已接入真实剪辑软件启动前的外部沙盒运行门：`editor-software-real-runner-sandbox-agent` 会为三个视频平台生成 `runner_sandbox_manifest.json`、`runner_environment_snapshot.json`、`runner_launch_plan.json`、`runner_command_preview.json`、`runner_audit_log.json`、`runner_evidence_manifest.json`、`human_real_run_approval_request.md` 和 README。
- 默认无 `human_real_run_approval.json` 时，real runner sandbox 会阻断所有 runner item；有效批准也只标记 `ready_for_manual_external_sandbox_launch`，仍不 spawn 进程、不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。
- 视频生产包现在会嵌入 editor software real runner sandbox 摘要，并生成 `final/editor_software_real_runner_manifest.json` 汇总三端真实软件启动前状态。
- 已新增 `make validate-phase4-editor-software-real-runner-sandbox` 作为外部真实剪辑软件启动前环境快照、launch plan、command preview、evidence manifest 和人工 real-run approval gate 的验收入口。
- Editor software run evidence 已接入人工外部真实运行后的证据接收 closeout 层：`editor-software-run-evidence-agent` 会为三个视频平台生成 `real_run_evidence_manifest.json`、`evidence_validation_report.json`、`rollback_decision_report.json`、`post_launch_evidence_checklist.md` 和 README。
- 默认无 `human_real_run_result.json` 时，run evidence 层会阻断所有 evidence item；有效人工结果只 ingest 与 runner manifest sha256 匹配且 runner 已 ready 的人工证据，仍不 spawn 进程、不打开剪辑软件、不执行导入、不修改工程、不上传、不发布。
- 视频生产包现在会嵌入 editor software run evidence 摘要，project bundle 会包含 `software_run_evidence/` closeout 文件，并生成 `final/editor_software_run_evidence_manifest.json` 汇总三端证据接收状态。
- 已新增 `make validate-phase4-editor-software-run-evidence` 作为人工真实运行结果、evidence ingest、post-launch checklist 和 rollback decision report 的验收入口。
- Step 3 已接入本地封面图适配器：`cover-image-agent` 会为三个视频平台生成 PNG 封面草图和封面元数据。
- 视频生产包现在还会嵌入 `generated_assets`，并标记封面图生成已本地完成但仍待人工审核。
- 已新增 `make validate-phase4-cover-adapter` 作为封面适配器验收入口。
- Step 4 已接入本地 storyboard preview 适配器：`storyboard-preview-agent` 会为三个视频平台生成分镜关键帧 PNG、preview metadata 和预览图。
- 视频生产包现在还会嵌入 storyboard keyframe 资产，并标记分镜关键帧生成已本地完成但仍待人工审核。
- 已新增 `make validate-phase4-storyboard-adapter` 作为 storyboard 适配器验收入口。
- Step 5 已接入本地字幕时间轴校正：`subtitle-timing-agent` 会为三个视频平台生成 `timed_subtitles.json` 和 `timed_subtitles.srt`。
- 视频生产包现在会嵌入 timed subtitle 摘要，并标记字幕校正已本地确定性完成、未调用 TTS。
- 已新增 `make validate-phase4-subtitle-timing` 作为字幕时间轴校正验收入口。
- Step 6 已接入本地配音草轨：`voiceover-tts-agent` 会根据 `timed_subtitles.json` 生成 `assets/{platform}/voiceover/voiceover.wav` 和 `voiceover_manifest.json`。
- 视频生产包现在会嵌入 voiceover TTS 摘要，并按 manifest 聚合标记默认本地草轨、OpenAI Speech、SiliconFlow Speech 或混合 provider 边界。
- 已新增 `make validate-phase4-voiceover-tts` 作为配音草轨验收入口。
- Step 7 已接入本地剪辑时间线：`edit-project-agent` 会根据 storyboard keyframes、timed subtitles、voiceover 和 B-roll 槽位生成 `edit_timeline.json`、`edit_manifest.json` 和 `draft_cut.edl`。
- 视频生产包现在会嵌入 edit project 摘要，并生成 `final/edit_project_manifest.json` 汇总三端剪辑交付物，标记剪辑时间线已本地生成、未打开剪辑软件。
- 已新增 `make validate-phase4-edit-project` 作为剪辑时间线验收入口。
- Step 8 已接入本地剪辑工程导出：`export-project-agent` 会根据 edit timeline 生成 `project.fcpxml`、导入说明、offline media report 和 export manifest。
- 视频生产包现在会嵌入 export project 摘要，并生成 `final/export_project_manifest.json` 汇总三端剪辑工程交付物，标记工程导出已本地生成、未打开剪辑软件。
- 已新增 `make validate-phase4-export-project` 作为剪辑工程导出验收入口。
- Step 9 已接入本地工程交付包：`project-bundle-agent` 会把 FCPXML、导入说明、offline media report、export manifest、时间线、EDL、字幕、配音和分镜关键帧打成 ZIP。
- 视频生产包现在会嵌入 project bundle 摘要，并生成 `final/project_bundle_manifest.json` 汇总三端 ZIP 交付物，标记工程交付包已本地生成、未打开剪辑软件。
- 已新增 `make validate-phase4-project-bundle` 作为 ZIP 工程交付包验收入口。
- Step 10 已接入本地交付索引：`delivery-index-agent` 会汇总三个 project bundle，生成 `final/delivery_index.json`、`final/delivery_readme.md`、文件大小和 SHA-256。
- content package 现在会引用 delivery index 和 delivery README，标记交付索引已本地生成、未同步外部存储。
- 已新增 `make validate-phase4-delivery-index` 作为本地交付索引验收入口。
- Step 11 已接入本地 artifact store 可下载交付目录：`artifact-store-agent` 会读取 delivery index，把三个视频平台 project bundle ZIP 复制到 `artifact_store/downloads/`，并生成 `artifact_store_manifest.json`、下载索引、校验和、README 和 delivery index 副本。
- content package 现在会引用 artifact store manifest、README、download index 和 checksum 文件，标记 artifact store 已本地生成、未同步外部存储、未上传、未发布。
- 已新增 `make validate-phase4-artifact-store` 作为本地可下载交付目录、复制件校验和与分发边界的验收入口。
- Step 12 已接入外部分发镜像计划层：`external-mirror-plan-agent` 会读取 artifact store，重新校验本地 ZIP，生成 `external_mirror_plan.json`、`sync_command_preview.md`、`human_distribution_approval_request.md` 和 README。
- content package 现在会引用 external mirror plan、sync command preview、approval request 和 README，标记外部分发仍只是计划层，未同步外部存储、未登录、未上传、未发布。
- 已新增 `make validate-phase4-external-mirror-plan` 作为外部分发计划、命令预览和人工批准请求的验收入口。

任务：

- 将 asset generation tasks 接入真实图片生成或素材库检索
- 已将 voiceover draft adapter 扩展为 hybrid TTS provider，默认保持本地草轨，显式环境变量可调用 OpenAI Speech 或 SiliconFlow Speech，并新增 SiliconFlow smoke 验证入口
- 将 external mirror plan 接入人工批准后的可选对象存储或素材库镜像执行器；默认仍不得自动上传、登录或发布

## Phase 5: 一键部署与控制台

目标：不同设备可一键运行。

当前进度：

- Step 1 已接入本地控制台服务：`make console` 会启动 `content_agent_os.console_server`，提供 Web UI、`/healthz`、run/job/env/backups API；新 run 要求完整五平台集合，避免破坏 Phase 4 交付契约。
- Docker Compose 已从占位服务升级为真实 `console` service，使用同一控制台入口，挂载 `outputs/` 和 `backups/`。
- `.env.example` 已补齐控制台、输出目录、备份目录和 hybrid TTS 变量名；控制台只展示 secret 是否存在，不展示 secret 值。
- 已新增本地备份包生成：`POST /api/backups` 会把 `outputs/runs/` 打成 `backups/content_agent_os_backup_*.zip`，不包含环境变量。
- 已新增 `make validate-phase5-console` 作为控制台、Compose 入口、secret 隐藏和备份策略验收入口。
- Step 2 已接入 restore dry-run 与显式确认恢复：`POST /api/restore-dry-run` 会读取指定备份 ZIP 的清单，校验恢复路径仅限 `outputs/runs/`，统计将恢复文件和覆盖数量；`POST /api/restore` 必须提供精确 `RESTORE <backup-name>` 确认短语，才会恢复安全路径内的文件并写入 restore log。
- Step 3 已接入多设备迁移说明：`docs/PHASE5_MIGRATION.md` 明确源设备收口、迁移文件、secret 边界、新设备启动、restore 安全流程和 Docker 可选验证；`make validate-phase5-migration` 作为迁移文档验收入口。
- Step 4 已接入本地配置向导：`GET /api/setup-check` 和 `/admin` 后端控制台的配置检查区块会检查 Python、workflow、五平台集合、`.env.example`、`outputs/`、`backups/`、resume 状态库、最新备份和 secret presence；`make validate-phase5-setup` 会验证 API、HTML 和 secret redaction。
- Step 5 已接入 worker/scheduler profiles：`docker-compose.yml` 提供 `worker` 与 `scheduler` profiles，`make worker` 执行一次 workflow，`make scheduler-once` 写入一次 dry-run tick，`make scheduler` 按间隔循环；scheduler 默认 dry-run，`make validate-phase5-profiles` 会验证 profile 接线和 dry-run 不创建 run。
- Step 6 已接入 durable job queue / worker handoff：console run/resume 请求写入 `outputs/runs/_state/console_jobs.sqlite`，`make worker` 消费 queued jobs，`make worker-once` 单次消费后退出；scheduler execute mode 只 enqueue run job，不直接执行 workflow；`make validate-phase5-job-queue` 会验证 console enqueue、worker consume、scheduler handoff 和 runtime restart 后 job 可见。
- Step 7 已接入 queue observability / operations panel：`/admin` 后端控制台的队列任务面板显示 queue health、job DB path、worker id、时间戳、error 和操作按钮；`GET /api/queue-health`、status-filtered jobs、job audit、Cancel、Retry、Mark Failed 已接入；`make validate-phase5-queue-ops` 会验证操作边界和 audit log。
- Step 8 已接入 queue history retention / cleanup：`.env.example` 提供 `CONTENT_AGENT_JOB_RETENTION_DAYS` 和 `CONTENT_AGENT_AUDIT_RETENTION_DAYS`，`/admin` 后端控制台的队列维护面板提供 Cleanup Dry-Run 和 Confirm Cleanup；cleanup 必须输入精确 `CLEANUP JOBS`，且只删除 `DONE` / `FAILED` / `CANCELED` 历史，不删除 `QUEUED` / `RUNNING`；`make validate-phase5-queue-retention` 会验证 retention 边界。
- Step 9 已接入 local runtime 增强：`GET /api/local-runtime` 和 `/admin` 后端控制台的本机状态面板展示本机 `make console`、`make worker-once`、`make worker`、`make scheduler-once`、`make scheduler` readiness，并明确 Docker 是 optional，不是本机运行前置条件；`make validate-phase5-local-runtime` 会验证 API、HTML、secret redaction 和 Docker optional 边界。

任务：

- Docker Compose 完整服务（Step 1 已接入 console service；Step 5 已接入 worker/scheduler profiles；Step 6 已接入 durable queue handoff；Step 7 已接入 queue ops；Step 8 已接入 queue retention；Step 9 明确 Docker optional；后续只需在 Docker 可用环境实机验证）
- Web UI（`/` 已接入中文创作工作台；`/admin` 已接入本机状态、配置检查、队列维护、备份恢复和环境变量安全状态）
- 环境变量管理（`/admin` 已接入安全状态展示；Step 4 已接入本地配置向导；Step 9 已接入 local runtime readiness；后续可加更细的本地 secret 注入引导）
- 数据备份/恢复（Step 1 已接入本地备份；Step 2 已接入 restore dry-run 与显式确认恢复；后续可增强批量迁移向导）
- 多设备迁移说明（Step 3 已接入；Step 4 已接入 Setup Check 迁移预检；后续可加交互式迁移向导）
