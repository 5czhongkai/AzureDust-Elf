from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
EDITOR_REPLACEMENT_EXECUTION_BOUNDARY = "blocked_pending_explicit_human_approval"
EDITOR_PROJECT_MUTATION_BOUNDARY = "blocked_pending_explicit_human_mutation_approval"
EDITOR_SOFTWARE_IMPORT_BOUNDARY = "blocked_pending_explicit_human_software_import_approval"
EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY = "blocked_pending_explicit_human_real_run_approval"
EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY = "blocked_pending_human_real_run_result"
EXPECTED_VOICEOVER_TTS_BOUNDARIES = {
    "performed_locally_draft_no_external_provider",
    "performed_external_openai_speech_pending_human_review",
    "performed_external_siliconflow_speech_pending_human_review",
    "performed_mixed_voiceover_tts_pending_human_review",
}
REQUIRED_VIDEO_DELIVERABLES = {
    "voiceover_script",
    "storyboard",
    "subtitle_script",
    "timed_subtitles",
    "timed_subtitles_srt",
    "voiceover_audio",
    "voiceover_manifest",
    "edit_timeline",
    "edit_manifest",
    "draft_cut_edl",
    "project_fcpxml",
    "project_import_readme",
    "offline_media_report",
    "export_manifest",
    "project_bundle_zip",
    "project_bundle_manifest",
    "project_bundle_file_manifest",
    "project_bundle_readme",
    "material_manifest",
    "material_readme",
    "licensed_media_ingest_manifest",
    "licensed_media_ingest_readme",
    "licensed_media_review_handoff",
    "licensed_media_proxy_manifest",
    "licensed_media_replacement_suggestions",
    "licensed_media_proxy_readme",
    "editor_replacement_instruction_manifest",
    "editor_replacement_commands",
    "editor_import_template_fcpxml",
    "editor_human_confirmation_checklist",
    "editor_replacement_readme",
    "editor_replacement_execution_manifest",
    "editor_replacement_execution_plan",
    "editor_replacement_execution_audit_log",
    "editor_replacement_approval_request",
    "editor_replacement_execution_readme",
    "editor_project_mutation_manifest",
    "editor_project_patched_fcpxml",
    "editor_project_mutation_diff",
    "editor_project_rollback_manifest",
    "editor_project_mutation_audit_log",
    "editor_project_final_review_checklist",
    "editor_project_mutation_readme",
    "editor_software_import_manifest",
    "editor_software_import_plan",
    "editor_software_import_commands",
    "editor_software_import_audit_log",
    "editor_software_import_rollback_safety_report",
    "editor_software_import_execution_request",
    "editor_software_import_readme",
    "editor_software_real_runner_manifest",
    "editor_software_real_runner_environment_snapshot",
    "editor_software_real_runner_launch_plan",
    "editor_software_real_runner_command_preview",
    "editor_software_real_runner_audit_log",
    "editor_software_real_runner_evidence_manifest",
    "editor_software_real_runner_approval_request",
    "editor_software_real_runner_readme",
    "editor_software_run_evidence_manifest",
    "editor_software_run_evidence_validation_report",
    "editor_software_run_evidence_rollback_decision_report",
    "editor_software_run_evidence_checklist",
    "editor_software_run_evidence_readme",
    "shot_list",
    "broll_list",
    "cover_prompt",
    "storyboard_preview",
    "storyboard_preview_metadata",
}


def fail(message: str) -> None:
    print(f"Phase 4 validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> dict:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


def depends_on_transitively(steps: dict[str, object], step_id: str, required_dependency_id: str) -> bool:
    stack = list(getattr(steps[step_id], "depends_on", []))
    seen: set[str] = set()
    while stack:
        candidate = stack.pop()
        if candidate == required_dependency_id:
            return True
        if candidate in seen or candidate not in steps:
            continue
        seen.add(candidate)
        stack.extend(getattr(steps[candidate], "depends_on", []))
    return False


def validate_workflow_contract() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    expect("visual_assets" in steps, "workflow must include visual_assets step")
    expect(steps["visual_assets"].agent == "asset-agent", "visual_assets must use asset-agent")
    for output_path in [
        "asset_plan.json",
        "cover_prompts.md",
        "assets/asset_generation_tasks.json",
        "assets/media_asset_manifest.json",
        "assets/asset_ingest_guide.md",
    ]:
        expect(output_path in steps["visual_assets"].outputs, f"visual_assets missing output: {output_path}")
    for step_id in ["douyin_video", "shipinhao_video", "bilibili_video"]:
        expect("visual_assets" in steps[step_id].depends_on, f"{step_id} must depend on visual_assets")
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_storyboard_preview"
        expect(step_id in steps, f"workflow must include {step_id}")
        expect(steps[step_id].agent == "storyboard-preview-agent", f"{step_id} must use storyboard-preview-agent")
        expect(f"{platform}_video" in steps[step_id].depends_on, f"{step_id} must depend on {platform}_video")
        expect(step_id in steps["fact_check"].depends_on, f"fact_check must depend on {step_id}")
        material_step_id = f"{platform}_asset_materialization"
        expect(material_step_id in steps, f"workflow must include {material_step_id}")
        expect(steps[material_step_id].agent == "asset-materialization-agent", f"{material_step_id} must use asset-materialization-agent")
        expect("visual_assets" in steps[material_step_id].depends_on, f"{material_step_id} must depend on visual_assets")
        expect(f"{platform}_video" in steps[material_step_id].depends_on, f"{material_step_id} must depend on {platform}_video")
        expect(material_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {material_step_id}")
        licensed_ingest_step_id = f"{platform}_licensed_media_ingest"
        expect(licensed_ingest_step_id in steps, f"workflow must include {licensed_ingest_step_id}")
        expect(
            steps[licensed_ingest_step_id].agent == "licensed-media-ingest-agent",
            f"{licensed_ingest_step_id} must use licensed-media-ingest-agent",
        )
        expect(
            material_step_id in steps[licensed_ingest_step_id].depends_on,
            f"{licensed_ingest_step_id} must depend on asset materialization",
        )
        expect(licensed_ingest_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {licensed_ingest_step_id}")
        licensed_proxy_step_id = f"{platform}_licensed_media_proxy"
        expect(licensed_proxy_step_id in steps, f"workflow must include {licensed_proxy_step_id}")
        expect(
            steps[licensed_proxy_step_id].agent == "licensed-media-proxy-agent",
            f"{licensed_proxy_step_id} must use licensed-media-proxy-agent",
        )
        expect(steps[licensed_proxy_step_id].platform == platform, f"{licensed_proxy_step_id} platform mismatch")
        expect(
            licensed_ingest_step_id in steps[licensed_proxy_step_id].depends_on,
            f"{licensed_proxy_step_id} must depend on licensed media ingest",
        )
        for output_path in [
            f"assets/{platform}/licensed_media/proxy_manifest.json",
            f"assets/{platform}/licensed_media/replacement_suggestions.json",
            f"assets/{platform}/licensed_media/proxy/README.md",
        ]:
            expect(output_path in steps[licensed_proxy_step_id].outputs, f"{licensed_proxy_step_id} missing output: {output_path}")
        expect(licensed_proxy_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {licensed_proxy_step_id}")
        subtitle_step_id = f"{platform}_subtitle_timing"
        expect(subtitle_step_id in steps, f"workflow must include {subtitle_step_id}")
        expect(steps[subtitle_step_id].agent == "subtitle-timing-agent", f"{subtitle_step_id} must use subtitle-timing-agent")
        expect(f"{platform}_video" in steps[subtitle_step_id].depends_on, f"{subtitle_step_id} must depend on {platform}_video")
        expect(f"{platform}_storyboard_preview" in steps[subtitle_step_id].depends_on, f"{subtitle_step_id} must depend on storyboard preview")
        expect(subtitle_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {subtitle_step_id}")
        voiceover_step_id = f"{platform}_voiceover_tts"
        expect(voiceover_step_id in steps, f"workflow must include {voiceover_step_id}")
        expect(steps[voiceover_step_id].agent == "voiceover-tts-agent", f"{voiceover_step_id} must use voiceover-tts-agent")
        expect(f"{platform}_subtitle_timing" in steps[voiceover_step_id].depends_on, f"{voiceover_step_id} must depend on subtitle timing")
        expect(voiceover_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {voiceover_step_id}")
        edit_step_id = f"{platform}_edit_project"
        expect(edit_step_id in steps, f"workflow must include {edit_step_id}")
        expect(steps[edit_step_id].agent == "edit-project-agent", f"{edit_step_id} must use edit-project-agent")
        expect(f"{platform}_voiceover_tts" in steps[edit_step_id].depends_on, f"{edit_step_id} must depend on voiceover TTS")
        expect(f"{platform}_storyboard_preview" in steps[edit_step_id].depends_on, f"{edit_step_id} must depend on storyboard preview")
        expect(f"{platform}_asset_materialization" in steps[edit_step_id].depends_on, f"{edit_step_id} must depend on asset materialization")
        expect(
            f"{platform}_licensed_media_ingest" in steps[edit_step_id].depends_on,
            f"{edit_step_id} must depend on licensed media ingest",
        )
        expect(
            f"{platform}_licensed_media_proxy" in steps[edit_step_id].depends_on,
            f"{edit_step_id} must depend on licensed media proxy",
        )
        expect(edit_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {edit_step_id}")
        export_step_id = f"{platform}_export_project"
        expect(export_step_id in steps, f"workflow must include {export_step_id}")
        expect(steps[export_step_id].agent == "export-project-agent", f"{export_step_id} must use export-project-agent")
        expect(f"{platform}_edit_project" in steps[export_step_id].depends_on, f"{export_step_id} must depend on edit project")
        expect(export_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {export_step_id}")
        instruction_step_id = f"{platform}_editor_replacement_instructions"
        expect(instruction_step_id in steps, f"workflow must include {instruction_step_id}")
        expect(
            steps[instruction_step_id].agent == "editor-replacement-instructions-agent",
            f"{instruction_step_id} must use editor-replacement-instructions-agent",
        )
        expect(f"{platform}_export_project" in steps[instruction_step_id].depends_on, f"{instruction_step_id} must depend on export project")
        expect(
            f"{platform}_licensed_media_proxy" in steps[instruction_step_id].depends_on,
            f"{instruction_step_id} must depend on licensed media proxy",
        )
        for output_path in [
            f"assets/{platform}/edit/replacement_instructions/instruction_manifest.json",
            f"assets/{platform}/edit/replacement_instructions/replacement_commands.json",
            f"assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml",
            f"assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md",
            f"assets/{platform}/edit/replacement_instructions/README.md",
        ]:
            expect(output_path in steps[instruction_step_id].outputs, f"{instruction_step_id} missing output: {output_path}")
        expect(instruction_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {instruction_step_id}")
        execution_step_id = f"{platform}_editor_replacement_execution"
        expect(execution_step_id in steps, f"workflow must include {execution_step_id}")
        expect(
            steps[execution_step_id].agent == "editor-replacement-execution-agent",
            f"{execution_step_id} must use editor-replacement-execution-agent",
        )
        expect(f"{platform}_editor_replacement_instructions" in steps[execution_step_id].depends_on, f"{execution_step_id} must depend on editor replacement instructions")
        for output_path in [
            f"assets/{platform}/edit/replacement_execution/execution_manifest.json",
            f"assets/{platform}/edit/replacement_execution/execution_plan.json",
            f"assets/{platform}/edit/replacement_execution/execution_audit_log.json",
            f"assets/{platform}/edit/replacement_execution/human_execution_approval_request.md",
            f"assets/{platform}/edit/replacement_execution/README.md",
        ]:
            expect(output_path in steps[execution_step_id].outputs, f"{execution_step_id} missing output: {output_path}")
        expect(execution_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {execution_step_id}")
        mutation_step_id = f"{platform}_editor_project_mutation_sandbox"
        expect(mutation_step_id in steps, f"workflow must include {mutation_step_id}")
        expect(
            steps[mutation_step_id].agent == "editor-project-mutation-sandbox-agent",
            f"{mutation_step_id} must use editor-project-mutation-sandbox-agent",
        )
        expect(
            execution_step_id in steps[mutation_step_id].depends_on,
            f"{mutation_step_id} must depend on editor replacement execution",
        )
        for output_path in [
            f"assets/{platform}/edit/mutation_sandbox/mutation_manifest.json",
            f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml",
            f"assets/{platform}/edit/mutation_sandbox/mutation_diff.json",
            f"assets/{platform}/edit/mutation_sandbox/rollback_manifest.json",
            f"assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json",
            f"assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md",
            f"assets/{platform}/edit/mutation_sandbox/README.md",
        ]:
            expect(output_path in steps[mutation_step_id].outputs, f"{mutation_step_id} missing output: {output_path}")
        expect(mutation_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {mutation_step_id}")
        import_step_id = f"{platform}_editor_software_import_executor"
        expect(import_step_id in steps, f"workflow must include {import_step_id}")
        expect(
            steps[import_step_id].agent == "editor-software-import-executor-agent",
            f"{import_step_id} must use editor-software-import-executor-agent",
        )
        expect(
            mutation_step_id in steps[import_step_id].depends_on,
            f"{import_step_id} must depend on editor project mutation sandbox",
        )
        for output_path in [
            f"assets/{platform}/edit/software_import_executor/import_executor_manifest.json",
            f"assets/{platform}/edit/software_import_executor/import_plan.json",
            f"assets/{platform}/edit/software_import_executor/import_commands.json",
            f"assets/{platform}/edit/software_import_executor/software_import_audit_log.json",
            f"assets/{platform}/edit/software_import_executor/rollback_safety_report.json",
            f"assets/{platform}/edit/software_import_executor/isolated_execution_request.md",
            f"assets/{platform}/edit/software_import_executor/README.md",
        ]:
            expect(output_path in steps[import_step_id].outputs, f"{import_step_id} missing output: {output_path}")
        expect(import_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {import_step_id}")
        runner_step_id = f"{platform}_editor_software_real_runner_sandbox"
        expect(runner_step_id in steps, f"workflow must include {runner_step_id}")
        expect(
            steps[runner_step_id].agent == "editor-software-real-runner-sandbox-agent",
            f"{runner_step_id} must use editor-software-real-runner-sandbox-agent",
        )
        expect(import_step_id in steps[runner_step_id].depends_on, f"{runner_step_id} must depend on software import executor")
        for output_path in [
            f"assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json",
            f"assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json",
            f"assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json",
            f"assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json",
            f"assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json",
            f"assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json",
            f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md",
            f"assets/{platform}/edit/software_real_runner_sandbox/README.md",
        ]:
            expect(output_path in steps[runner_step_id].outputs, f"{runner_step_id} missing output: {output_path}")
        expect(runner_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {runner_step_id}")
        evidence_step_id = f"{platform}_editor_software_run_evidence"
        expect(evidence_step_id in steps, f"workflow must include {evidence_step_id}")
        expect(
            steps[evidence_step_id].agent == "editor-software-run-evidence-agent",
            f"{evidence_step_id} must use editor-software-run-evidence-agent",
        )
        expect(runner_step_id in steps[evidence_step_id].depends_on, f"{evidence_step_id} must depend on real runner sandbox")
        for output_path in [
            f"assets/{platform}/edit/software_run_evidence/real_run_evidence_manifest.json",
            f"assets/{platform}/edit/software_run_evidence/evidence_validation_report.json",
            f"assets/{platform}/edit/software_run_evidence/rollback_decision_report.json",
            f"assets/{platform}/edit/software_run_evidence/post_launch_evidence_checklist.md",
            f"assets/{platform}/edit/software_run_evidence/README.md",
        ]:
            expect(output_path in steps[evidence_step_id].outputs, f"{evidence_step_id} missing output: {output_path}")
        expect(evidence_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {evidence_step_id}")
        bundle_step_id = f"{platform}_project_bundle"
        expect(bundle_step_id in steps, f"workflow must include {bundle_step_id}")
        expect(steps[bundle_step_id].agent == "project-bundle-agent", f"{bundle_step_id} must use project-bundle-agent")
        expect(
            depends_on_transitively(steps, bundle_step_id, evidence_step_id),
            f"{bundle_step_id} must be downstream of editor software run evidence",
        )
        expect(bundle_step_id in steps["fact_check"].depends_on, f"fact_check must depend on {bundle_step_id}")
    expect("final/video_production_package.json" in workflow.outputs, "workflow must export video production package")
    expect("final/materialization_manifest.json" in workflow.outputs, "workflow must export materialization manifest")
    expect("final/licensed_media_ingest_manifest.json" in workflow.outputs, "workflow must export licensed media ingest manifest")
    expect("final/licensed_media_proxy_manifest.json" in workflow.outputs, "workflow must export licensed media proxy manifest")
    expect("final/editor_replacement_instruction_manifest.json" in workflow.outputs, "workflow must export editor replacement instruction manifest")
    expect("final/editor_replacement_execution_manifest.json" in workflow.outputs, "workflow must export editor replacement execution manifest")
    expect("final/editor_project_mutation_manifest.json" in workflow.outputs, "workflow must export editor project mutation manifest")
    expect("final/editor_software_import_manifest.json" in workflow.outputs, "workflow must export editor software import manifest")
    expect("final/editor_software_real_runner_manifest.json" in workflow.outputs, "workflow must export editor software real runner manifest")
    expect("final/editor_software_run_evidence_manifest.json" in workflow.outputs, "workflow must export editor software run evidence manifest")
    expect("final/edit_project_manifest.json" in workflow.outputs, "workflow must export edit project manifest")
    expect("final/export_project_manifest.json" in workflow.outputs, "workflow must export export project manifest")
    expect("final/project_bundle_manifest.json" in workflow.outputs, "workflow must export project bundle manifest")


def validate_phase4_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 视频生产包验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect("final/video_production_package.json" in workflow_run.get("artifacts", []), "workflow artifacts missing video package")
        expect("final/materialization_manifest.json" in workflow_run.get("artifacts", []), "workflow artifacts missing materialization manifest")
        expect(
            "final/licensed_media_ingest_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing licensed media ingest manifest",
        )
        expect(
            "final/licensed_media_proxy_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing licensed media proxy manifest",
        )
        expect(
            "final/editor_replacement_instruction_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor replacement instruction manifest",
        )
        expect(
            "final/editor_replacement_execution_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor replacement execution manifest",
        )
        expect(
            "final/editor_project_mutation_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor project mutation manifest",
        )
        expect(
            "final/editor_software_import_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor software import manifest",
        )
        expect(
            "final/editor_software_real_runner_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor software real runner manifest",
        )
        expect(
            "final/editor_software_run_evidence_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor software run evidence manifest",
        )
        expect("final/edit_project_manifest.json" in workflow_run.get("artifacts", []), "workflow artifacts missing edit project manifest")
        expect("final/export_project_manifest.json" in workflow_run.get("artifacts", []), "workflow artifacts missing export project manifest")
        expect("final/project_bundle_manifest.json" in workflow_run.get("artifacts", []), "workflow artifacts missing project bundle manifest")

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        expect(modes_by_step.get("visual_assets") == "agent-local", "visual_assets must run through asset-agent handler")

        asset_plan = load_json(run_dir / "asset_plan.json")
        asset_tasks = load_json(run_dir / "assets/asset_generation_tasks.json")
        media_asset_manifest = load_json(run_dir / "assets/media_asset_manifest.json")
        expect(asset_plan.get("schema_version") == "phase4.asset_plan.v1", "asset_plan schema_version mismatch")
        expect(asset_plan.get("generated_by") == "asset-agent", "asset_plan must be generated by asset-agent")
        expect(asset_tasks.get("schema_version") == "phase4.asset_generation_tasks.v1", "asset tasks schema_version mismatch")
        expect(media_asset_manifest.get("schema_version") == "phase4.media_asset_manifest.v1", "media asset manifest schema_version mismatch")
        expect(asset_plan.get("video_platforms") == VIDEO_PLATFORMS, "asset_plan video platforms mismatch")
        platform_plans = {
            item.get("platform"): item
            for item in asset_plan.get("platform_plans", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            plan = platform_plans.get(platform)
            expect(isinstance(plan, dict), f"asset_plan missing platform plan: {platform}")
            expect(bool(plan.get("cover_prompt")), f"{platform} asset plan missing cover_prompt")
            expect(len(plan.get("shot_list", [])) >= 3, f"{platform} asset plan needs shot list")
            expect(len(plan.get("broll_list", [])) >= 2, f"{platform} asset plan needs B-roll list")
            clearance = plan.get("asset_clearance", {})
            expect(clearance.get("copyright_status") == "human_review_required", f"{platform} asset clearance must require human review")

        cover_prompts = (run_dir / "cover_prompts.md").read_text(encoding="utf-8")
        for label in ["抖音", "视频号", "B站"]:
            expect(label in cover_prompts, f"cover_prompts.md missing section for {label}")

        for platform in VIDEO_PLATFORMS:
            storyboard = load_json(run_dir / platform / "storyboard.json")
            shot_list = load_json(run_dir / platform / "shot_list.json")
            broll_list = load_json(run_dir / platform / "broll_list.json")
            expect(len(storyboard) >= 4, f"{platform} storyboard must have at least 4 scenes")
            expect(len(shot_list) == len(storyboard), f"{platform} shot_list must align with storyboard")
            expect(len(broll_list) >= 2, f"{platform} broll_list must have at least 2 assets")
            for path in [
                run_dir / platform / "script.md",
                run_dir / platform / "subtitles.srt",
                run_dir / platform / "cover_prompt.md",
            ]:
                expect(path.exists(), f"missing video deliverable: {path.relative_to(run_dir)}")
            cover_prompt = (run_dir / platform / "cover_prompt.md").read_text(encoding="utf-8")
            expect("Review note:" in cover_prompt, f"{platform} cover prompt must include review note")
            subtitles = (run_dir / platform / "subtitles.srt").read_text(encoding="utf-8")
            expect(subtitles.count("-->") == len(storyboard), f"{platform} subtitle blocks must match storyboard")
            timed_subtitles = load_json(run_dir / platform / "timed_subtitles.json")
            timed_srt = run_dir / platform / "timed_subtitles.srt"
            expect(timed_srt.exists(), f"{platform} timed subtitles SRT missing")
            expect(timed_subtitles.get("schema_version") == "phase4.timed_subtitles.v1", f"{platform} timed subtitles schema mismatch")
            expect(timed_subtitles.get("validation", {}).get("status") == "PASSED", f"{platform} timed subtitles validation must pass")
            expect(timed_subtitles.get("total_duration_seconds") == sum(int(scene["duration_seconds"]) for scene in storyboard), f"{platform} timed subtitles duration mismatch")
            expect(timed_srt.read_text(encoding="utf-8").count("-->") == timed_subtitles.get("subtitle_count"), f"{platform} timed SRT block count mismatch")
            voiceover_manifest = load_json(run_dir / "assets" / platform / "voiceover" / "voiceover_manifest.json")
            voiceover_audio = run_dir / "assets" / platform / "voiceover" / "voiceover.wav"
            expect(voiceover_audio.exists(), f"{platform} voiceover audio missing")
            expect(voiceover_audio.read_bytes()[:4] == b"RIFF", f"{platform} voiceover audio must be WAV")
            expect(voiceover_manifest.get("schema_version") == "phase4.voiceover_tts_manifest.v1", f"{platform} voiceover manifest schema mismatch")
            expect(isinstance(voiceover_manifest.get("provider_external"), bool), f"{platform} voiceover provider mode must be recorded")
            expect(voiceover_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} voiceover manifest validation must pass")
            expect(voiceover_manifest.get("segment_count") == timed_subtitles.get("subtitle_count"), f"{platform} voiceover segment count mismatch")
            expect(modes_by_step.get(f"{platform}_asset_materialization") == "agent-local", f"{platform} materialization must run through run_agent")
            material_manifest = load_json(run_dir / "assets" / platform / "materials" / "material_manifest.json")
            material_readme = run_dir / "assets" / platform / "materials" / "README.md"
            expect(material_readme.exists(), f"{platform} material README missing")
            expect(material_manifest.get("schema_version") == "phase4.materialized_assets_manifest.v1", f"{platform} material manifest schema mismatch")
            expect(material_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} material manifest validation must pass")
            expect(
                material_manifest.get("export_boundary", {}).get("asset_materialization") == "performed_locally_reference_only",
                f"{platform} materialization boundary mismatch",
            )
            material_assets = material_manifest.get("materialized_assets", [])
            expect(isinstance(material_assets, list) and material_assets, f"{platform} material references must be non-empty")
            for asset in material_assets:
                expect(asset.get("asset_type") == "broll_reference", f"{platform} material asset type mismatch")
                expect(asset.get("licensed_final_media_required") is True, f"{platform} material reference must require licensed final media")
                reference_path = str(asset.get("reference_path") or "")
                expect(reference_path and (run_dir / reference_path).exists(), f"{platform} material reference missing: {reference_path}")
                expect((run_dir / reference_path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{platform} material reference must be PNG")
            expect(modes_by_step.get(f"{platform}_licensed_media_ingest") == "agent-local", f"{platform} licensed media ingest must run through run_agent")
            licensed_ingest_manifest = load_json(run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json")
            licensed_ingest_readme = run_dir / "assets" / platform / "licensed_media" / "README.md"
            licensed_review_handoff = run_dir / "assets" / platform / "licensed_media" / "review_handoff.md"
            expect(licensed_ingest_readme.exists(), f"{platform} licensed media ingest README missing")
            expect(licensed_review_handoff.exists(), f"{platform} licensed media review handoff missing")
            expect(licensed_ingest_manifest.get("schema_version") == "phase4.licensed_media_ingest_manifest.v1", f"{platform} licensed ingest schema mismatch")
            expect(licensed_ingest_manifest.get("artifact_type") == "licensed_media_ingest", f"{platform} licensed ingest type mismatch")
            expect(licensed_ingest_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} licensed ingest validation must pass")
            expect(licensed_ingest_manifest.get("validation", {}).get("intake_complete") is False, f"{platform} licensed ingest should await human media")
            expect(
                licensed_ingest_manifest.get("summary", {}).get("pending_human_media_count", 0) >= 1,
                f"{platform} licensed ingest must keep pending human media",
            )
            expect(
                licensed_ingest_manifest.get("export_boundary", {}).get("licensed_media_ingest")
                == "review_handoff_only_pending_human_supplied_media",
                f"{platform} licensed ingest boundary mismatch",
            )
            expect(
                licensed_ingest_manifest.get("export_boundary", {}).get("external_asset_search") == "not_performed",
                f"{platform} licensed ingest must not search external assets",
            )
            expect(modes_by_step.get(f"{platform}_licensed_media_proxy") == "agent-local", f"{platform} licensed media proxy must run through run_agent")
            proxy_manifest = load_json(run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json")
            replacement_suggestions = load_json(run_dir / "assets" / platform / "licensed_media" / "replacement_suggestions.json")
            proxy_readme = run_dir / "assets" / platform / "licensed_media" / "proxy" / "README.md"
            expect(proxy_readme.exists(), f"{platform} licensed media proxy README missing")
            expect(proxy_manifest.get("schema_version") == "phase4.licensed_media_proxy_manifest.v1", f"{platform} proxy manifest schema mismatch")
            expect(proxy_manifest.get("artifact_type") == "licensed_media_proxy", f"{platform} proxy manifest type mismatch")
            expect(replacement_suggestions.get("schema_version") == "phase4.licensed_media_replacement_suggestions.v1", f"{platform} replacement suggestions schema mismatch")
            expect(replacement_suggestions.get("artifact_type") == "licensed_media_replacement_suggestions", f"{platform} replacement suggestions type mismatch")
            expect(proxy_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} proxy validation must pass")
            expect(proxy_manifest.get("validation", {}).get("proxy_copy_complete_for_ready_media") is True, f"{platform} proxy copy completeness must pass")
            proxy_summary = proxy_manifest.get("summary", {})
            expect(proxy_summary.get("required_final_media_count", 0) >= 1, f"{platform} proxy summary must be non-empty")
            expect(proxy_summary.get("ready_source_media_count") == 0, f"{platform} default run should have no ready proxy source media")
            expect(proxy_summary.get("proxy_copied_count") == 0, f"{platform} default run should not copy proxy media")
            expect(proxy_summary.get("pending_human_media_count", 0) >= 1, f"{platform} default run should keep pending human media")
            for suggestion in replacement_suggestions.get("suggestions", []):
                expect(suggestion.get("replacement_status") == "pending_human_media", f"{platform} default replacement suggestion should await human media")
                expect(suggestion.get("proxy_media_path") is None, f"{platform} default replacement suggestion must not invent proxy media")
            expect(
                proxy_manifest.get("export_boundary", {}).get("licensed_media_proxy")
                == "performed_locally_from_human_registered_media_only",
                f"{platform} proxy boundary mismatch",
            )
            for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
                expect(proxy_manifest.get("export_boundary", {}).get(key) == "not_performed", f"{platform} proxy must mark {key} as not_performed")
            expect(proxy_manifest.get("export_boundary", {}).get("editing_software") == "not_opened", f"{platform} proxy must not open editing software")
            edit_timeline = load_json(run_dir / "assets" / platform / "edit" / "edit_timeline.json")
            edit_manifest = load_json(run_dir / "assets" / platform / "edit" / "edit_manifest.json")
            edit_edl = run_dir / "assets" / platform / "edit" / "draft_cut.edl"
            expect(edit_edl.exists(), f"{platform} draft EDL missing")
            expect(edit_timeline.get("schema_version") == "phase4.edit_timeline.v1", f"{platform} edit timeline schema mismatch")
            expect(edit_manifest.get("schema_version") == "phase4.edit_project_manifest.v1", f"{platform} edit manifest schema mismatch")
            expect(edit_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} edit manifest validation must pass")
            expect(len(edit_timeline.get("tracks", {}).get("video", [])) == len(storyboard), f"{platform} edit video clips must match storyboard")
            placeholders = [
                clip.get("broll_placeholder")
                for clip in edit_timeline.get("tracks", {}).get("video", [])
                if isinstance(clip, dict) and isinstance(clip.get("broll_placeholder"), dict)
            ]
            expect(placeholders, f"{platform} edit timeline must include proxy-aware B-roll placeholders")
            for placeholder in placeholders:
                expect(placeholder.get("licensed_media_proxy_manifest_path") == f"assets/{platform}/licensed_media/proxy_manifest.json", f"{platform} edit placeholder missing proxy manifest path")
                expect(placeholder.get("licensed_media_replacement_suggestions_path") == f"assets/{platform}/licensed_media/replacement_suggestions.json", f"{platform} edit placeholder missing replacement suggestions path")
                expect(placeholder.get("licensed_media_proxy_readme_path") == f"assets/{platform}/licensed_media/proxy/README.md", f"{platform} edit placeholder missing proxy README path")
                expect(placeholder.get("proxy_media_path") is None, f"{platform} default edit placeholder must not include proxy media")
            export_manifest = load_json(run_dir / "assets" / platform / "edit" / "export_manifest.json")
            export_fcpxml = run_dir / "assets" / platform / "edit" / "project.fcpxml"
            expect(export_fcpxml.exists(), f"{platform} FCPXML missing")
            expect(export_manifest.get("schema_version") == "phase4.export_project_manifest.v1", f"{platform} export manifest schema mismatch")
            expect(export_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} export manifest validation must pass")
            project_bundle_manifest = load_json(run_dir / "assets" / platform / "bundle" / "project_bundle_manifest.json")
            project_bundle_zip = run_dir / "assets" / platform / "bundle" / "project_bundle.zip"
            expect(project_bundle_zip.exists(), f"{platform} project bundle ZIP missing")
            expect(project_bundle_manifest.get("schema_version") == "phase4.project_bundle_manifest.v1", f"{platform} project bundle schema mismatch")
            expect(project_bundle_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} project bundle validation must pass")
            preview_metadata = load_json(run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json")
            frames = preview_metadata.get("frames", [])
            expect(preview_metadata.get("schema_version") == "phase4.storyboard_preview_metadata.v1", f"{platform} preview metadata schema mismatch")
            expect(len(frames) == len(storyboard), f"{platform} storyboard preview frame count must match storyboard")
            for frame in frames:
                expect((run_dir / frame["path"]).exists(), f"{platform} keyframe path missing: {frame['path']}")

        video_package = load_json(run_dir / "final/video_production_package.json")
        final_materialization_manifest = load_json(run_dir / "final/materialization_manifest.json")
        final_licensed_ingest_manifest = load_json(run_dir / "final/licensed_media_ingest_manifest.json")
        final_licensed_proxy_manifest = load_json(run_dir / "final/licensed_media_proxy_manifest.json")
        final_editor_instruction_manifest = load_json(run_dir / "final/editor_replacement_instruction_manifest.json")
        final_editor_execution_manifest = load_json(run_dir / "final/editor_replacement_execution_manifest.json")
        final_editor_mutation_manifest = load_json(run_dir / "final/editor_project_mutation_manifest.json")
        final_editor_import_manifest = load_json(run_dir / "final/editor_software_import_manifest.json")
        final_editor_real_runner_manifest = load_json(run_dir / "final/editor_software_real_runner_manifest.json")
        final_editor_run_evidence_manifest = load_json(run_dir / "final/editor_software_run_evidence_manifest.json")
        final_edit_manifest = load_json(run_dir / "final/edit_project_manifest.json")
        final_export_manifest = load_json(run_dir / "final/export_project_manifest.json")
        final_project_bundle_manifest = load_json(run_dir / "final/project_bundle_manifest.json")
        expect(video_package.get("schema_version") == "phase4.video_production_package.v1", "video package schema_version mismatch")
        expect(video_package.get("package_type") == "video_production_package", "video package type mismatch")
        expect(video_package.get("asset_generation_tasks") == "assets/asset_generation_tasks.json", "video package missing asset tasks path")
        expect(video_package.get("media_asset_manifest") == "assets/media_asset_manifest.json", "video package missing media manifest path")
        expect(video_package.get("materialization_manifest") == "final/materialization_manifest.json", "video package missing materialization manifest path")
        expect(
            video_package.get("licensed_media_ingest_manifest") == "final/licensed_media_ingest_manifest.json",
            "video package missing licensed media ingest manifest path",
        )
        expect(
            video_package.get("licensed_media_proxy_manifest") == "final/licensed_media_proxy_manifest.json",
            "video package missing licensed media proxy manifest path",
        )
        expect(
            video_package.get("editor_replacement_instruction_manifest") == "final/editor_replacement_instruction_manifest.json",
            "video package missing editor replacement instruction manifest path",
        )
        expect(
            video_package.get("editor_replacement_execution_manifest") == "final/editor_replacement_execution_manifest.json",
            "video package missing editor replacement execution manifest path",
        )
        expect(
            video_package.get("editor_project_mutation_manifest") == "final/editor_project_mutation_manifest.json",
            "video package missing editor project mutation manifest path",
        )
        expect(
            video_package.get("editor_software_import_manifest") == "final/editor_software_import_manifest.json",
            "video package missing editor software import manifest path",
        )
        expect(
            video_package.get("editor_software_real_runner_manifest") == "final/editor_software_real_runner_manifest.json",
            "video package missing editor software real runner manifest path",
        )
        expect(
            video_package.get("editor_software_run_evidence_manifest") == "final/editor_software_run_evidence_manifest.json",
            "video package missing editor software run evidence manifest path",
        )
        expect(video_package.get("edit_project_manifest") == "final/edit_project_manifest.json", "video package missing edit project manifest path")
        expect(video_package.get("export_project_manifest") == "final/export_project_manifest.json", "video package missing export project manifest path")
        expect(video_package.get("project_bundle_manifest") == "final/project_bundle_manifest.json", "video package missing project bundle manifest path")
        expect(video_package.get("generated_assets"), "video package must embed generated assets")
        expect(
            any(asset.get("asset_type") == "broll_reference" for asset in video_package.get("generated_assets", []) if isinstance(asset, dict)),
            "video package must embed materialized B-roll references",
        )
        expect(video_package.get("video_platforms") == VIDEO_PLATFORMS, "video package platforms mismatch")
        expect(video_package.get("review_required") is True, "video package must require review")
        expect(final_materialization_manifest.get("schema_version") == "phase4.materialization_bundle_manifest.v1", "final materialization manifest schema mismatch")
        expect(final_materialization_manifest.get("artifact_type") == "materialization_bundle", "final materialization manifest type mismatch")
        expect(final_materialization_manifest.get("platforms") == VIDEO_PLATFORMS, "final materialization manifest platforms mismatch")
        expect(final_materialization_manifest.get("validation", {}).get("status") == "PASSED", "final materialization manifest validation must pass")
        expect(
            final_licensed_ingest_manifest.get("schema_version") == "phase4.licensed_media_ingest_bundle_manifest.v1",
            "final licensed ingest manifest schema mismatch",
        )
        expect(
            final_licensed_ingest_manifest.get("artifact_type") == "licensed_media_ingest_bundle",
            "final licensed ingest manifest type mismatch",
        )
        expect(final_licensed_ingest_manifest.get("platforms") == VIDEO_PLATFORMS, "final licensed ingest manifest platforms mismatch")
        expect(final_licensed_ingest_manifest.get("validation", {}).get("status") == "PASSED", "final licensed ingest validation must pass")
        expect(final_licensed_ingest_manifest.get("validation", {}).get("intake_complete") is False, "final licensed ingest should await human media")
        expect(
            final_licensed_ingest_manifest.get("validation", {}).get("pending_human_media_count", 0) >= 1,
            "final licensed ingest must keep pending human media",
        )
        expect(
            final_licensed_proxy_manifest.get("schema_version") == "phase4.licensed_media_proxy_bundle_manifest.v1",
            "final licensed proxy manifest schema mismatch",
        )
        expect(
            final_licensed_proxy_manifest.get("artifact_type") == "licensed_media_proxy_bundle",
            "final licensed proxy manifest type mismatch",
        )
        expect(final_licensed_proxy_manifest.get("platforms") == VIDEO_PLATFORMS, "final licensed proxy manifest platforms mismatch")
        expect(final_licensed_proxy_manifest.get("validation", {}).get("status") == "PASSED", "final licensed proxy validation must pass")
        expect(final_licensed_proxy_manifest.get("validation", {}).get("ready_source_media_count") == 0, "default final proxy should have no ready source media")
        expect(final_licensed_proxy_manifest.get("validation", {}).get("proxy_copied_count") == 0, "default final proxy should not copy media")
        expect(final_licensed_proxy_manifest.get("validation", {}).get("pending_human_media_count", 0) >= 1, "default final proxy should keep pending human media")
        expect(final_licensed_proxy_manifest.get("validation", {}).get("proxy_copy_complete_for_ready_media") is True, "final proxy copy completeness must pass")
        expect(
            final_editor_instruction_manifest.get("schema_version") == "phase4.editor_replacement_instruction_bundle_manifest.v1",
            "final editor instruction manifest schema mismatch",
        )
        expect(
            final_editor_instruction_manifest.get("artifact_type") == "editor_replacement_instruction_bundle",
            "final editor instruction manifest type mismatch",
        )
        expect(final_editor_instruction_manifest.get("platforms") == VIDEO_PLATFORMS, "final editor instruction platforms mismatch")
        expect(final_editor_instruction_manifest.get("validation", {}).get("status") == "PASSED", "final editor instruction validation must pass")
        expect(
            final_editor_instruction_manifest.get("validation", {}).get("human_confirmation_gate_active") is True,
            "final editor instruction human gate must be active",
        )
        expect(
            final_editor_instruction_manifest.get("validation", {}).get("replacement_execution_performed") is False,
            "final editor instruction must not execute replacements",
        )
        expect(
            final_editor_instruction_manifest.get("validation", {}).get("editing_software_opened") is False,
            "final editor instruction must not open editing software",
        )
        expect(final_editor_instruction_manifest.get("validation", {}).get("instruction_count", 0) >= 1, "final editor instruction count must be non-empty")
        expect(
            final_editor_instruction_manifest.get("validation", {}).get("ready_pending_human_confirmation_count") == 0,
            "default final editor instruction should have no ready commands",
        )
        expect(
            final_editor_instruction_manifest.get("validation", {}).get("pending_human_media_count", 0) >= 1,
            "default final editor instruction must keep pending media",
        )
        instruction_boundary = final_editor_instruction_manifest.get("export_boundary", {})
        expect(
            instruction_boundary.get("editor_replacement_instructions") == "performed_locally_template_and_instruction_only",
            "final editor instruction boundary mismatch",
        )
        expect(instruction_boundary.get("replacement_execution") == "not_performed", "final editor instruction must not execute replacement")
        expect(instruction_boundary.get("editing_software") == "not_opened", "final editor instruction must not open editing software")
        expect(instruction_boundary.get("project_file_mutation") == "not_performed", "final editor instruction must not mutate project files")
        for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
            expect(instruction_boundary.get(key) == "not_performed", f"final editor instruction must mark {key} as not_performed")
        expect(
            final_editor_execution_manifest.get("schema_version") == "phase4.editor_replacement_execution_bundle_manifest.v1",
            "final editor execution manifest schema mismatch",
        )
        expect(
            final_editor_execution_manifest.get("artifact_type") == "editor_replacement_execution_bundle",
            "final editor execution manifest type mismatch",
        )
        expect(final_editor_execution_manifest.get("platforms") == VIDEO_PLATFORMS, "final editor execution platforms mismatch")
        expect(final_editor_execution_manifest.get("validation", {}).get("status") == "PASSED", "final editor execution validation must pass")
        expect(final_editor_execution_manifest.get("validation", {}).get("command_count", 0) >= 1, "final editor execution count must be non-empty")
        expect(
            final_editor_execution_manifest.get("validation", {}).get("human_execution_approval_required") is True,
            "final editor execution must require explicit approval",
        )
        expect(
            final_editor_execution_manifest.get("validation", {}).get("human_execution_approval_present_count") == 0,
            "default final editor execution must not have approval files",
        )
        expect(
            final_editor_execution_manifest.get("validation", {}).get("human_execution_approval_valid_count") == 0,
            "default final editor execution must not have valid approvals",
        )
        expect(
            final_editor_execution_manifest.get("validation", {}).get("replacement_execution_performed") is False,
            "final editor execution must not execute replacements",
        )
        expect(
            final_editor_execution_manifest.get("validation", {}).get("editing_software_opened") is False,
            "final editor execution must not open editing software",
        )
        expect(
            final_editor_execution_manifest.get("validation", {}).get("project_file_mutation_performed") is False,
            "final editor execution must not mutate project files",
        )
        execution_boundary = final_editor_execution_manifest.get("export_boundary", {})
        expect(
            execution_boundary.get("editor_replacement_execution") == EDITOR_REPLACEMENT_EXECUTION_BOUNDARY,
            "final editor execution boundary mismatch",
        )
        expect(execution_boundary.get("replacement_execution") == "not_performed", "final editor execution must not execute replacement")
        expect(execution_boundary.get("editing_software") == "not_opened", "final editor execution must not open editing software")
        expect(execution_boundary.get("project_file_mutation") == "not_performed", "final editor execution must not mutate project files")
        expect(execution_boundary.get("requires_explicit_human_approval") is True, "final editor execution must require approval")
        for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
            expect(execution_boundary.get(key) == "not_performed", f"final editor execution must mark {key} as not_performed")
        expect(
            final_editor_mutation_manifest.get("schema_version") == "phase4.editor_project_mutation_bundle_manifest.v1",
            "final editor mutation manifest schema mismatch",
        )
        expect(
            final_editor_mutation_manifest.get("artifact_type") == "editor_project_mutation_bundle",
            "final editor mutation manifest type mismatch",
        )
        expect(final_editor_mutation_manifest.get("platforms") == VIDEO_PLATFORMS, "final editor mutation platforms mismatch")
        expect(final_editor_mutation_manifest.get("validation", {}).get("status") == "PASSED", "final editor mutation validation must pass")
        expect(final_editor_mutation_manifest.get("validation", {}).get("execution_item_count", 0) >= 1, "final editor mutation count must be non-empty")
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("human_mutation_approval_required") is True,
            "final editor mutation must require explicit mutation approval",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("human_mutation_approval_present_count") == 0,
            "default final editor mutation must not have approval files",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("human_mutation_approval_valid_count") == 0,
            "default final editor mutation must not have valid approvals",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("mutation_applied_count") == 0,
            "default final editor mutation must not apply sandbox mutations",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("patched_copy_generated") is True,
            "final editor mutation must generate patched copies",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("original_project_mutated") is False,
            "final editor mutation must not mutate original projects",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("replacement_execution_performed") is False,
            "final editor mutation must not execute replacements",
        )
        expect(
            final_editor_mutation_manifest.get("validation", {}).get("editing_software_opened") is False,
            "final editor mutation must not open editing software",
        )
        mutation_boundary = final_editor_mutation_manifest.get("export_boundary", {})
        expect(
            mutation_boundary.get("editor_project_mutation_sandbox") == EDITOR_PROJECT_MUTATION_BOUNDARY,
            "final editor mutation boundary mismatch",
        )
        expect(mutation_boundary.get("original_project_mutation") == "not_performed", "final editor mutation must not mutate original project")
        expect(mutation_boundary.get("replacement_execution") == "not_performed", "final editor mutation must not execute replacement")
        expect(mutation_boundary.get("editing_software") == "not_opened", "final editor mutation must not open editing software")
        expect(
            mutation_boundary.get("project_file_mutation") == "patched_copy_only_original_not_mutated",
            "final editor mutation project mutation policy mismatch",
        )
        expect(mutation_boundary.get("requires_explicit_human_mutation_approval") is True, "final editor mutation must require approval")
        for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
            expect(mutation_boundary.get(key) == "not_performed", f"final editor mutation must mark {key} as not_performed")
        expect(
            final_editor_import_manifest.get("schema_version") == "phase4.editor_software_import_bundle_manifest.v1",
            "final editor software import manifest schema mismatch",
        )
        expect(
            final_editor_import_manifest.get("artifact_type") == "editor_software_import_bundle",
            "final editor software import manifest type mismatch",
        )
        expect(final_editor_import_manifest.get("platforms") == VIDEO_PLATFORMS, "final editor software import platforms mismatch")
        expect(final_editor_import_manifest.get("validation", {}).get("status") == "PASSED", "final editor software import validation must pass")
        expect(final_editor_import_manifest.get("validation", {}).get("import_item_count", 0) >= 1, "final editor software import count must be non-empty")
        expect(
            final_editor_import_manifest.get("validation", {}).get("human_software_import_approval_required") is True,
            "final editor software import must require explicit approval",
        )
        expect(
            final_editor_import_manifest.get("validation", {}).get("human_software_import_approval_present_count") == 0,
            "default final editor software import must not have approval files",
        )
        expect(
            final_editor_import_manifest.get("validation", {}).get("human_software_import_approval_valid_count") == 0,
            "default final editor software import must not have valid approvals",
        )
        expect(
            final_editor_import_manifest.get("validation", {}).get("ready_for_isolated_manual_import_count") == 0,
            "default final editor software import must not expose ready imports",
        )
        expect(
            final_editor_import_manifest.get("validation", {}).get("software_import_execution_performed") is False,
            "final editor software import must not execute imports",
        )
        expect(
            final_editor_import_manifest.get("validation", {}).get("editing_software_opened") is False,
            "final editor software import must not open editing software",
        )
        expect(
            final_editor_import_manifest.get("validation", {}).get("project_file_mutation_performed") is False,
            "final editor software import must not mutate project files",
        )
        import_boundary = final_editor_import_manifest.get("export_boundary", {})
        expect(
            import_boundary.get("editor_software_import_executor") == EDITOR_SOFTWARE_IMPORT_BOUNDARY,
            "final editor software import boundary mismatch",
        )
        expect(import_boundary.get("software_import_execution") == "not_performed", "final editor software import must not execute import")
        expect(import_boundary.get("editing_software") == "not_opened", "final editor software import must not open editing software")
        expect(import_boundary.get("project_file_mutation") == "not_performed_by_executor", "final editor software import project mutation policy mismatch")
        expect(import_boundary.get("requires_explicit_human_software_import_approval") is True, "final editor software import must require approval")
        expect(import_boundary.get("external_software_isolation") == "required_before_manual_launch", "final editor software import must require isolation")
        for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
            expect(import_boundary.get(key) == "not_performed", f"final editor software import must mark {key} as not_performed")
        expect(
            final_editor_real_runner_manifest.get("schema_version") == "phase4.editor_software_real_runner_bundle_manifest.v1",
            "final editor software real runner manifest schema mismatch",
        )
        expect(
            final_editor_real_runner_manifest.get("artifact_type") == "editor_software_real_runner_bundle",
            "final editor software real runner manifest type mismatch",
        )
        expect(final_editor_real_runner_manifest.get("platforms") == VIDEO_PLATFORMS, "final editor software real runner platforms mismatch")
        expect(final_editor_real_runner_manifest.get("validation", {}).get("status") == "PASSED", "final editor software real runner validation must pass")
        expect(
            final_editor_real_runner_manifest.get("validation", {}).get("real_software_launch_performed") is False,
            "final editor software real runner must not launch software",
        )
        expect(
            final_editor_real_runner_manifest.get("validation", {}).get("process_spawned") is False,
            "final editor software real runner must not spawn process",
        )
        real_runner_boundary = final_editor_real_runner_manifest.get("export_boundary", {})
        expect(
            real_runner_boundary.get("editor_software_real_runner_sandbox") == EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY,
            "final editor software real runner boundary mismatch",
        )
        expect(real_runner_boundary.get("real_software_launch") == "not_performed", "final editor software real runner must not launch")
        expect(real_runner_boundary.get("process_spawn") == "not_performed", "final editor software real runner must not spawn")
        expect(
            final_editor_run_evidence_manifest.get("schema_version") == "phase4.editor_software_run_evidence_bundle_manifest.v1",
            "final editor software run evidence manifest schema mismatch",
        )
        expect(
            final_editor_run_evidence_manifest.get("artifact_type") == "editor_software_run_evidence_bundle",
            "final editor software run evidence manifest type mismatch",
        )
        expect(final_editor_run_evidence_manifest.get("platforms") == VIDEO_PLATFORMS, "final editor software run evidence platforms mismatch")
        expect(final_editor_run_evidence_manifest.get("validation", {}).get("status") == "PASSED", "final editor software run evidence validation must pass")
        expect(
            final_editor_run_evidence_manifest.get("validation", {}).get("process_spawned_by_automation") is False,
            "final editor software run evidence must not spawn process",
        )
        run_evidence_boundary = final_editor_run_evidence_manifest.get("export_boundary", {})
        expect(
            run_evidence_boundary.get("editor_software_run_evidence") == EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY,
            "final editor software run evidence boundary mismatch",
        )
        expect(run_evidence_boundary.get("real_software_launch_by_automation") == "not_performed", "final run evidence must not launch software")
        expect(run_evidence_boundary.get("process_spawn") == "not_performed", "final run evidence must not spawn")
        expect(final_edit_manifest.get("schema_version") == "phase4.edit_project_bundle_manifest.v1", "final edit manifest schema mismatch")
        expect(final_edit_manifest.get("artifact_type") == "edit_project_bundle", "final edit manifest type mismatch")
        expect(final_edit_manifest.get("platforms") == VIDEO_PLATFORMS, "final edit manifest platforms mismatch")
        expect(final_edit_manifest.get("validation", {}).get("status") == "PASSED", "final edit manifest validation must pass")
        expect(final_export_manifest.get("schema_version") == "phase4.export_project_bundle_manifest.v1", "final export manifest schema mismatch")
        expect(final_export_manifest.get("artifact_type") == "export_project_bundle", "final export manifest type mismatch")
        expect(final_export_manifest.get("platforms") == VIDEO_PLATFORMS, "final export manifest platforms mismatch")
        expect(final_export_manifest.get("validation", {}).get("status") == "PASSED", "final export manifest validation must pass")
        expect(final_project_bundle_manifest.get("schema_version") == "phase4.project_bundle_bundle_manifest.v1", "final project bundle manifest schema mismatch")
        expect(final_project_bundle_manifest.get("artifact_type") == "project_bundle_bundle", "final project bundle manifest type mismatch")
        expect(final_project_bundle_manifest.get("platforms") == VIDEO_PLATFORMS, "final project bundle manifest platforms mismatch")
        expect(final_project_bundle_manifest.get("validation", {}).get("status") == "PASSED", "final project bundle manifest validation must pass")
        final_edit_projects = {
            project.get("platform"): project
            for project in final_edit_manifest.get("platform_projects", [])
            if isinstance(project, dict)
        }
        final_export_projects = {
            project.get("platform"): project
            for project in final_export_manifest.get("platform_projects", [])
            if isinstance(project, dict)
        }
        final_project_bundles = {
            bundle.get("platform"): bundle
            for bundle in final_project_bundle_manifest.get("platform_bundles", [])
            if isinstance(bundle, dict)
        }
        final_materials = {
            item.get("platform"): item
            for item in final_materialization_manifest.get("platform_materials", [])
            if isinstance(item, dict)
        }
        final_ingests = {
            item.get("platform"): item
            for item in final_licensed_ingest_manifest.get("platform_ingests", [])
            if isinstance(item, dict)
        }
        final_proxies = {
            item.get("platform"): item
            for item in final_licensed_proxy_manifest.get("platform_proxies", [])
            if isinstance(item, dict)
        }
        final_instructions = {
            item.get("platform"): item
            for item in final_editor_instruction_manifest.get("platform_instructions", [])
            if isinstance(item, dict)
        }
        final_executions = {
            item.get("platform"): item
            for item in final_editor_execution_manifest.get("platform_executions", [])
            if isinstance(item, dict)
        }
        final_mutations = {
            item.get("platform"): item
            for item in final_editor_mutation_manifest.get("platform_mutations", [])
            if isinstance(item, dict)
        }
        final_imports = {
            item.get("platform"): item
            for item in final_editor_import_manifest.get("platform_imports", [])
            if isinstance(item, dict)
        }
        final_real_runners = {
            item.get("platform"): item
            for item in final_editor_real_runner_manifest.get("platform_runners", [])
            if isinstance(item, dict)
        }
        final_run_evidence = {
            item.get("platform"): item
            for item in final_editor_run_evidence_manifest.get("platform_evidence", [])
            if isinstance(item, dict)
        }
        boundary = video_package.get("export_boundary", {})
        expect(
            boundary.get("cover_image_generation") == "performed_locally_pending_human_review",
            "export boundary must mark local cover generation as pending review",
        )
        expect(
            boundary.get("storyboard_preview_generation") == "performed_locally_pending_human_review",
            "export boundary must mark storyboard preview generation as pending review",
        )
        expect(
            boundary.get("asset_materialization") == "performed_locally_reference_only",
            "export boundary must mark asset materialization as reference-only",
        )
        expect(
            boundary.get("licensed_media_ingest") == "review_handoff_only_pending_human_supplied_media",
            "export boundary must mark licensed media ingest as review handoff only",
        )
        expect(
            boundary.get("licensed_media_proxy") == "performed_locally_from_human_registered_media_only",
            "export boundary must mark licensed media proxy as local human-registered copy only",
        )
        expect(
            boundary.get("editor_replacement_instructions") == "performed_locally_template_and_instruction_only",
            "export boundary must mark editor replacement instructions as template-only",
        )
        expect(
            boundary.get("editor_replacement_execution") == EDITOR_REPLACEMENT_EXECUTION_BOUNDARY,
            "export boundary must mark editor replacement execution as blocked pending approval",
        )
        expect(
            boundary.get("editor_project_mutation_sandbox") == EDITOR_PROJECT_MUTATION_BOUNDARY,
            "export boundary must mark editor project mutation sandbox as blocked pending approval",
        )
        expect(
            boundary.get("editor_software_import_executor") == EDITOR_SOFTWARE_IMPORT_BOUNDARY,
            "export boundary must mark editor software import executor as blocked pending approval",
        )
        expect(
            boundary.get("editor_software_real_runner_sandbox") == EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY,
            "export boundary must mark editor software real runner as blocked pending approval",
        )
        expect(
            boundary.get("editor_software_run_evidence") == EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY,
            "export boundary must mark editor software run evidence as blocked pending human result",
        )
        expect(
            boundary.get("subtitle_timing_correction") == "performed_locally_deterministic_no_tts",
            "export boundary must mark subtitle timing as deterministic and no-TTS",
        )
        expect(
            boundary.get("voiceover_tts_generation") in EXPECTED_VOICEOVER_TTS_BOUNDARIES,
            "export boundary must mark voiceover TTS with a supported provider mode",
        )
        expect(
            boundary.get("edit_project_generation") == "performed_locally_draft_no_editing_software",
            "export boundary must mark edit project as local draft and no editing software",
        )
        expect(
            boundary.get("export_project_generation") == "performed_locally_draft_no_editing_software",
            "export boundary must mark export project as local draft and no editing software",
        )
        expect(
            boundary.get("project_bundle_generation") == "performed_locally_draft_no_editing_software",
            "export boundary must mark project bundle as local draft and no editing software",
        )
        for key in ["publishing", "upload", "login_or_cookie_refresh", "asset_download", "external_asset_search"]:
            expect(boundary.get(key) == "not_performed", f"export boundary must mark {key} as not_performed")

        packages = video_package.get("platform_packages", [])
        expect(len(packages) == 3, "video package must include three platform packages")
        for package in packages:
            platform = package.get("platform")
            deliverables = package.get("deliverables", {})
            missing = sorted(REQUIRED_VIDEO_DELIVERABLES - set(deliverables))
            expect(not missing, f"{platform} package missing deliverables: {missing}")
            expect("generated_cover_image" in deliverables, f"{platform} package missing generated cover image")
            expect("generated_cover_metadata" in deliverables, f"{platform} package missing generated cover metadata")
            expect("storyboard_preview" in deliverables, f"{platform} package missing storyboard preview")
            expect("storyboard_preview_metadata" in deliverables, f"{platform} package missing storyboard preview metadata")
            expect("timed_subtitles" in deliverables, f"{platform} package missing timed subtitles")
            expect("timed_subtitles_srt" in deliverables, f"{platform} package missing timed subtitles SRT")
            expect("voiceover_audio" in deliverables, f"{platform} package missing voiceover audio")
            expect("voiceover_manifest" in deliverables, f"{platform} package missing voiceover manifest")
            expect("edit_timeline" in deliverables, f"{platform} package missing edit timeline")
            expect("edit_manifest" in deliverables, f"{platform} package missing edit manifest")
            expect("draft_cut_edl" in deliverables, f"{platform} package missing draft cut EDL")
            expect("project_fcpxml" in deliverables, f"{platform} package missing FCPXML")
            expect("project_import_readme" in deliverables, f"{platform} package missing project import readme")
            expect("offline_media_report" in deliverables, f"{platform} package missing offline media report")
            expect("export_manifest" in deliverables, f"{platform} package missing export manifest")
            expect("project_bundle_zip" in deliverables, f"{platform} package missing project bundle ZIP")
            expect("project_bundle_manifest" in deliverables, f"{platform} package missing project bundle manifest")
            expect("project_bundle_file_manifest" in deliverables, f"{platform} package missing project bundle file manifest")
            expect("project_bundle_readme" in deliverables, f"{platform} package missing project bundle README")
            expect("material_manifest" in deliverables, f"{platform} package missing material manifest")
            expect("material_readme" in deliverables, f"{platform} package missing material README")
            expect("licensed_media_ingest_manifest" in deliverables, f"{platform} package missing licensed ingest manifest")
            expect("licensed_media_ingest_readme" in deliverables, f"{platform} package missing licensed ingest README")
            expect("licensed_media_review_handoff" in deliverables, f"{platform} package missing licensed media review handoff")
            expect("licensed_media_proxy_manifest" in deliverables, f"{platform} package missing licensed proxy manifest")
            expect("licensed_media_replacement_suggestions" in deliverables, f"{platform} package missing replacement suggestions")
            expect("licensed_media_proxy_readme" in deliverables, f"{platform} package missing licensed proxy README")
            expect("editor_replacement_instruction_manifest" in deliverables, f"{platform} package missing editor instruction manifest")
            expect("editor_replacement_commands" in deliverables, f"{platform} package missing editor replacement commands")
            expect("editor_import_template_fcpxml" in deliverables, f"{platform} package missing editor import template")
            expect("editor_human_confirmation_checklist" in deliverables, f"{platform} package missing editor confirmation checklist")
            expect("editor_replacement_readme" in deliverables, f"{platform} package missing editor replacement README")
            expect("editor_replacement_execution_manifest" in deliverables, f"{platform} package missing editor execution manifest")
            expect("editor_replacement_execution_plan" in deliverables, f"{platform} package missing editor execution plan")
            expect("editor_replacement_execution_audit_log" in deliverables, f"{platform} package missing editor execution audit log")
            expect("editor_replacement_approval_request" in deliverables, f"{platform} package missing editor execution approval request")
            expect("editor_replacement_execution_readme" in deliverables, f"{platform} package missing editor execution README")
            expect("editor_project_mutation_manifest" in deliverables, f"{platform} package missing editor project mutation manifest")
            expect("editor_project_patched_fcpxml" in deliverables, f"{platform} package missing patched project FCPXML")
            expect("editor_project_mutation_diff" in deliverables, f"{platform} package missing mutation diff")
            expect("editor_project_rollback_manifest" in deliverables, f"{platform} package missing rollback manifest")
            expect("editor_project_mutation_audit_log" in deliverables, f"{platform} package missing mutation audit log")
            expect("editor_project_final_review_checklist" in deliverables, f"{platform} package missing final review checklist")
            expect("editor_project_mutation_readme" in deliverables, f"{platform} package missing mutation README")
            expect("editor_software_import_manifest" in deliverables, f"{platform} package missing software import manifest")
            expect("editor_software_import_plan" in deliverables, f"{platform} package missing software import plan")
            expect("editor_software_import_commands" in deliverables, f"{platform} package missing software import commands")
            expect("editor_software_import_audit_log" in deliverables, f"{platform} package missing software import audit log")
            expect("editor_software_import_rollback_safety_report" in deliverables, f"{platform} package missing software import rollback safety report")
            expect("editor_software_import_execution_request" in deliverables, f"{platform} package missing software import execution request")
            expect("editor_software_import_readme" in deliverables, f"{platform} package missing software import README")
            expect("editor_software_real_runner_manifest" in deliverables, f"{platform} package missing real runner manifest")
            expect("editor_software_real_runner_environment_snapshot" in deliverables, f"{platform} package missing real runner environment")
            expect("editor_software_real_runner_launch_plan" in deliverables, f"{platform} package missing real runner launch plan")
            expect("editor_software_real_runner_command_preview" in deliverables, f"{platform} package missing real runner command preview")
            expect("editor_software_real_runner_audit_log" in deliverables, f"{platform} package missing real runner audit log")
            expect("editor_software_real_runner_evidence_manifest" in deliverables, f"{platform} package missing real runner evidence manifest")
            expect("editor_software_real_runner_approval_request" in deliverables, f"{platform} package missing real runner approval request")
            expect("editor_software_real_runner_readme" in deliverables, f"{platform} package missing real runner README")
            expect("editor_software_run_evidence_manifest" in deliverables, f"{platform} package missing run evidence manifest")
            expect("editor_software_run_evidence_validation_report" in deliverables, f"{platform} package missing run evidence validation report")
            expect("editor_software_run_evidence_rollback_decision_report" in deliverables, f"{platform} package missing rollback decision report")
            expect("editor_software_run_evidence_checklist" in deliverables, f"{platform} package missing post-launch evidence checklist")
            expect("editor_software_run_evidence_readme" in deliverables, f"{platform} package missing run evidence README")
            for deliverable_path in deliverables.values():
                expect((run_dir / deliverable_path).exists(), f"{platform} deliverable path missing: {deliverable_path}")
            asset_plan_section = package.get("asset_plan", {})
            expect(asset_plan_section.get("shot_list"), f"{platform} package missing embedded shot list")
            expect(asset_plan_section.get("broll_list"), f"{platform} package missing embedded B-roll list")
            expect(package.get("review_required") is True, f"{platform} package must require review")
            expect(package.get("generated_assets"), f"{platform} package must embed generated assets")
            material_summary = package.get("materialized_assets", {})
            expect(material_summary.get("validation_status") == "PASSED", f"{platform} material summary must pass")
            expect(material_summary.get("materialized_count", 0) >= 1, f"{platform} material summary must be non-empty")
            expect(material_summary.get("licensed_final_media_required") is True, f"{platform} material summary must require licensed final media")
            for reference_path in material_summary.get("reference_paths", []):
                asset_id = Path(reference_path).stem.replace("_reference", "")
                expect(deliverables.get(f"material_reference_{asset_id}") == reference_path, f"{platform} package missing material reference {asset_id}")
            final_material = final_materials.get(platform)
            expect(isinstance(final_material, dict), f"final materialization manifest missing platform: {platform}")
            expect(final_material.get("manifest_path") == deliverables.get("material_manifest"), f"{platform} final material manifest path mismatch")
            expect(final_material.get("validation", {}).get("status") == "PASSED", f"{platform} final material validation must pass")
            ingest_summary = package.get("licensed_media_ingest", {})
            expect(ingest_summary.get("validation_status") == "PASSED", f"{platform} licensed ingest summary must pass")
            expect(ingest_summary.get("required_final_media_count", 0) >= 1, f"{platform} licensed ingest summary must be non-empty")
            expect(ingest_summary.get("pending_human_media_count", 0) >= 1, f"{platform} licensed ingest must keep pending human media")
            expect(ingest_summary.get("intake_complete") is False, f"{platform} licensed ingest should await human media")
            expect(ingest_summary.get("licensed_final_media_required") is True, f"{platform} licensed ingest must require final media")
            final_ingest = final_ingests.get(platform)
            expect(isinstance(final_ingest, dict), f"final licensed ingest manifest missing platform: {platform}")
            expect(final_ingest.get("manifest_path") == deliverables.get("licensed_media_ingest_manifest"), f"{platform} final ingest manifest path mismatch")
            expect(final_ingest.get("review_handoff_path") == deliverables.get("licensed_media_review_handoff"), f"{platform} final ingest handoff path mismatch")
            expect(final_ingest.get("validation", {}).get("status") == "PASSED", f"{platform} final licensed ingest validation must pass")
            proxy_summary = package.get("licensed_media_proxy", {})
            expect(proxy_summary.get("validation_status") == "PASSED", f"{platform} licensed proxy summary must pass")
            expect(proxy_summary.get("required_final_media_count", 0) >= 1, f"{platform} licensed proxy summary must be non-empty")
            expect(proxy_summary.get("ready_source_media_count") == 0, f"{platform} default licensed proxy should have no ready source")
            expect(proxy_summary.get("proxy_copied_count") == 0, f"{platform} default licensed proxy should not copy media")
            expect(proxy_summary.get("pending_human_media_count", 0) >= 1, f"{platform} default licensed proxy must keep pending media")
            expect(proxy_summary.get("proxy_copy_complete_for_ready_media") is True, f"{platform} licensed proxy copy completeness must pass")
            final_proxy = final_proxies.get(platform)
            expect(isinstance(final_proxy, dict), f"final licensed proxy manifest missing platform: {platform}")
            expect(final_proxy.get("manifest_path") == deliverables.get("licensed_media_proxy_manifest"), f"{platform} final proxy manifest path mismatch")
            expect(final_proxy.get("replacement_suggestions_path") == deliverables.get("licensed_media_replacement_suggestions"), f"{platform} final proxy suggestions path mismatch")
            expect(final_proxy.get("readme_path") == deliverables.get("licensed_media_proxy_readme"), f"{platform} final proxy readme path mismatch")
            expect(final_proxy.get("validation", {}).get("status") == "PASSED", f"{platform} final licensed proxy validation must pass")
            instruction_manifest = load_json(run_dir / str(deliverables.get("editor_replacement_instruction_manifest")))
            replacement_commands = load_json(run_dir / str(deliverables.get("editor_replacement_commands")))
            expect(
                instruction_manifest.get("schema_version") == "phase4.editor_replacement_instruction_manifest.v1",
                f"{platform} editor instruction schema mismatch",
            )
            expect(instruction_manifest.get("artifact_type") == "editor_replacement_instructions", f"{platform} editor instruction type mismatch")
            expect(instruction_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} editor instruction validation must pass")
            expect(
                instruction_manifest.get("validation", {}).get("human_confirmation_gate_active") is True,
                f"{platform} editor instruction human gate must be active",
            )
            expect(
                instruction_manifest.get("validation", {}).get("replacement_execution_performed") is False,
                f"{platform} editor instruction must not execute replacements",
            )
            expect(
                instruction_manifest.get("validation", {}).get("editing_software_opened") is False,
                f"{platform} editor instruction must not open editing software",
            )
            expect(
                replacement_commands.get("schema_version") == "phase4.editor_replacement_commands.v1",
                f"{platform} editor commands schema mismatch",
            )
            expect(replacement_commands.get("artifact_type") == "editor_replacement_commands", f"{platform} editor commands type mismatch")
            for command in replacement_commands.get("commands", []):
                expect(command.get("dry_run_only") is True, f"{platform} editor command must be dry-run only")
                expect(command.get("human_confirmation_required") is True, f"{platform} editor command must require confirmation")
                expect(command.get("confirmation_gate_status") == "pending_human_confirmation", f"{platform} editor command gate mismatch")
                expect(command.get("execution_status") == "not_executed", f"{platform} editor command must not execute")
            try:
                root = ET.parse(run_dir / str(deliverables.get("editor_import_template_fcpxml"))).getroot()
            except ET.ParseError as exc:
                fail(f"{platform} editor import template is invalid XML: {exc}")
            expect(root.tag == "fcpxml", f"{platform} editor import template root must be fcpxml")
            instruction_summary = package.get("editor_replacement_instructions", {})
            expect(instruction_summary.get("validation_status") == "PASSED", f"{platform} editor instruction summary must pass")
            expect(instruction_summary.get("instruction_count", 0) >= 1, f"{platform} editor instruction summary must be non-empty")
            expect(instruction_summary.get("ready_pending_human_confirmation_count") == 0, f"{platform} default editor instructions should have no ready commands")
            expect(instruction_summary.get("pending_human_media_count", 0) >= 1, f"{platform} default editor instructions must keep pending media")
            expect(instruction_summary.get("human_confirmation_gate_active") is True, f"{platform} editor instruction summary must keep human gate active")
            expect(instruction_summary.get("replacement_execution_performed") is False, f"{platform} editor instruction summary must not execute replacements")
            expect(instruction_summary.get("editing_software_opened") is False, f"{platform} editor instruction summary must not open editing software")
            expect(instruction_summary.get("human_confirmation_required") is True, f"{platform} editor instruction summary must require confirmation")
            final_instruction = final_instructions.get(platform)
            expect(isinstance(final_instruction, dict), f"final editor instruction manifest missing platform: {platform}")
            expect(
                final_instruction.get("manifest_path") == deliverables.get("editor_replacement_instruction_manifest"),
                f"{platform} final editor instruction manifest path mismatch",
            )
            expect(
                final_instruction.get("replacement_commands_path") == deliverables.get("editor_replacement_commands"),
                f"{platform} final editor commands path mismatch",
            )
            expect(
                final_instruction.get("editor_import_template_path") == deliverables.get("editor_import_template_fcpxml"),
                f"{platform} final editor template path mismatch",
            )
            expect(
                final_instruction.get("human_confirmation_checklist_path") == deliverables.get("editor_human_confirmation_checklist"),
                f"{platform} final editor checklist path mismatch",
            )
            expect(final_instruction.get("readme_path") == deliverables.get("editor_replacement_readme"), f"{platform} final editor README path mismatch")
            expect(final_instruction.get("validation", {}).get("status") == "PASSED", f"{platform} final editor instruction validation must pass")
            expect(
                final_instruction.get("validation", {}).get("human_confirmation_gate_active") is True,
                f"{platform} final editor instruction gate must be active",
            )
            expect(
                final_instruction.get("validation", {}).get("replacement_execution_performed") is False,
                f"{platform} final editor instruction must not execute replacements",
            )
            execution_manifest = load_json(run_dir / str(deliverables.get("editor_replacement_execution_manifest")))
            execution_plan = load_json(run_dir / str(deliverables.get("editor_replacement_execution_plan")))
            execution_audit_log = load_json(run_dir / str(deliverables.get("editor_replacement_execution_audit_log")))
            expect(
                execution_manifest.get("schema_version") == "phase4.editor_replacement_execution_manifest.v1",
                f"{platform} editor execution schema mismatch",
            )
            expect(execution_manifest.get("artifact_type") == "editor_replacement_execution", f"{platform} editor execution type mismatch")
            expect(execution_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} editor execution validation must pass")
            expect(execution_manifest.get("validation", {}).get("human_execution_approval_required") is True, f"{platform} editor execution must require approval")
            expect(execution_manifest.get("validation", {}).get("human_execution_approval_present") is False, f"{platform} default editor execution must not have approval")
            expect(execution_manifest.get("validation", {}).get("human_execution_approval_valid") is False, f"{platform} default editor execution approval must be invalid")
            expect(execution_manifest.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} editor execution must not execute")
            expect(execution_manifest.get("validation", {}).get("editing_software_opened") is False, f"{platform} editor execution must not open editing software")
            expect(execution_manifest.get("validation", {}).get("project_file_mutation_performed") is False, f"{platform} editor execution must not mutate project")
            expect(
                execution_manifest.get("export_boundary", {}).get("editor_replacement_execution") == EDITOR_REPLACEMENT_EXECUTION_BOUNDARY,
                f"{platform} editor execution boundary mismatch",
            )
            expect(
                execution_plan.get("schema_version") == "phase4.editor_replacement_execution_plan.v1",
                f"{platform} editor execution plan schema mismatch",
            )
            expect(execution_plan.get("artifact_type") == "editor_replacement_execution_plan", f"{platform} editor execution plan type mismatch")
            expect(
                execution_audit_log.get("schema_version") == "phase4.editor_replacement_execution_audit_log.v1",
                f"{platform} editor execution audit schema mismatch",
            )
            expect(execution_audit_log.get("artifact_type") == "editor_replacement_execution_audit_log", f"{platform} editor execution audit type mismatch")
            for command in execution_plan.get("commands", []):
                expect(command.get("execution_performed") is False, f"{platform} execution plan command must not execute")
                expect(command.get("editing_software_opened") is False, f"{platform} execution plan command must not open editor")
                expect(command.get("project_file_mutation_performed") is False, f"{platform} execution plan command must not mutate project")
            execution_summary = package.get("editor_replacement_execution", {})
            expect(execution_summary.get("validation_status") == "PASSED", f"{platform} editor execution summary must pass")
            expect(execution_summary.get("command_count", 0) >= 1, f"{platform} editor execution summary must be non-empty")
            expect(execution_summary.get("human_execution_approval_required") is True, f"{platform} editor execution summary must require approval")
            expect(execution_summary.get("human_execution_approval_present") is False, f"{platform} default execution summary should not have approval")
            expect(execution_summary.get("human_execution_approval_valid") is False, f"{platform} default execution approval should be invalid")
            expect(execution_summary.get("replacement_execution_performed") is False, f"{platform} editor execution summary must not execute")
            expect(execution_summary.get("editing_software_opened") is False, f"{platform} editor execution summary must not open editing software")
            expect(execution_summary.get("project_file_mutation_performed") is False, f"{platform} editor execution summary must not mutate project")
            expect(execution_summary.get("review_required") is True, f"{platform} editor execution summary must require review")
            expect(
                execution_summary.get("editor_replacement_execution") == EDITOR_REPLACEMENT_EXECUTION_BOUNDARY,
                f"{platform} editor execution summary boundary mismatch",
            )
            final_execution = final_executions.get(platform)
            expect(isinstance(final_execution, dict), f"final editor execution manifest missing platform: {platform}")
            expect(
                final_execution.get("manifest_path") == deliverables.get("editor_replacement_execution_manifest"),
                f"{platform} final editor execution manifest path mismatch",
            )
            expect(
                final_execution.get("execution_plan_path") == deliverables.get("editor_replacement_execution_plan"),
                f"{platform} final editor execution plan path mismatch",
            )
            expect(
                final_execution.get("audit_log_path") == deliverables.get("editor_replacement_execution_audit_log"),
                f"{platform} final editor execution audit path mismatch",
            )
            expect(
                final_execution.get("approval_request_path") == deliverables.get("editor_replacement_approval_request"),
                f"{platform} final editor execution approval request path mismatch",
            )
            expect(final_execution.get("readme_path") == deliverables.get("editor_replacement_execution_readme"), f"{platform} final editor execution README path mismatch")
            expect(final_execution.get("validation", {}).get("status") == "PASSED", f"{platform} final editor execution validation must pass")
            expect(
                final_execution.get("validation", {}).get("human_execution_approval_required") is True,
                f"{platform} final editor execution must require approval",
            )
            expect(
                final_execution.get("validation", {}).get("replacement_execution_performed") is False,
                f"{platform} final editor execution must not execute replacements",
            )
            mutation_manifest = load_json(run_dir / str(deliverables.get("editor_project_mutation_manifest")))
            mutation_diff = load_json(run_dir / str(deliverables.get("editor_project_mutation_diff")))
            mutation_audit_log = load_json(run_dir / str(deliverables.get("editor_project_mutation_audit_log")))
            rollback_manifest = load_json(run_dir / str(deliverables.get("editor_project_rollback_manifest")))
            patched_project_path = run_dir / str(deliverables.get("editor_project_patched_fcpxml"))
            expect(patched_project_path.exists(), f"{platform} patched project FCPXML missing")
            try:
                xml_text = "\n".join(
                    line
                    for line in patched_project_path.read_text(encoding="utf-8").splitlines()
                    if not line.strip().startswith("<!DOCTYPE")
                )
                ET.fromstring(xml_text.encode("utf-8"))
            except ET.ParseError as exc:
                fail(f"{platform} patched project FCPXML is invalid XML: {exc}")
            expect(
                mutation_manifest.get("schema_version") == "phase4.editor_project_mutation_sandbox_manifest.v1",
                f"{platform} editor mutation schema mismatch",
            )
            expect(mutation_manifest.get("artifact_type") == "editor_project_mutation_sandbox", f"{platform} editor mutation type mismatch")
            expect(mutation_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} editor mutation validation must pass")
            expect(mutation_manifest.get("validation", {}).get("human_mutation_approval_required") is True, f"{platform} editor mutation must require approval")
            expect(mutation_manifest.get("validation", {}).get("human_mutation_approval_present") is False, f"{platform} default editor mutation must not have approval")
            expect(mutation_manifest.get("validation", {}).get("human_mutation_approval_valid") is False, f"{platform} default editor mutation approval must be invalid")
            expect(mutation_manifest.get("validation", {}).get("mutation_applied_count") == 0, f"{platform} default editor mutation must not apply patches")
            expect(mutation_manifest.get("validation", {}).get("patched_copy_generated") is True, f"{platform} editor mutation must generate patched copy")
            expect(mutation_manifest.get("validation", {}).get("original_project_mutated") is False, f"{platform} editor mutation must not mutate original")
            expect(mutation_manifest.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} editor mutation must not execute")
            expect(mutation_manifest.get("validation", {}).get("editing_software_opened") is False, f"{platform} editor mutation must not open editor")
            expect(
                mutation_manifest.get("export_boundary", {}).get("editor_project_mutation_sandbox") == EDITOR_PROJECT_MUTATION_BOUNDARY,
                f"{platform} editor mutation boundary mismatch",
            )
            expect(mutation_diff.get("schema_version") == "phase4.editor_project_mutation_diff.v1", f"{platform} mutation diff schema mismatch")
            expect(mutation_diff.get("artifact_type") == "editor_project_mutation_diff", f"{platform} mutation diff type mismatch")
            expect(rollback_manifest.get("schema_version") == "phase4.editor_project_mutation_rollback_manifest.v1", f"{platform} rollback schema mismatch")
            expect(rollback_manifest.get("rollback_policy") == "discard_patched_copy_keep_original_project", f"{platform} rollback policy mismatch")
            expect(mutation_audit_log.get("schema_version") == "phase4.editor_project_mutation_audit_log.v1", f"{platform} mutation audit schema mismatch")
            expect(mutation_audit_log.get("artifact_type") == "editor_project_mutation_audit_log", f"{platform} mutation audit type mismatch")
            for item in mutation_manifest.get("mutation_items", []):
                expect(item.get("original_project_mutated") is False, f"{platform} mutation item must not mutate original")
                expect(item.get("replacement_execution_performed") is False, f"{platform} mutation item must not execute")
                expect(item.get("editing_software_opened") is False, f"{platform} mutation item must not open editor")
            mutation_summary = package.get("editor_project_mutation_sandbox", {})
            expect(mutation_summary.get("validation_status") == "PASSED", f"{platform} editor mutation summary must pass")
            expect(mutation_summary.get("execution_item_count", 0) >= 1, f"{platform} editor mutation summary must be non-empty")
            expect(mutation_summary.get("human_mutation_approval_required") is True, f"{platform} editor mutation summary must require approval")
            expect(mutation_summary.get("human_mutation_approval_present") is False, f"{platform} default mutation summary should not have approval")
            expect(mutation_summary.get("human_mutation_approval_valid") is False, f"{platform} default mutation approval should be invalid")
            expect(mutation_summary.get("mutation_applied_count") == 0, f"{platform} default mutation summary must not apply patches")
            expect(mutation_summary.get("patched_copy_generated") is True, f"{platform} editor mutation summary must generate patched copy")
            expect(mutation_summary.get("original_project_mutated") is False, f"{platform} editor mutation summary must not mutate original")
            expect(mutation_summary.get("replacement_execution_performed") is False, f"{platform} editor mutation summary must not execute")
            expect(mutation_summary.get("editing_software_opened") is False, f"{platform} editor mutation summary must not open editor")
            expect(
                mutation_summary.get("editor_project_mutation_sandbox") == EDITOR_PROJECT_MUTATION_BOUNDARY,
                f"{platform} editor mutation summary boundary mismatch",
            )
            final_mutation = final_mutations.get(platform)
            expect(isinstance(final_mutation, dict), f"final editor mutation manifest missing platform: {platform}")
            expect(
                final_mutation.get("manifest_path") == deliverables.get("editor_project_mutation_manifest"),
                f"{platform} final editor mutation manifest path mismatch",
            )
            expect(
                final_mutation.get("patched_project_path") == deliverables.get("editor_project_patched_fcpxml"),
                f"{platform} final editor patched project path mismatch",
            )
            expect(
                final_mutation.get("mutation_diff_path") == deliverables.get("editor_project_mutation_diff"),
                f"{platform} final editor mutation diff path mismatch",
            )
            expect(
                final_mutation.get("rollback_manifest_path") == deliverables.get("editor_project_rollback_manifest"),
                f"{platform} final editor rollback path mismatch",
            )
            expect(
                final_mutation.get("audit_log_path") == deliverables.get("editor_project_mutation_audit_log"),
                f"{platform} final editor mutation audit path mismatch",
            )
            expect(
                final_mutation.get("final_review_checklist_path") == deliverables.get("editor_project_final_review_checklist"),
                f"{platform} final editor mutation checklist path mismatch",
            )
            expect(final_mutation.get("readme_path") == deliverables.get("editor_project_mutation_readme"), f"{platform} final editor mutation README path mismatch")
            expect(final_mutation.get("validation", {}).get("status") == "PASSED", f"{platform} final editor mutation validation must pass")
            expect(
                final_mutation.get("validation", {}).get("original_project_mutated") is False,
                f"{platform} final editor mutation must not mutate original",
            )
            expect(
                final_mutation.get("validation", {}).get("replacement_execution_performed") is False,
                f"{platform} final editor mutation must not execute replacements",
            )
            import_manifest = load_json(run_dir / str(deliverables.get("editor_software_import_manifest")))
            import_plan = load_json(run_dir / str(deliverables.get("editor_software_import_plan")))
            import_commands = load_json(run_dir / str(deliverables.get("editor_software_import_commands")))
            import_audit_log = load_json(run_dir / str(deliverables.get("editor_software_import_audit_log")))
            rollback_safety_report = load_json(
                run_dir / str(deliverables.get("editor_software_import_rollback_safety_report"))
            )
            expect(
                import_manifest.get("schema_version") == "phase4.editor_software_import_executor_manifest.v1",
                f"{platform} editor software import schema mismatch",
            )
            expect(
                import_manifest.get("artifact_type") == "editor_software_import_executor",
                f"{platform} editor software import type mismatch",
            )
            expect(import_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} editor software import validation must pass")
            expect(
                import_manifest.get("validation", {}).get("human_software_import_approval_required") is True,
                f"{platform} editor software import must require approval",
            )
            expect(
                import_manifest.get("validation", {}).get("human_software_import_approval_present") is False,
                f"{platform} default editor software import must not have approval",
            )
            expect(
                import_manifest.get("validation", {}).get("human_software_import_approval_valid") is False,
                f"{platform} default editor software import approval must be invalid",
            )
            expect(
                import_manifest.get("validation", {}).get("software_import_execution_performed") is False,
                f"{platform} editor software import must not execute",
            )
            expect(
                import_manifest.get("validation", {}).get("editing_software_opened") is False,
                f"{platform} editor software import must not open editing software",
            )
            expect(
                import_manifest.get("validation", {}).get("project_file_mutation_performed") is False,
                f"{platform} editor software import must not mutate project files",
            )
            expect(
                import_manifest.get("export_boundary", {}).get("editor_software_import_executor") == EDITOR_SOFTWARE_IMPORT_BOUNDARY,
                f"{platform} editor software import boundary mismatch",
            )
            expect(
                import_plan.get("schema_version") == "phase4.editor_software_import_plan.v1",
                f"{platform} editor software import plan schema mismatch",
            )
            expect(import_plan.get("artifact_type") == "editor_software_import_plan", f"{platform} editor software import plan type mismatch")
            expect(
                import_commands.get("schema_version") == "phase4.editor_software_import_commands.v1",
                f"{platform} editor software import commands schema mismatch",
            )
            expect(
                import_commands.get("artifact_type") == "editor_software_import_commands",
                f"{platform} editor software import commands type mismatch",
            )
            expect(
                import_audit_log.get("schema_version") == "phase4.editor_software_import_audit_log.v1",
                f"{platform} editor software import audit schema mismatch",
            )
            expect(
                import_audit_log.get("artifact_type") == "editor_software_import_audit_log",
                f"{platform} editor software import audit type mismatch",
            )
            expect(
                rollback_safety_report.get("schema_version") == "phase4.editor_software_import_rollback_safety_report.v1",
                f"{platform} editor software import rollback safety schema mismatch",
            )
            expect(
                rollback_safety_report.get("artifact_type") == "editor_software_import_rollback_safety_report",
                f"{platform} editor software import rollback safety type mismatch",
            )
            for command in import_commands.get("commands", []):
                expect(command.get("command_type") == "editor_software_import", f"{platform} import command type mismatch")
                expect(command.get("dry_run_only") is True, f"{platform} import command must be dry-run")
                expect(command.get("auto_execute") is False, f"{platform} import command must not auto-execute")
                expect(command.get("human_software_import_approval_required") is True, f"{platform} import command must require approval")
                expect(command.get("import_execution_performed") is False, f"{platform} import command must not execute import")
                expect(command.get("editing_software_opened") is False, f"{platform} import command must not open editor")
                expect(command.get("project_file_mutation_performed") is False, f"{platform} import command must not mutate project")
                expect(command.get("upload_performed") is False, f"{platform} import command must not upload")
                expect(command.get("publishing_performed") is False, f"{platform} import command must not publish")
            import_summary = package.get("editor_software_import_executor", {})
            expect(import_summary.get("validation_status") == "PASSED", f"{platform} editor software import summary must pass")
            expect(import_summary.get("editor_software_import_executor") == EDITOR_SOFTWARE_IMPORT_BOUNDARY, f"{platform} editor software import summary boundary mismatch")
            expect(import_summary.get("import_item_count", 0) >= 1, f"{platform} editor software import summary must be non-empty")
            expect(import_summary.get("ready_for_isolated_manual_import_count") == 0, f"{platform} default import summary must not expose ready imports")
            expect(import_summary.get("blocked_pending_approval_count", 0) >= 1, f"{platform} default import summary must block on approval")
            expect(import_summary.get("patched_project_exists") is True, f"{platform} import summary must see patched project")
            expect(import_summary.get("rollback_available") is True, f"{platform} import summary must see rollback")
            expect(import_summary.get("human_software_import_approval_required") is True, f"{platform} import summary must require approval")
            expect(import_summary.get("human_software_import_approval_present") is False, f"{platform} default import summary should not have approval")
            expect(import_summary.get("human_software_import_approval_valid") is False, f"{platform} default import approval should be invalid")
            expect(import_summary.get("software_import_execution_performed") is False, f"{platform} import summary must not execute import")
            expect(import_summary.get("editing_software_opened") is False, f"{platform} import summary must not open editor")
            expect(import_summary.get("project_file_mutation_performed") is False, f"{platform} import summary must not mutate project")
            final_import = final_imports.get(platform)
            expect(isinstance(final_import, dict), f"final editor software import manifest missing platform: {platform}")
            expect(
                final_import.get("manifest_path") == deliverables.get("editor_software_import_manifest"),
                f"{platform} final software import manifest path mismatch",
            )
            expect(
                final_import.get("import_plan_path") == deliverables.get("editor_software_import_plan"),
                f"{platform} final software import plan path mismatch",
            )
            expect(
                final_import.get("import_commands_path") == deliverables.get("editor_software_import_commands"),
                f"{platform} final software import commands path mismatch",
            )
            expect(
                final_import.get("audit_log_path") == deliverables.get("editor_software_import_audit_log"),
                f"{platform} final software import audit path mismatch",
            )
            expect(
                final_import.get("rollback_safety_report_path")
                == deliverables.get("editor_software_import_rollback_safety_report"),
                f"{platform} final software import rollback safety path mismatch",
            )
            expect(
                final_import.get("execution_request_path") == deliverables.get("editor_software_import_execution_request"),
                f"{platform} final software import request path mismatch",
            )
            expect(final_import.get("readme_path") == deliverables.get("editor_software_import_readme"), f"{platform} final software import README path mismatch")
            expect(final_import.get("validation", {}).get("status") == "PASSED", f"{platform} final software import validation must pass")
            expect(
                final_import.get("validation", {}).get("software_import_execution_performed") is False,
                f"{platform} final software import must not execute",
            )
            expect(
                final_import.get("validation", {}).get("editing_software_opened") is False,
                f"{platform} final software import must not open editor",
            )
            real_runner_manifest = load_json(run_dir / str(deliverables.get("editor_software_real_runner_manifest")))
            real_runner_launch = load_json(run_dir / str(deliverables.get("editor_software_real_runner_launch_plan")))
            real_runner_commands = load_json(run_dir / str(deliverables.get("editor_software_real_runner_command_preview")))
            real_runner_evidence = load_json(run_dir / str(deliverables.get("editor_software_real_runner_evidence_manifest")))
            expect(
                real_runner_manifest.get("schema_version") == "phase4.editor_software_real_runner_sandbox_manifest.v1",
                f"{platform} real runner schema mismatch",
            )
            expect(real_runner_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} real runner validation must pass")
            expect(
                real_runner_manifest.get("export_boundary", {}).get("editor_software_real_runner_sandbox")
                == EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY,
                f"{platform} real runner boundary mismatch",
            )
            expect(real_runner_manifest.get("validation", {}).get("process_spawned") is False, f"{platform} real runner must not spawn")
            expect(real_runner_launch.get("schema_version") == "phase4.editor_software_real_runner_launch_plan.v1", f"{platform} real runner launch schema mismatch")
            expect(real_runner_commands.get("schema_version") == "phase4.editor_software_real_runner_command_preview.v1", f"{platform} real runner command schema mismatch")
            expect(real_runner_evidence.get("schema_version") == "phase4.editor_software_real_runner_evidence_manifest.v1", f"{platform} real runner evidence schema mismatch")
            real_runner_summary = package.get("editor_software_real_runner_sandbox", {})
            expect(real_runner_summary.get("validation_status") == "PASSED", f"{platform} real runner summary must pass")
            expect(real_runner_summary.get("editor_software_real_runner_sandbox") == EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY, f"{platform} real runner summary boundary mismatch")
            expect(real_runner_summary.get("process_spawned") is False, f"{platform} real runner summary must not spawn")
            final_real_runner = final_real_runners.get(platform)
            expect(isinstance(final_real_runner, dict), f"final real runner manifest missing platform: {platform}")
            expect(
                final_real_runner.get("manifest_path") == deliverables.get("editor_software_real_runner_manifest"),
                f"{platform} final real runner manifest path mismatch",
            )

            run_evidence_manifest = load_json(run_dir / str(deliverables.get("editor_software_run_evidence_manifest")))
            run_evidence_validation = load_json(run_dir / str(deliverables.get("editor_software_run_evidence_validation_report")))
            run_evidence_rollback = load_json(run_dir / str(deliverables.get("editor_software_run_evidence_rollback_decision_report")))
            expect(
                run_evidence_manifest.get("schema_version") == "phase4.editor_software_run_evidence_manifest.v1",
                f"{platform} run evidence schema mismatch",
            )
            expect(run_evidence_manifest.get("validation", {}).get("status") == "PASSED", f"{platform} run evidence validation must pass")
            expect(
                run_evidence_manifest.get("export_boundary", {}).get("editor_software_run_evidence")
                == EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY,
                f"{platform} run evidence boundary mismatch",
            )
            expect(run_evidence_manifest.get("validation", {}).get("process_spawned_by_automation") is False, f"{platform} run evidence must not spawn")
            expect(
                run_evidence_validation.get("schema_version") == "phase4.editor_software_run_evidence_validation_report.v1",
                f"{platform} run evidence validation report schema mismatch",
            )
            expect(
                run_evidence_rollback.get("schema_version") == "phase4.editor_software_run_evidence_rollback_decision_report.v1",
                f"{platform} rollback decision report schema mismatch",
            )
            run_evidence_summary = package.get("editor_software_run_evidence", {})
            expect(run_evidence_summary.get("validation_status") == "PASSED", f"{platform} run evidence summary must pass")
            expect(run_evidence_summary.get("editor_software_run_evidence") == EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY, f"{platform} run evidence summary boundary mismatch")
            expect(run_evidence_summary.get("human_real_run_result_present") is False, f"{platform} default run evidence should not have result")
            final_evidence = final_run_evidence.get(platform)
            expect(isinstance(final_evidence, dict), f"final run evidence manifest missing platform: {platform}")
            expect(
                final_evidence.get("manifest_path") == deliverables.get("editor_software_run_evidence_manifest"),
                f"{platform} final run evidence manifest path mismatch",
            )
            timed_summary = package.get("timed_subtitles", {})
            expect(timed_summary.get("tts_ready") is True, f"{platform} timed subtitles must be TTS-ready")
            expect(timed_summary.get("validation_status") == "PASSED", f"{platform} timed subtitles summary must pass")
            voiceover_summary = package.get("voiceover_tts", {})
            expect(isinstance(voiceover_summary.get("provider_external"), bool), f"{platform} voiceover provider mode must be recorded")
            expect(voiceover_summary.get("validation_status") == "PASSED", f"{platform} voiceover summary must pass")
            edit_summary = package.get("edit_project", {})
            expect(edit_summary.get("validation_status") == "PASSED", f"{platform} edit project summary must pass")
            expect(edit_summary.get("video_duration_matches") is True, f"{platform} edit project video duration must match")
            final_edit_project = final_edit_projects.get(platform)
            expect(isinstance(final_edit_project, dict), f"final edit manifest missing platform: {platform}")
            expect(final_edit_project.get("timeline_path") == deliverables.get("edit_timeline"), f"{platform} final edit manifest timeline mismatch")
            expect(final_edit_project.get("manifest_path") == deliverables.get("edit_manifest"), f"{platform} final edit manifest manifest mismatch")
            expect(final_edit_project.get("edl_path") == deliverables.get("draft_cut_edl"), f"{platform} final edit manifest EDL mismatch")
            expect(final_edit_project.get("validation", {}).get("status") == "PASSED", f"{platform} final edit manifest validation must pass")
            export_summary = package.get("export_project", {})
            expect(export_summary.get("validation_status") == "PASSED", f"{platform} export project summary must pass")
            expect(export_summary.get("referenced_media_files_exist") is True, f"{platform} export project media refs must exist")
            final_export_project = final_export_projects.get(platform)
            expect(isinstance(final_export_project, dict), f"final export manifest missing platform: {platform}")
            expect(final_export_project.get("project_path") == deliverables.get("project_fcpxml"), f"{platform} final export manifest FCPXML mismatch")
            expect(final_export_project.get("manifest_path") == deliverables.get("export_manifest"), f"{platform} final export manifest manifest mismatch")
            project_bundle_summary = package.get("project_bundle", {})
            expect(project_bundle_summary.get("validation_status") == "PASSED", f"{platform} project bundle summary must pass")
            expect(project_bundle_summary.get("required_files_present") is True, f"{platform} project bundle required files must exist")
            final_project_bundle = final_project_bundles.get(platform)
            expect(isinstance(final_project_bundle, dict), f"final project bundle manifest missing platform: {platform}")
            expect(final_project_bundle.get("bundle_path") == deliverables.get("project_bundle_zip"), f"{platform} final project bundle path mismatch")
            expect(final_project_bundle.get("manifest_path") == deliverables.get("project_bundle_manifest"), f"{platform} final project bundle manifest mismatch")
            expect(
                any(asset.get("asset_type") == "storyboard_frame" for asset in package.get("generated_assets", []) if isinstance(asset, dict)),
                f"{platform} package must embed storyboard frame metadata",
            )

        content_package = load_json(run_dir / "final/content_package_manifest.json")
        expect(
            content_package.get("video_production_package") == "final/video_production_package.json",
            "content package must reference video production package",
        )
        expect(
            content_package.get("materialization_manifest") == "final/materialization_manifest.json",
            "content package must reference materialization manifest",
        )
        expect(
            content_package.get("licensed_media_ingest_manifest") == "final/licensed_media_ingest_manifest.json",
            "content package must reference licensed media ingest manifest",
        )
        expect(
            content_package.get("licensed_media_proxy_manifest") == "final/licensed_media_proxy_manifest.json",
            "content package must reference licensed media proxy manifest",
        )
        expect(
            content_package.get("editor_replacement_instruction_manifest")
            == "final/editor_replacement_instruction_manifest.json",
            "content package must reference editor replacement instruction manifest",
        )
        expect(
            content_package.get("editor_replacement_execution_manifest")
            == "final/editor_replacement_execution_manifest.json",
            "content package must reference editor replacement execution manifest",
        )
        expect(
            content_package.get("editor_project_mutation_manifest") == "final/editor_project_mutation_manifest.json",
            "content package must reference editor project mutation manifest",
        )
        expect(
            content_package.get("edit_project_manifest") == "final/edit_project_manifest.json",
            "content package must reference edit project manifest",
        )
        expect(
            content_package.get("export_project_manifest") == "final/export_project_manifest.json",
            "content package must reference export project manifest",
        )
        expect(
            content_package.get("project_bundle_manifest") == "final/project_bundle_manifest.json",
            "content package must reference project bundle manifest",
        )


def main() -> int:
    validate_workflow_contract()
    print("Phase 4 drill passed: workflow video production contract")
    validate_phase4_run()
    print("Phase 4 drill passed: end-to-end video production package")
    print("Phase 4 video package validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
