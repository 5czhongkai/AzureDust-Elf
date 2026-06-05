from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
EXPECTED_OFFLINE_STATUSES = {
    "pending_human_licensed_media",
    "licensed_media_candidate_pending_review",
    "licensed_media_ready_for_editor_replacement",
}


def fail(message: str) -> None:
    print(f"Phase 4 licensed media ingest validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> Any:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


def validate_workflow_licensed_ingest_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("final/licensed_media_ingest_manifest.json" in workflow.outputs, "workflow must export licensed media ingest manifest")

    for platform in VIDEO_PLATFORMS:
        ingest_step_id = f"{platform}_licensed_media_ingest"
        material_step_id = f"{platform}_asset_materialization"
        edit_step_id = f"{platform}_edit_project"
        ingest_step = steps.get(ingest_step_id)
        edit_step = steps.get(edit_step_id)

        expect(ingest_step is not None, f"workflow missing step: {ingest_step_id}")
        expect(ingest_step.agent == "licensed-media-ingest-agent", f"{ingest_step_id} must use licensed-media-ingest-agent")
        expect(ingest_step.platform == platform, f"{ingest_step_id} platform mismatch")
        expect(material_step_id in ingest_step.depends_on, f"{ingest_step_id} must depend on {material_step_id}")
        expect(
            f"assets/{platform}/licensed_media/ingest_manifest.json" in ingest_step.outputs,
            f"{ingest_step_id} missing ingest manifest output",
        )
        expect(
            f"assets/{platform}/licensed_media/README.md" in ingest_step.outputs,
            f"{ingest_step_id} missing licensed media README output",
        )
        expect(
            f"assets/{platform}/licensed_media/review_handoff.md" in ingest_step.outputs,
            f"{ingest_step_id} missing review handoff output",
        )
        expect(edit_step is not None, f"workflow missing edit step for {platform}")
        expect(ingest_step_id in edit_step.depends_on, f"{edit_step_id} must depend on licensed media ingest")
        expect(ingest_step_id in fact_check.depends_on, f"fact_check must depend on {ingest_step_id}")


def validate_licensed_ingest_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 授权素材接收与审核交接验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/licensed_media_ingest_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing licensed media ingest manifest",
        )

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        video_package = load_json(run_dir / "final/video_production_package.json")
        final_ingest_manifest = load_json(run_dir / "final/licensed_media_ingest_manifest.json")

        expect(
            content_package.get("licensed_media_ingest_manifest") == "final/licensed_media_ingest_manifest.json",
            "content package must reference licensed media ingest manifest",
        )
        expect(
            video_package.get("licensed_media_ingest_manifest") == "final/licensed_media_ingest_manifest.json",
            "video package must reference licensed media ingest manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("licensed_media_ingest")
            == "review_handoff_only_pending_human_supplied_media",
            "video package must mark licensed media ingest as review handoff only",
        )
        expect(
            video_package.get("export_boundary", {}).get("asset_download") == "not_performed",
            "video package must not download media",
        )
        expect(
            video_package.get("export_boundary", {}).get("external_asset_search") == "not_performed",
            "video package must not search external assets",
        )

        expect(
            final_ingest_manifest.get("schema_version") == "phase4.licensed_media_ingest_bundle_manifest.v1",
            "final licensed ingest manifest schema mismatch",
        )
        expect(
            final_ingest_manifest.get("artifact_type") == "licensed_media_ingest_bundle",
            "final licensed ingest manifest type mismatch",
        )
        expect(final_ingest_manifest.get("platforms") == VIDEO_PLATFORMS, "final licensed ingest platforms mismatch")
        expect(final_ingest_manifest.get("validation", {}).get("status") == "PASSED", "final licensed ingest validation must pass")
        expect(final_ingest_manifest.get("validation", {}).get("intake_complete") is False, "final licensed ingest intake must remain incomplete")
        expect(
            final_ingest_manifest.get("validation", {}).get("pending_human_media_count", 0) >= 1,
            "final licensed ingest must keep pending human media",
        )
        expect(
            final_ingest_manifest.get("validation", {}).get("licensed_final_media_required") is True,
            "final licensed ingest must require final licensed media",
        )
        boundary = final_ingest_manifest.get("export_boundary", {})
        expect(
            boundary.get("licensed_media_ingest") == "review_handoff_only_pending_human_supplied_media",
            "final licensed ingest boundary mismatch",
        )
        expect(boundary.get("editing_software") == "not_opened", "final licensed ingest must not open editing software")
        for key in ["asset_download", "external_asset_search", "upload", "publishing"]:
            expect(boundary.get(key) == "not_performed", f"final licensed ingest must mark {key} as not_performed")

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_platform_ingests = {
            item.get("platform"): item
            for item in final_ingest_manifest.get("platform_ingests", [])
            if isinstance(item, dict)
        }

        for platform in VIDEO_PLATFORMS:
            _validate_platform_ingest(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                logs_by_step=logs_by_step,
                package=packages.get(platform),
                final_entry=final_platform_ingests.get(platform),
            )


def _validate_platform_ingest(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    logs_by_step: dict[str | None, Any],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_licensed_media_ingest"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
    log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
    expect(log_metadata.get("licensed_media_ingest_status") == "PASSED", f"{step_id} ingest status must pass")
    expect(log_metadata.get("intake_complete") is False, f"{step_id} intake must remain incomplete without human registry")
    expect(log_metadata.get("pending_human_media_count", 0) >= 1, f"{step_id} must keep pending human media")

    manifest_path = run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json"
    readme_path = run_dir / "assets" / platform / "licensed_media" / "README.md"
    handoff_path = run_dir / "assets" / platform / "licensed_media" / "review_handoff.md"
    manifest = load_json(manifest_path)
    expect(readme_path.exists(), f"{platform} licensed media README missing")
    expect(handoff_path.exists(), f"{platform} licensed media review handoff missing")

    expect(manifest.get("schema_version") == "phase4.licensed_media_ingest_manifest.v1", f"{platform} ingest schema mismatch")
    expect(manifest.get("artifact_type") == "licensed_media_ingest", f"{platform} ingest artifact type mismatch")
    expect(manifest.get("adapter") == "local-licensed-media-ingest-adapter", f"{platform} ingest adapter mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} ingest validation must pass")
    expect(manifest.get("validation", {}).get("all_materialized_assets_covered") is True, f"{platform} ingest must cover all materialized assets")
    expect(manifest.get("validation", {}).get("intake_complete") is False, f"{platform} ingest must remain incomplete")
    expect(manifest.get("validation", {}).get("licensed_final_media_required") is True, f"{platform} ingest must require final licensed media")
    expect(manifest.get("human_media_registry_exists") is False, f"{platform} temp run should not have human media registry")
    ingest_boundary = manifest.get("export_boundary", {})
    expect(
        ingest_boundary.get("licensed_media_ingest") == "review_handoff_only_pending_human_supplied_media",
        f"{platform} ingest boundary mismatch",
    )
    expect(ingest_boundary.get("editing_software") == "not_opened", f"{platform} ingest must not open editing software")
    for key in ["asset_download", "external_asset_search", "upload", "publishing"]:
        expect(ingest_boundary.get(key) == "not_performed", f"{platform} ingest boundary must mark {key} as not_performed")

    licensed_media = manifest.get("licensed_media", [])
    expect(isinstance(licensed_media, list) and licensed_media, f"{platform} ingest must list licensed media slots")
    summary = manifest.get("summary", {})
    expect(summary.get("required_final_media_count") == len(licensed_media), f"{platform} required final media count mismatch")
    expect(summary.get("pending_human_media_count") == len(licensed_media), f"{platform} pending human media count mismatch")
    expect(summary.get("candidate_media_count") == 0, f"{platform} should have no candidate media without registry")
    expect(summary.get("ready_for_editor_replacement_count") == 0, f"{platform} should have no ready media without registry")
    reference_paths: set[str] = set()
    for item in licensed_media:
        expect(item.get("asset_type") == "licensed_broll_media", f"{platform} licensed media asset type mismatch")
        expect(item.get("source_reference_asset_type") == "broll_reference", f"{platform} licensed media source reference type mismatch")
        reference_path = item.get("reference_path")
        expect(isinstance(reference_path, str) and (run_dir / reference_path).exists(), f"{platform} licensed media missing reference path")
        reference_paths.add(reference_path)
        expect(item.get("licensed_media_path") is None, f"{platform} should not invent licensed media path")
        expect(item.get("license_proof_path") is None, f"{platform} should not invent license proof path")
        expect(item.get("media_exists") is False, f"{platform} licensed media should be pending")
        expect(item.get("intake_status") == "pending_human_media", f"{platform} intake status mismatch")
        expect(item.get("ready_for_editor_replacement") is False, f"{platform} media should not be editor-ready")
        expect(item.get("review_status") == "awaiting_human_review", f"{platform} review status mismatch")
        expect(item.get("rights_confirmation") == "unconfirmed", f"{platform} rights confirmation mismatch")
        expect(item.get("licensed_final_media_required") is True, f"{platform} item must require final licensed media")
        expect(item.get("manual_review_required") is True, f"{platform} item must require manual review")
        actions = item.get("required_human_actions", [])
        expect(isinstance(actions, list) and len(actions) >= 3, f"{platform} item must list required human actions")

    readme = readme_path.read_text(encoding="utf-8")
    handoff = handoff_path.read_text(encoding="utf-8")
    expect("does not search, download, license, upload, publish, or open editing software" in readme, f"{platform} README missing boundary")
    expect("human_media_registry.json" in readme, f"{platform} README missing registry instructions")
    expect("Licensed Media Review Handoff" in handoff, f"{platform} handoff missing title")
    expect("Required actions" in handoff, f"{platform} handoff missing required actions")

    edit_timeline = load_json(run_dir / "assets" / platform / "edit" / "edit_timeline.json")
    placeholders = [
        clip.get("broll_placeholder")
        for clip in edit_timeline.get("tracks", {}).get("video", [])
        if isinstance(clip, dict) and isinstance(clip.get("broll_placeholder"), dict)
    ]
    expect(len(placeholders) >= len(licensed_media), f"{platform} edit timeline must preserve licensed media placeholders")
    for placeholder in placeholders[: len(licensed_media)]:
        expect(placeholder.get("reference_path") in reference_paths, f"{platform} placeholder missing reference path")
        expect(
            placeholder.get("licensed_media_ingest_manifest_path") == f"assets/{platform}/licensed_media/ingest_manifest.json",
            f"{platform} placeholder missing ingest manifest path",
        )
        expect(
            placeholder.get("licensed_media_review_handoff_path") == f"assets/{platform}/licensed_media/review_handoff.md",
            f"{platform} placeholder missing review handoff path",
        )
        expect(placeholder.get("licensed_media_intake_status") == "pending_human_media", f"{platform} placeholder intake mismatch")
        expect(placeholder.get("licensed_media_review_status") == "awaiting_human_review", f"{platform} placeholder review mismatch")
        expect(placeholder.get("ready_for_editor_replacement") is False, f"{platform} placeholder should not be ready")
        expect(placeholder.get("licensed_final_media_required") is True, f"{platform} placeholder must require final media")

    offline_report = load_json(run_dir / "assets" / platform / "edit" / "offline_media_report.json")
    slots = offline_report.get("offline_broll_slots", [])
    expect(isinstance(slots, list) and len(slots) >= len(licensed_media), f"{platform} offline report must preserve B-roll slots")
    for slot in slots[: len(licensed_media)]:
        expect(slot.get("reference_path") in reference_paths, f"{platform} offline slot missing reference path")
        expect(slot.get("status") in EXPECTED_OFFLINE_STATUSES, f"{platform} offline slot status mismatch")
        expect(slot.get("licensed_media_ingest_manifest_path") == f"assets/{platform}/licensed_media/ingest_manifest.json", f"{platform} offline slot missing ingest path")
        expect(slot.get("licensed_media_review_handoff_path") == f"assets/{platform}/licensed_media/review_handoff.md", f"{platform} offline slot missing handoff path")
        expect(slot.get("licensed_media_intake_status") == "pending_human_media", f"{platform} offline slot intake mismatch")
        expect(slot.get("licensed_final_media_required") is True, f"{platform} offline slot must require final media")

    bundle_path = run_dir / "assets" / platform / "bundle" / "project_bundle.zip"
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in [
        "licensed_media/ingest_manifest.json",
        "licensed_media/README.md",
        "licensed_media/review_handoff.md",
    ]:
        expect(archive_path in archive_paths, f"{platform} bundle missing licensed media file: {archive_path}")

    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    expect(deliverables.get("licensed_media_ingest_manifest") == f"assets/{platform}/licensed_media/ingest_manifest.json", f"{platform} package missing ingest manifest")
    expect(deliverables.get("licensed_media_ingest_readme") == f"assets/{platform}/licensed_media/README.md", f"{platform} package missing ingest README")
    expect(deliverables.get("licensed_media_review_handoff") == f"assets/{platform}/licensed_media/review_handoff.md", f"{platform} package missing review handoff")
    ingest_summary = package.get("licensed_media_ingest", {})
    expect(ingest_summary.get("validation_status") == "PASSED", f"{platform} package ingest summary must pass")
    expect(ingest_summary.get("required_final_media_count") == len(licensed_media), f"{platform} package required count mismatch")
    expect(ingest_summary.get("pending_human_media_count") == len(licensed_media), f"{platform} package pending count mismatch")
    expect(ingest_summary.get("candidate_media_count") == 0, f"{platform} package candidate count mismatch")
    expect(ingest_summary.get("ready_for_editor_replacement_count") == 0, f"{platform} package ready count mismatch")
    expect(ingest_summary.get("intake_complete") is False, f"{platform} package intake must remain incomplete")
    expect(ingest_summary.get("licensed_final_media_required") is True, f"{platform} package must require licensed media")
    expect(set(ingest_summary.get("pending_asset_ids", [])) == {str(item["asset_id"]) for item in licensed_media}, f"{platform} package pending asset ids mismatch")

    expect(isinstance(final_entry, dict), f"final licensed ingest manifest missing platform: {platform}")
    expect(final_entry.get("manifest_path") == f"assets/{platform}/licensed_media/ingest_manifest.json", f"{platform} final ingest path mismatch")
    expect(final_entry.get("readme_path") == f"assets/{platform}/licensed_media/README.md", f"{platform} final README path mismatch")
    expect(final_entry.get("review_handoff_path") == f"assets/{platform}/licensed_media/review_handoff.md", f"{platform} final handoff path mismatch")
    expect(final_entry.get("required_final_media_count") == len(licensed_media), f"{platform} final required count mismatch")
    expect(final_entry.get("pending_human_media_count") == len(licensed_media), f"{platform} final pending count mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final validation must pass")
    expect(final_entry.get("validation", {}).get("intake_complete") is False, f"{platform} final intake must remain incomplete")


def main() -> int:
    validate_workflow_licensed_ingest_steps()
    print("Phase 4 licensed media ingest drill passed: workflow ingest steps")
    validate_licensed_ingest_run()
    print("Phase 4 licensed media ingest drill passed: manifests, review handoff, edit/export/bundle/package embedding")
    print("Phase 4 licensed media ingest validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
