from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "README.md",
    "docs/RUNBOOK.md",
    "docs/IMPLEMENTATION_ROADMAP.md",
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yml",
    ".env.example",
    "schemas/task_spec.schema.json",
    "schemas/agent_manifest.schema.json",
    "schemas/plugin_manifest.schema.json",
    "schemas/workflow.schema.json",
    "schemas/workflow_run.schema.json",
    "schemas/supervision_snapshot.schema.json",
    "schemas/artifact_manifest.schema.json",
    "schemas/artifact_store_manifest.schema.json",
    "schemas/asset_generation_tasks.schema.json",
    "schemas/cover_image_metadata.schema.json",
    "schemas/delivery_index.schema.json",
    "schemas/edit_project_bundle_manifest.schema.json",
    "schemas/edit_project_manifest.schema.json",
    "schemas/edit_timeline.schema.json",
    "schemas/export_project_bundle_manifest.schema.json",
    "schemas/export_project_manifest.schema.json",
    "schemas/project_bundle_bundle_manifest.schema.json",
    "schemas/project_bundle_manifest.schema.json",
    "schemas/storyboard_preview_metadata.schema.json",
    "schemas/timed_subtitles.schema.json",
    "schemas/voiceover_tts_manifest.schema.json",
    "schemas/content_package.schema.json",
    "schemas/media_asset_manifest.schema.json",
    "schemas/materialization_bundle_manifest.schema.json",
    "schemas/materialized_assets_manifest.schema.json",
    "schemas/licensed_media_ingest_bundle_manifest.schema.json",
    "schemas/licensed_media_ingest_manifest.schema.json",
    "schemas/licensed_media_proxy_bundle_manifest.schema.json",
    "schemas/licensed_media_proxy_manifest.schema.json",
    "schemas/licensed_media_replacement_suggestions.schema.json",
    "schemas/editor_replacement_commands.schema.json",
    "schemas/editor_replacement_instruction_bundle_manifest.schema.json",
    "schemas/editor_replacement_instruction_manifest.schema.json",
    "schemas/editor_replacement_execution_bundle_manifest.schema.json",
    "schemas/editor_replacement_execution_manifest.schema.json",
    "schemas/editor_replacement_execution_plan.schema.json",
    "schemas/editor_project_mutation_bundle_manifest.schema.json",
    "schemas/editor_project_mutation_diff.schema.json",
    "schemas/editor_project_mutation_sandbox_manifest.schema.json",
    "schemas/editor_software_import_bundle_manifest.schema.json",
    "schemas/editor_software_import_commands.schema.json",
    "schemas/editor_software_import_executor_manifest.schema.json",
    "schemas/editor_software_import_plan.schema.json",
    "schemas/editor_software_real_runner_bundle_manifest.schema.json",
    "schemas/editor_software_real_runner_command_preview.schema.json",
    "schemas/editor_software_real_runner_launch_plan.schema.json",
    "schemas/editor_software_real_runner_sandbox_manifest.schema.json",
    "schemas/editor_software_run_evidence_bundle_manifest.schema.json",
    "schemas/editor_software_run_evidence_manifest.schema.json",
    "schemas/editor_software_run_evidence_rollback_decision_report.schema.json",
    "schemas/editor_software_run_evidence_validation_report.schema.json",
    "schemas/external_mirror_plan.schema.json",
    "schemas/video_production_package.schema.json",
    "schemas/platform_outputs/wechat_article.schema.json",
    "schemas/platform_outputs/xiaohongshu_note.schema.json",
    "schemas/platform_outputs/video_package.schema.json",
    "registry/agent_registry.yaml",
    "registry/plugin_registry.yaml",
    "workflows/one_topic_multi_platform.yaml",
    "examples/input_brief.json",
    "examples/task_spec.xiaohongshu.json",
    "plugins/wechat/manifest.yaml",
    "plugins/xiaohongshu/manifest.yaml",
    "plugins/douyin/manifest.yaml",
    "plugins/shipinhao/manifest.yaml",
    "plugins/bilibili/manifest.yaml",
    "agents/common/licensed-media-proxy-agent/manifest.yaml",
    "agents/common/editor-replacement-instructions-agent/manifest.yaml",
    "agents/common/editor-replacement-execution-agent/manifest.yaml",
    "agents/common/editor-project-mutation-sandbox-agent/manifest.yaml",
    "agents/common/editor-software-import-executor-agent/manifest.yaml",
    "agents/common/editor-software-real-runner-sandbox-agent/manifest.yaml",
    "agents/common/editor-software-run-evidence-agent/manifest.yaml",
    "agents/common/artifact-store-agent/manifest.yaml",
    "agents/common/external-mirror-plan-agent/manifest.yaml",
    "scripts/validate_run.py",
    "scripts/validate_stale_detector.py",
    "scripts/validate_retry_policy.py",
    "scripts/validate_repair_agent.py",
    "scripts/validate_human_approval_gate.py",
    "scripts/validate_phase3.py",
    "scripts/validate_phase4_asset_pipeline.py",
    "scripts/validate_phase4_asset_materialization.py",
    "scripts/validate_phase4_licensed_media_ingest.py",
    "scripts/validate_phase4_licensed_media_proxy.py",
    "scripts/validate_phase4_editor_replacement_instructions.py",
    "scripts/validate_phase4_editor_replacement_execution.py",
    "scripts/validate_phase4_editor_project_mutation_sandbox.py",
    "scripts/validate_phase4_editor_software_import_executor.py",
    "scripts/validate_phase4_editor_software_real_runner_sandbox.py",
    "scripts/validate_phase4_editor_software_run_evidence.py",
    "scripts/validate_phase4_artifact_store.py",
    "scripts/validate_phase4_external_mirror_plan.py",
    "scripts/validate_phase4_cover_adapter.py",
    "scripts/validate_phase4_delivery_index.py",
    "scripts/validate_phase4_edit_project.py",
    "scripts/validate_phase4_export_project.py",
    "scripts/validate_phase4_project_bundle.py",
    "scripts/validate_phase4_storyboard_adapter.py",
    "scripts/validate_phase4_subtitle_timing.py",
    "scripts/validate_phase4_voiceover_tts.py",
    "scripts/validate_phase4_voiceover_tts_siliconflow.py",
    "scripts/validate_phase4_video_package.py",
    "scripts/validate_phase5_console.py",
    "scripts/validate_phase5_migration.py",
    "scripts/validate_phase5_setup_check.py",
    "scripts/validate_phase5_profiles.py",
    "scripts/validate_phase5_job_queue.py",
    "scripts/validate_phase5_queue_ops.py",
    "scripts/validate_phase5_queue_retention.py",
    "scripts/validate_phase5_local_runtime.py",
    "scripts/validate_phase5_desktop_app.py",
    "scripts/build_macos_app.sh",
    "desktop/macos/ContentAgentLauncher/main.swift",
    "desktop/macos/ContentAgentLauncher/Resources/content_creator_logo.svg",
    "docs/PHASE5_MIGRATION.md",
    "src/content_agent_os/__init__.py",
    "src/content_agent_os/agents.py",
    "src/content_agent_os/approval_gate.py",
    "src/content_agent_os/artifact_store.py",
    "src/content_agent_os/asset_materialization.py",
    "src/content_agent_os/cli.py",
    "src/content_agent_os/console_server.py",
    "src/content_agent_os/delivery_index.py",
    "src/content_agent_os/edit_project.py",
    "src/content_agent_os/editor_replacement_instructions.py",
    "src/content_agent_os/editor_replacement_execution.py",
    "src/content_agent_os/editor_project_mutation_sandbox.py",
    "src/content_agent_os/editor_software_import_executor.py",
    "src/content_agent_os/editor_software_real_runner_sandbox.py",
    "src/content_agent_os/editor_software_run_evidence.py",
    "src/content_agent_os/export_project.py",
    "src/content_agent_os/external_mirror_plan.py",
    "src/content_agent_os/licensed_media_ingest.py",
    "src/content_agent_os/licensed_media_proxy.py",
    "src/content_agent_os/job_queue.py",
    "src/content_agent_os/project_bundle.py",
    "src/content_agent_os/retry_policy.py",
    "src/content_agent_os/runner.py",
    "src/content_agent_os/scheduler.py",
    "src/content_agent_os/stale_detector.py",
    "src/content_agent_os/supervision.py",
    "src/content_agent_os/subtitle_timing.py",
    "src/content_agent_os/voiceover_tts.py",
    "src/content_agent_os/worker.py",
    "src/content_agent_os/workflow.py",
]

REQUIRED_AGENTS = [
    "global-orchestrator",
    "research-agent",
    "topic-agent",
    "outline-agent",
    "style-agent",
    "asset-agent",
    "asset-materialization-agent",
    "licensed-media-ingest-agent",
    "licensed-media-proxy-agent",
    "editor-replacement-instructions-agent",
    "editor-replacement-execution-agent",
    "editor-project-mutation-sandbox-agent",
    "editor-software-import-executor-agent",
    "editor-software-real-runner-sandbox-agent",
    "editor-software-run-evidence-agent",
    "artifact-store-agent",
    "external-mirror-plan-agent",
    "cover-image-agent",
    "storyboard-preview-agent",
    "subtitle-timing-agent",
    "voiceover-tts-agent",
    "edit-project-agent",
    "export-project-agent",
    "project-bundle-agent",
    "delivery-index-agent",
    "fact-check-agent",
    "compliance-agent",
    "validator-agent",
    "repair-agent",
    "wechat-article-agent",
    "xiaohongshu-note-agent",
    "douyin-video-agent",
    "shipinhao-video-agent",
    "bilibili-video-agent",
]

REQUIRED_PLUGINS = ["wechat", "xiaohongshu", "douyin", "shipinhao", "bilibili"]


def fail(message: str) -> None:
    print(f"V0 validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        fail(f"missing required file: {path}")
    return file_path.read_text(encoding="utf-8")


def check_registry_paths(registry_text: str, registry_name: str) -> None:
    for raw_line in registry_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("path: "):
            continue
        manifest_path = line.removeprefix("path: ").strip()
        if not (ROOT / manifest_path).exists():
            fail(f"{registry_name} references missing manifest: {manifest_path}")


def check_manifest_keys(base: str, required_keys: list[str]) -> None:
    manifest_paths = sorted((ROOT / base).rglob("manifest.yaml"))
    if not manifest_paths:
        fail(f"no manifests found under {base}")
    for manifest_path in manifest_paths:
        text = manifest_path.read_text(encoding="utf-8")
        for key in required_keys:
            if f"{key}:" not in text:
                fail(f"{manifest_path.relative_to(ROOT)} missing key: {key}")


def main() -> int:
    for path in REQUIRED_PATHS:
        if not (ROOT / path).exists():
            fail(f"missing required path: {path}")

    for schema_path in sorted((ROOT / "schemas").rglob("*.json")):
        try:
            json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON schema {schema_path.relative_to(ROOT)}: {exc}")

    agent_registry = read_text("registry/agent_registry.yaml")
    check_registry_paths(agent_registry, "agent registry")
    for agent_id in REQUIRED_AGENTS:
        if agent_id not in agent_registry:
            fail(f"agent registry missing {agent_id}")

    plugin_registry = read_text("registry/plugin_registry.yaml")
    check_registry_paths(plugin_registry, "plugin registry")
    for plugin_id in REQUIRED_PLUGINS:
        if plugin_id not in plugin_registry:
            fail(f"plugin registry missing {plugin_id}")

    check_manifest_keys("agents", ["id", "name", "layer", "role", "inputs", "outputs"])
    check_manifest_keys("plugins", ["id", "name", "platform", "agents", "inputs", "outputs"])

    workflow = read_text("workflows/one_topic_multi_platform.yaml")
    for platform in REQUIRED_PLUGINS:
        if platform not in workflow:
            fail(f"workflow missing platform step: {platform}")

    makefile = read_text("Makefile")
    for target in ["run:", "run-demo:", "resume:", "monitor:", "logs:", "approve-repair:", "console:", "worker:", "worker-once:", "scheduler:", "scheduler-once:", "build-macos-app:", "validate-run:", "validate-stale-detector:", "validate-retry-policy:", "validate-repair-agent:", "validate-human-approval-gate:", "validate-phase3:", "validate-phase4-video-package:", "validate-phase4-assets:", "validate-phase4-asset-materialization:", "validate-phase4-licensed-media-ingest:", "validate-phase4-licensed-media-proxy:", "validate-phase4-editor-replacement-instructions:", "validate-phase4-editor-replacement-execution:", "validate-phase4-editor-project-mutation-sandbox:", "validate-phase4-editor-software-import-executor:", "validate-phase4-editor-software-real-runner-sandbox:", "validate-phase4-editor-software-run-evidence:", "validate-phase4-artifact-store:", "validate-phase4-external-mirror-plan:", "validate-phase4-cover-adapter:", "validate-phase4-storyboard-adapter:", "validate-phase4-subtitle-timing:", "validate-phase4-voiceover-tts:", "validate-phase4-voiceover-tts-siliconflow:", "validate-phase4-edit-project:", "validate-phase4-export-project:", "validate-phase4-project-bundle:", "validate-phase4-delivery-index:", "validate-phase5-console:", "validate-phase5-migration:", "validate-phase5-setup:", "validate-phase5-profiles:", "validate-phase5-job-queue:", "validate-phase5-queue-ops:", "validate-phase5-queue-retention:", "validate-phase5-local-runtime:", "validate-phase5-desktop-app:"]:
        if target not in makefile:
            fail(f"Makefile missing target: {target}")

    readme = read_text("README.md")
    for phrase in ["AzureDust-Elf", "当前版本", "主要功能"]:
        if phrase not in readme:
            fail(f"README missing phrase: {phrase}")

    print("V0 validation passed.")
    print(f"Checked {len(REQUIRED_PATHS)} required paths, {len(REQUIRED_AGENTS)} agents, {len(REQUIRED_PLUGINS)} plugins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
