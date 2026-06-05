from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
EXPECTED_REFERENCES = {
    "douyin": [
        "workflow_board_reference.png",
        "task_ledger_closeup_reference.png",
        "vertical_caption_overlay_reference.png",
    ],
    "shipinhao": [
        "workflow_board_reference.png",
        "task_ledger_closeup_reference.png",
        "vertical_caption_overlay_reference.png",
    ],
    "bilibili": [
        "workflow_board_reference.png",
        "task_ledger_closeup_reference.png",
        "chapter_timeline_reference.png",
    ],
}
EXPECTED_OFFLINE_STATUSES = {
    "reference_generated_pending_licensed_media",
    "pending_human_licensed_media",
    "licensed_media_candidate_pending_review",
    "licensed_media_ready_for_editor_replacement",
    "proxy_ready_for_editor_replacement",
}


def fail(message: str) -> None:
    print(f"Phase 4 asset materialization validation failed: {message}", file=sys.stderr)
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


def validate_workflow_materialization_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("final/materialization_manifest.json" in workflow.outputs, "workflow must export final materialization manifest")
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_asset_materialization"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "asset-materialization-agent", f"{step_id} must use asset-materialization-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect("visual_assets" in step.depends_on, f"{step_id} must depend on visual_assets")
        expect(f"{platform}_video" in step.depends_on, f"{step_id} must depend on {platform}_video")
        expect(f"assets/{platform}/materials/material_manifest.json" in step.outputs, f"{step_id} missing manifest output")
        expect(f"assets/{platform}/materials/README.md" in step.outputs, f"{step_id} missing README output")
        for filename in EXPECTED_REFERENCES[platform]:
            expect(f"assets/{platform}/materials/{filename}" in step.outputs, f"{step_id} missing reference output: {filename}")
        edit_step = steps.get(f"{platform}_edit_project")
        expect(edit_step is not None, f"workflow missing edit step for {platform}")
        expect(step_id in edit_step.depends_on, f"{platform} edit project must depend on materialization")
        expect(step_id in fact_check.depends_on, f"fact_check must depend on {step_id}")


def validate_materialization_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 本地素材实物化验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/materialization_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final materialization manifest",
        )

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/materialization_manifest.json")
        expect(
            content_package.get("materialization_manifest") == "final/materialization_manifest.json",
            "content package must reference final materialization manifest",
        )
        expect(
            video_package.get("materialization_manifest") == "final/materialization_manifest.json",
            "video package must reference final materialization manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("asset_materialization")
            == "performed_locally_reference_only",
            "video package must mark asset materialization as local reference only",
        )
        expect(
            video_package.get("export_boundary", {}).get("external_asset_search") == "not_performed",
            "video package must mark external asset search as not performed",
        )
        expect(final_manifest.get("schema_version") == "phase4.materialization_bundle_manifest.v1", "final materialization schema mismatch")
        expect(final_manifest.get("artifact_type") == "materialization_bundle", "final materialization type mismatch")
        expect(final_manifest.get("validation", {}).get("status") == "PASSED", "final materialization validation must pass")
        expect(
            final_manifest.get("export_boundary", {}).get("asset_download") == "not_performed",
            "final materialization manifest must not download assets",
        )
        expect(
            final_manifest.get("export_boundary", {}).get("external_asset_search") == "not_performed",
            "final materialization manifest must not search external assets",
        )

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        platform_materials = {
            item.get("platform"): item
            for item in final_manifest.get("platform_materials", [])
            if isinstance(item, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_asset_materialization"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(log_metadata.get("materialization_status") == "PASSED", f"{step_id} materialization status must pass")
            expect(log_metadata.get("licensed_final_media_required") is True, f"{step_id} must keep licensed final media required")

            manifest_path = run_dir / "assets" / platform / "materials" / "material_manifest.json"
            readme_path = run_dir / "assets" / platform / "materials" / "README.md"
            manifest = load_json(manifest_path)
            expect(readme_path.exists(), f"{platform} material README missing")
            expect(manifest.get("schema_version") == "phase4.materialized_assets_manifest.v1", f"{platform} material manifest schema mismatch")
            expect(manifest.get("adapter") == "local-asset-materialization-adapter", f"{platform} material adapter mismatch")
            expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} material validation must pass")
            boundary = manifest.get("export_boundary", {})
            for key in ["asset_download", "external_asset_search", "upload", "publishing"]:
                expect(boundary.get(key) == "not_performed", f"{platform} boundary must mark {key} as not_performed")
            expect(boundary.get("asset_materialization") == "performed_locally_reference_only", f"{platform} materialization boundary mismatch")

            assets = manifest.get("materialized_assets", [])
            expect(isinstance(assets, list) and len(assets) == len(EXPECTED_REFERENCES[platform]), f"{platform} materialized asset count mismatch")
            reference_paths = [str(asset.get("reference_path")) for asset in assets if isinstance(asset, dict)]
            for filename in EXPECTED_REFERENCES[platform]:
                expected_path = f"assets/{platform}/materials/{filename}"
                expect(expected_path in reference_paths, f"{platform} missing reference path: {expected_path}")
                _expect_png(run_dir / expected_path, platform)
            for asset in assets:
                expect(asset.get("asset_type") == "broll_reference", f"{platform} material asset_type mismatch")
                expect(asset.get("source_task_asset_type") == "broll", f"{platform} source asset type mismatch")
                expect(asset.get("generation_status") == "generated_reference_pending_review", f"{platform} generation status mismatch")
                expect(asset.get("rights_status") == "self_created_reference_pending_human_review", f"{platform} rights status mismatch")
                expect(asset.get("licensed_final_media_required") is True, f"{platform} must keep licensed final media required")
                planned_target = asset.get("planned_target_path")
                if isinstance(planned_target, str) and planned_target:
                    expect(not (run_dir / planned_target).exists(), f"{platform} planned B-roll MP4 must not be generated: {planned_target}")

            readme = readme_path.read_text(encoding="utf-8")
            expect("reference only" in readme, f"{platform} material README must state reference-only boundary")
            expect("No external asset search" in readme, f"{platform} material README must state no external search")

            edit_timeline = load_json(run_dir / "assets" / platform / "edit" / "edit_timeline.json")
            video_clips = edit_timeline.get("tracks", {}).get("video", [])
            broll_placeholders = [
                clip.get("broll_placeholder")
                for clip in video_clips
                if isinstance(clip, dict) and isinstance(clip.get("broll_placeholder"), dict)
            ]
            expect(len(broll_placeholders) >= len(assets), f"{platform} edit timeline must preserve B-roll placeholders")
            for placeholder in broll_placeholders[: len(assets)]:
                reference_path = placeholder.get("reference_path")
                expect(isinstance(reference_path, str) and reference_path in reference_paths, f"{platform} placeholder missing material reference")
                expect(placeholder.get("reference_status") == "generated_reference_pending_review", f"{platform} placeholder reference status mismatch")
                expect(placeholder.get("licensed_final_media_required") is True, f"{platform} placeholder must require licensed final media")

            offline_report = load_json(run_dir / "assets" / platform / "edit" / "offline_media_report.json")
            slots = offline_report.get("offline_broll_slots", [])
            expect(len(slots) >= len(assets), f"{platform} offline report must preserve B-roll slots")
            for slot in slots[: len(assets)]:
                reference_path = slot.get("reference_path")
                expect(isinstance(reference_path, str) and reference_path in reference_paths, f"{platform} offline slot missing reference path")
                expect(slot.get("status") in EXPECTED_OFFLINE_STATUSES, f"{platform} offline slot status mismatch")
                expect(slot.get("licensed_final_media_required") is True, f"{platform} offline slot must require licensed final media")

            bundle_path = run_dir / "assets" / platform / "bundle" / "project_bundle.zip"
            try:
                with ZipFile(bundle_path) as archive:
                    archive_paths = set(archive.namelist())
            except BadZipFile as exc:
                fail(f"{platform} project bundle ZIP is invalid: {exc}")
            for filename in EXPECTED_REFERENCES[platform]:
                expect(f"materials/{filename}" in archive_paths, f"{platform} bundle missing material reference: {filename}")

            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("material_manifest") == f"assets/{platform}/materials/material_manifest.json", f"{platform} package missing material manifest")
            expect(deliverables.get("material_readme") == f"assets/{platform}/materials/README.md", f"{platform} package missing material README")
            for asset in assets:
                asset_id = str(asset.get("asset_id"))
                expect(
                    deliverables.get(f"material_reference_{asset_id}") == asset.get("reference_path"),
                    f"{platform} package missing material reference deliverable: {asset_id}",
                )
            material_summary = package.get("materialized_assets", {})
            expect(material_summary.get("validation_status") == "PASSED", f"{platform} material summary must pass")
            expect(material_summary.get("materialized_count") == len(assets), f"{platform} material summary count mismatch")
            expect(material_summary.get("licensed_final_media_required") is True, f"{platform} material summary must require final licensed media")

            final_entry = platform_materials.get(platform)
            expect(isinstance(final_entry, dict), f"final materialization manifest missing platform: {platform}")
            expect(final_entry.get("materialized_count") == len(assets), f"{platform} final material count mismatch")
            expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final material validation must pass")


def _expect_png(path: Path, platform: str) -> None:
    expect(path.exists(), f"{platform} reference PNG missing: {path}")
    expect(path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{platform} reference is not a PNG: {path}")
    with Image.open(path) as image:
        width, height = image.size
        expect(width >= 700 and height >= 700, f"{platform} reference PNG is too small: {path}")
        if platform == "bilibili":
            expect(width > height, f"{platform} reference should be horizontal: {path}")
        else:
            expect(height > width, f"{platform} reference should be vertical: {path}")


def main() -> int:
    validate_workflow_materialization_steps()
    print("Phase 4 asset materialization drill passed: workflow materialization steps")
    validate_materialization_run()
    print("Phase 4 asset materialization drill passed: manifests, reference PNGs, edit/export/bundle/package embedding")
    print("Phase 4 asset materialization validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
