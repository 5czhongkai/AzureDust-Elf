.PHONY: validate run run-demo resume monitor logs approve-repair console worker worker-once scheduler scheduler-once build-macos-app validate-run validate-stale-detector validate-retry-policy validate-repair-agent validate-human-approval-gate validate-phase3 validate-phase4-video-package validate-phase4-assets validate-phase4-asset-materialization validate-phase4-licensed-media-ingest validate-phase4-licensed-media-proxy validate-phase4-editor-replacement-instructions validate-phase4-editor-replacement-execution validate-phase4-editor-project-mutation-sandbox validate-phase4-editor-software-import-executor validate-phase4-editor-software-real-runner-sandbox validate-phase4-editor-software-run-evidence validate-phase4-cover-adapter validate-phase4-storyboard-adapter validate-phase4-subtitle-timing validate-phase4-voiceover-tts validate-phase4-voiceover-tts-siliconflow validate-phase4-edit-project validate-phase4-export-project validate-phase4-project-bundle validate-phase4-delivery-index validate-phase4-artifact-store validate-phase4-external-mirror-plan validate-phase5-console validate-phase5-migration validate-phase5-setup validate-phase5-profiles validate-phase5-job-queue validate-phase5-queue-ops validate-phase5-queue-retention validate-phase5-local-runtime validate-phase5-desktop-app clean

TOPIC ?= AI内容创作自动化系统
PLATFORMS ?= wechat,xiaohongshu,douyin,shipinhao,bilibili
RUN_ID ?=
REPAIR_ID ?=
APPROVED_BY ?= human
APPROVAL_NOTE ?= Human approval recorded.
OUTPUT_ROOT ?= outputs/runs
BACKUP_ROOT ?= backups
CONSOLE_HOST ?= 127.0.0.1
CONSOLE_PORT ?= 8080
SCHEDULE_INTERVAL_SECONDS ?= 86400
SCHEDULER_DRY_RUN ?= 1
WORKER_POLL_INTERVAL_SECONDS ?= 5

validate:
	python3 scripts/validate_v0.py

run:
	PYTHONPATH=src python3 -m content_agent_os.cli --mode run --workflow workflows/one_topic_multi_platform.yaml --topic "$(TOPIC)" --platforms "$(PLATFORMS)" --output-root "$(OUTPUT_ROOT)"

run-demo:
	PYTHONPATH=src python3 -m content_agent_os.cli --mode demo --workflow workflows/one_topic_multi_platform.yaml --topic "$(TOPIC)" --platforms "$(PLATFORMS)" --output-root "$(OUTPUT_ROOT)"

resume:
	PYTHONPATH=src python3 -m content_agent_os.cli --mode resume --workflow workflows/one_topic_multi_platform.yaml --run-id "$(RUN_ID)" --platforms "$(PLATFORMS)" --output-root "$(OUTPUT_ROOT)"

monitor:
	PYTHONPATH=src python3 -m content_agent_os.cli --mode monitor --run-id "$(RUN_ID)" --output-root "$(OUTPUT_ROOT)"

logs: monitor

approve-repair:
	PYTHONPATH=src python3 -m content_agent_os.cli --mode approve-repair --run-id "$(RUN_ID)" --repair-id "$(REPAIR_ID)" --approved-by "$(APPROVED_BY)" --approval-note "$(APPROVAL_NOTE)" --output-root "$(OUTPUT_ROOT)"

console:
	PYTHONPATH=src python3 -m content_agent_os.console_server --host "$(CONSOLE_HOST)" --port "$(CONSOLE_PORT)" --workflow workflows/one_topic_multi_platform.yaml --output-root "$(OUTPUT_ROOT)" --backup-root "$(BACKUP_ROOT)" --platforms "$(PLATFORMS)"

worker:
	PYTHONPATH=src python3 -m content_agent_os.worker --output-root "$(OUTPUT_ROOT)" --poll-interval-seconds "$(WORKER_POLL_INTERVAL_SECONDS)"

worker-once:
	PYTHONPATH=src python3 -m content_agent_os.worker --once --output-root "$(OUTPUT_ROOT)" --poll-interval-seconds "$(WORKER_POLL_INTERVAL_SECONDS)"

scheduler:
	CONTENT_AGENT_SCHEDULER_DRY_RUN="$(SCHEDULER_DRY_RUN)" PYTHONPATH=src python3 -m content_agent_os.scheduler --workflow workflows/one_topic_multi_platform.yaml --topic "$(TOPIC)" --platforms "$(PLATFORMS)" --output-root "$(OUTPUT_ROOT)" --interval-seconds "$(SCHEDULE_INTERVAL_SECONDS)"

scheduler-once:
	CONTENT_AGENT_SCHEDULER_DRY_RUN="$(SCHEDULER_DRY_RUN)" PYTHONPATH=src python3 -m content_agent_os.scheduler --once --workflow workflows/one_topic_multi_platform.yaml --topic "$(TOPIC)" --platforms "$(PLATFORMS)" --output-root "$(OUTPUT_ROOT)" --interval-seconds "$(SCHEDULE_INTERVAL_SECONDS)"

build-macos-app:
	bash scripts/build_macos_app.sh

validate-run:
	python3 scripts/validate_run.py "$(RUN_ID)"

validate-stale-detector:
	PYTHONPATH=src python3 scripts/validate_stale_detector.py

validate-retry-policy:
	PYTHONPATH=src python3 scripts/validate_retry_policy.py

validate-repair-agent:
	PYTHONPATH=src python3 scripts/validate_repair_agent.py

validate-human-approval-gate:
	PYTHONPATH=src python3 scripts/validate_human_approval_gate.py

validate-phase3:
	PYTHONPATH=src python3 scripts/validate_phase3.py

validate-phase4-video-package:
	PYTHONPATH=src python3 scripts/validate_phase4_video_package.py

validate-phase4-assets:
	PYTHONPATH=src python3 scripts/validate_phase4_asset_pipeline.py

validate-phase4-asset-materialization:
	PYTHONPATH=src python3 scripts/validate_phase4_asset_materialization.py

validate-phase4-licensed-media-ingest:
	PYTHONPATH=src python3 scripts/validate_phase4_licensed_media_ingest.py

validate-phase4-licensed-media-proxy:
	PYTHONPATH=src python3 scripts/validate_phase4_licensed_media_proxy.py

validate-phase4-editor-replacement-instructions:
	PYTHONPATH=src python3 scripts/validate_phase4_editor_replacement_instructions.py

validate-phase4-editor-replacement-execution:
	PYTHONPATH=src python3 scripts/validate_phase4_editor_replacement_execution.py

validate-phase4-editor-project-mutation-sandbox:
	PYTHONPATH=src python3 scripts/validate_phase4_editor_project_mutation_sandbox.py

validate-phase4-editor-software-import-executor:
	PYTHONPATH=src python3 scripts/validate_phase4_editor_software_import_executor.py

validate-phase4-editor-software-real-runner-sandbox:
	PYTHONPATH=src python3 scripts/validate_phase4_editor_software_real_runner_sandbox.py

validate-phase4-editor-software-run-evidence:
	PYTHONPATH=src python3 scripts/validate_phase4_editor_software_run_evidence.py

validate-phase4-cover-adapter:
	PYTHONPATH=src python3 scripts/validate_phase4_cover_adapter.py

validate-phase4-storyboard-adapter:
	PYTHONPATH=src python3 scripts/validate_phase4_storyboard_adapter.py

validate-phase4-subtitle-timing:
	PYTHONPATH=src python3 scripts/validate_phase4_subtitle_timing.py

validate-phase4-voiceover-tts:
	PYTHONPATH=src python3 scripts/validate_phase4_voiceover_tts.py

validate-phase4-voiceover-tts-siliconflow:
	PYTHONPATH=src python3 scripts/validate_phase4_voiceover_tts_siliconflow.py

validate-phase4-edit-project:
	PYTHONPATH=src python3 scripts/validate_phase4_edit_project.py

validate-phase4-export-project:
	PYTHONPATH=src python3 scripts/validate_phase4_export_project.py

validate-phase4-project-bundle:
	PYTHONPATH=src python3 scripts/validate_phase4_project_bundle.py

validate-phase4-delivery-index:
	PYTHONPATH=src python3 scripts/validate_phase4_delivery_index.py

validate-phase4-artifact-store:
	PYTHONPATH=src python3 scripts/validate_phase4_artifact_store.py

validate-phase4-external-mirror-plan:
	PYTHONPATH=src python3 scripts/validate_phase4_external_mirror_plan.py

validate-phase5-console:
	PYTHONPATH=src python3 scripts/validate_phase5_console.py

validate-phase5-migration:
	PYTHONPATH=src python3 scripts/validate_phase5_migration.py

validate-phase5-setup:
	PYTHONPATH=src python3 scripts/validate_phase5_setup_check.py

validate-phase5-profiles:
	PYTHONPATH=src python3 scripts/validate_phase5_profiles.py

validate-phase5-job-queue:
	PYTHONPATH=src python3 scripts/validate_phase5_job_queue.py

validate-phase5-queue-ops:
	PYTHONPATH=src python3 scripts/validate_phase5_queue_ops.py

validate-phase5-queue-retention:
	PYTHONPATH=src python3 scripts/validate_phase5_queue_retention.py

validate-phase5-local-runtime:
	PYTHONPATH=src python3 scripts/validate_phase5_local_runtime.py

validate-phase5-desktop-app:
	PYTHONPATH=src python3 scripts/validate_phase5_desktop_app.py

clean:
	rm -rf outputs/demo-runs
