from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.agents import AgentExecutionContext, run_agent  # noqa: E402
from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
BLOCKED_BOUNDARY = "blocked_pending_human_real_run_result"
INGESTED_BOUNDARY = "human_evidence_ingested_no_automation_execution"
EVIDENCE_FILES = {
    "manifest": "real_run_evidence_manifest.json",
    "validation": "evidence_validation_report.json",
    "rollback": "rollback_decision_report.json",
    "checklist": "post_launch_evidence_checklist.md",
    "readme": "README.md",
}


def fail(message: str) -> None:
    print(f"Phase 4 editor software run evidence validation failed: {message}", file=sys.stderr)
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_agent_outputs(run_dir: Path, outputs: dict[str, Any]) -> None:
    for relative_path, content in outputs.items():
        destination = run_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        elif isinstance(content, (dict, list)):
            write_json(destination, content)
        else:
            destination.write_text(str(content), encoding="utf-8")


def stable_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_workflow_evidence_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect(
        "final/editor_software_run_evidence_manifest.json" in workflow.outputs,
        "workflow must export editor software run evidence manifest",
    )

    for platform in VIDEO_PLATFORMS:
        runner_step_id = f"{platform}_editor_software_real_runner_sandbox"
        evidence_step_id = f"{platform}_editor_software_run_evidence"
        bundle_step_id = f"{platform}_project_bundle"
        evidence_step = steps.get(evidence_step_id)
        bundle_step = steps.get(bundle_step_id)
        expect(evidence_step is not None, f"workflow missing step: {evidence_step_id}")
        expect(
            evidence_step.agent == "editor-software-run-evidence-agent",
            f"{evidence_step_id} must use editor-software-run-evidence-agent",
        )
        expect(evidence_step.platform == platform, f"{evidence_step_id} platform mismatch")
        expect(runner_step_id in evidence_step.depends_on, f"{evidence_step_id} must depend on real runner sandbox")
        for filename in EVIDENCE_FILES.values():
            output_path = f"assets/{platform}/edit/software_run_evidence/{filename}"
            expect(output_path in evidence_step.outputs, f"{evidence_step_id} missing output: {output_path}")
        expect(bundle_step is not None, f"workflow missing bundle step for {platform}")
        expect(evidence_step_id in bundle_step.depends_on, f"{bundle_step_id} must depend on run evidence")
        expect(evidence_step_id in fact_check.depends_on, f"fact_check must depend on {evidence_step_id}")


def validate_boundary(boundary: dict[str, Any], label: str, expected_boundary: str) -> None:
    expect(boundary.get("editor_software_run_evidence") == expected_boundary, f"{label} evidence boundary mismatch")
    expect(boundary.get("real_software_launch_by_automation") == "not_performed", f"{label} must not launch software")
    expect(boundary.get("software_import_execution_by_automation") == "not_performed", f"{label} must not import")
    expect(boundary.get("editing_software") == "not_opened_by_automation", f"{label} must not open editor")
    expect(boundary.get("project_file_mutation") == "not_performed_by_evidence_ingest", f"{label} mutation boundary mismatch")
    expect(boundary.get("original_project_mutation") == "not_performed", f"{label} must not mutate original project")
    expect(boundary.get("replacement_execution_by_automation") == "not_performed", f"{label} must not execute replacement")
    expect(boundary.get("process_spawn") == "not_performed", f"{label} must not spawn process")
    expect(boundary.get("evidence_ingest_only") is True, f"{label} must be ingest-only")
    expect(boundary.get("requires_human_real_run_result") is True, f"{label} must require human real-run result")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} must mark {key} as not_performed")


def validate_platform_evidence_manifest(
    manifest: dict[str, Any],
    *,
    platform: str,
    expected_boundary: str,
    result_present: bool,
) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_software_run_evidence_manifest.v1",
        f"{platform} evidence manifest schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_software_run_evidence", f"{platform} evidence type mismatch")
    expect(manifest.get("adapter") == "local-editor-software-run-evidence-adapter", f"{platform} adapter mismatch")
    expect(manifest.get("platform") == platform, f"{platform} platform mismatch")
    expect(manifest.get("manual_review_required") is True, f"{platform} evidence manifest must require review")
    expect(manifest.get("human_real_run_result_required") is True, f"{platform} evidence must require human result")
    expect(manifest.get("human_real_run_result_present") is result_present, f"{platform} human result presence mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} evidence validation must pass")
    validate_boundary(manifest.get("export_boundary", {}), platform, expected_boundary)
    for key in [
        "real_software_launch_performed_by_automation",
        "software_import_execution_performed_by_automation",
        "editing_software_opened_by_automation",
        "project_file_mutation_performed_by_automation",
        "process_spawned_by_automation",
        "upload_performed",
        "publishing_performed",
    ]:
        expect(manifest.get("validation", {}).get(key) is False, f"{platform} evidence must report {key}=false")
    items = manifest.get("evidence_items", [])
    expect(isinstance(items, list) and items, f"{platform} evidence items must be non-empty")
    expect(manifest.get("summary", {}).get("evidence_item_count") == len(items), f"{platform} evidence item count mismatch")
    for item in items:
        expect(isinstance(item, dict), f"{platform} evidence item must be an object")
        for key in [
            "real_software_launch_performed_by_automation",
            "software_import_execution_performed_by_automation",
            "editing_software_opened_by_automation",
            "project_file_mutation_performed_by_automation",
            "process_spawned_by_automation",
            "upload_performed",
            "publishing_performed",
        ]:
            expect(item.get(key) is False, f"{platform} evidence item must report {key}=false")


def validate_platform_evidence_files(run_dir: Path, platform: str, expected_boundary: str, result_present: bool) -> dict[str, Any]:
    base = run_dir / "assets" / platform / "edit" / "software_run_evidence"
    paths = {name: base / filename for name, filename in EVIDENCE_FILES.items()}
    for name, path in paths.items():
        expect(path.exists(), f"{platform} evidence artifact missing: {name}")
    manifest = load_json(paths["manifest"])
    validation_report = load_json(paths["validation"])
    rollback_report = load_json(paths["rollback"])
    checklist = paths["checklist"].read_text(encoding="utf-8")
    readme = paths["readme"].read_text(encoding="utf-8")
    validate_platform_evidence_manifest(
        manifest,
        platform=platform,
        expected_boundary=expected_boundary,
        result_present=result_present,
    )
    expect(
        validation_report.get("schema_version") == "phase4.editor_software_run_evidence_validation_report.v1",
        f"{platform} validation report schema mismatch",
    )
    expect(
        rollback_report.get("schema_version") == "phase4.editor_software_run_evidence_rollback_decision_report.v1",
        f"{platform} rollback report schema mismatch",
    )
    validate_boundary(validation_report.get("export_boundary", {}), f"{platform} validation report", expected_boundary)
    validate_boundary(rollback_report.get("export_boundary", {}), f"{platform} rollback report", expected_boundary)
    expect("Post-Launch Evidence Checklist" in checklist, f"{platform} checklist missing heading")
    expect("Automation process spawn: not performed" in checklist, f"{platform} checklist missing no-spawn boundary")
    expect("Editor Software Run Evidence" in readme, f"{platform} evidence README missing heading")
    expect("does not launch editing software" in readme, f"{platform} evidence README missing no-launch boundary")
    return manifest


def validate_final_manifest(manifest: dict[str, Any], expected_boundary: str) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_software_run_evidence_bundle_manifest.v1",
        "final evidence manifest schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_software_run_evidence_bundle", "final evidence type mismatch")
    expect(manifest.get("manifest_path") == "final/editor_software_run_evidence_manifest.json", "final evidence path mismatch")
    validate_boundary(manifest.get("export_boundary", {}), "final evidence manifest", expected_boundary)
    validation = manifest.get("validation", {})
    expect(validation.get("status") == "PASSED", "final evidence validation must pass")
    expect(validation.get("platform_count") == len(VIDEO_PLATFORMS), "final evidence platform count mismatch")
    expect(validation.get("real_software_launch_performed_by_automation") is False, "final evidence must not launch software")
    expect(validation.get("process_spawned_by_automation") is False, "final evidence must not spawn process")


def with_zip_paths(bundle_path: Path, platform: str, expected_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} bundle ZIP is invalid: {exc}")
    for expected_path in expected_paths:
        expect(expected_path in archive_paths, f"{platform} bundle missing {expected_path}")


def validate_default_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 真实软件外部运行证据默认阻断验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/editor_software_run_evidence_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor software run evidence manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/editor_software_run_evidence_manifest.json")
        expect(
            video_package.get("editor_software_run_evidence_manifest")
            == "final/editor_software_run_evidence_manifest.json",
            "video package must reference editor software run evidence manifest",
        )
        expect(
            content_package.get("editor_software_run_evidence_manifest")
            == "final/editor_software_run_evidence_manifest.json",
            "content package must reference editor software run evidence manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("editor_software_run_evidence") == BLOCKED_BOUNDARY,
            "video package evidence boundary mismatch",
        )
        validate_final_manifest(final_manifest, BLOCKED_BOUNDARY)

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_manifest.get("platform_evidence", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_editor_software_run_evidence"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(metadata.get("editor_software_run_evidence_status") == "PASSED", f"{step_id} status must pass")
            expect(metadata.get("human_real_run_result_required") is True, f"{step_id} must require human result")
            expect(metadata.get("human_real_run_result_present") is False, f"{step_id} default run must not have result")
            expect(metadata.get("process_spawned_by_automation") is False, f"{step_id} must not spawn process")
            expect(metadata.get("editing_software_opened_by_automation") is False, f"{step_id} must not open editor")
            manifest = validate_platform_evidence_files(run_dir, platform, BLOCKED_BOUNDARY, result_present=False)
            expect(
                manifest.get("summary", {}).get("human_real_run_evidence_ingested_count") == 0,
                f"{platform} default evidence should not be ingested",
            )
            expect(
                manifest.get("summary", {}).get("blocked_evidence_count", 0) >= 1,
                f"{platform} default evidence should block items",
            )
            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            summary = package.get("editor_software_run_evidence", {})
            expect(summary.get("editor_software_run_evidence") == BLOCKED_BOUNDARY, f"{platform} package evidence boundary mismatch")
            expect(summary.get("validation_status") == "PASSED", f"{platform} package evidence summary must pass")
            deliverables = package.get("deliverables", {})
            for key, expected_path in {
                "editor_software_run_evidence_manifest": f"assets/{platform}/edit/software_run_evidence/real_run_evidence_manifest.json",
                "editor_software_run_evidence_validation_report": f"assets/{platform}/edit/software_run_evidence/evidence_validation_report.json",
                "editor_software_run_evidence_rollback_decision_report": f"assets/{platform}/edit/software_run_evidence/rollback_decision_report.json",
                "editor_software_run_evidence_checklist": f"assets/{platform}/edit/software_run_evidence/post_launch_evidence_checklist.md",
                "editor_software_run_evidence_readme": f"assets/{platform}/edit/software_run_evidence/README.md",
            }.items():
                expect(deliverables.get(key) == expected_path, f"{platform} package deliverable mismatch: {key}")
                expect((run_dir / expected_path).exists(), f"{platform} package deliverable missing: {expected_path}")
            final_entry = final_entries.get(platform)
            expect(isinstance(final_entry, dict), f"final evidence manifest missing platform: {platform}")
            expect(final_entry.get("manifest_path") == deliverables.get("editor_software_run_evidence_manifest"), f"{platform} final evidence manifest path mismatch")
            with_zip_paths(
                run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
                platform,
                [
                    "software_run_evidence/real_run_evidence_manifest.json",
                    "software_run_evidence/evidence_validation_report.json",
                    "software_run_evidence/rollback_decision_report.json",
                    "software_run_evidence/post_launch_evidence_checklist.md",
                    "software_run_evidence/README.md",
                ],
            )


def first_materialized_asset_id(run_dir: Path, platform: str) -> str:
    manifest = load_json(run_dir / "assets" / platform / "materials" / "material_manifest.json")
    for asset in manifest.get("materialized_assets", []):
        if isinstance(asset, dict) and asset.get("asset_id"):
            return str(asset["asset_id"])
    fail(f"{platform} has no materialized asset id")
    raise AssertionError("unreachable")


def validate_human_result_path() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 人工真实运行证据接收验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )
        platform = "douyin"
        asset_id = first_materialized_asset_id(run_dir, platform)
        source_media_path = f"assets/{platform}/licensed_media/human_supplied/{asset_id}_final.txt"
        source_media = run_dir / source_media_path
        source_media.parent.mkdir(parents=True, exist_ok=True)
        source_media.write_text(f"self-created run evidence fixture for {asset_id}\n", encoding="utf-8")
        write_json(
            run_dir / "assets" / platform / "licensed_media" / "human_media_registry.json",
            {
                "media": [
                    {
                        "asset_id": asset_id,
                        "licensed_media_path": source_media_path,
                        "license_source": "self_created_local_test_fixture",
                        "rights_owner": "human",
                        "usage_scope": "test_only",
                        "reviewer": "human",
                        "review_status": "approved_for_edit",
                        "rights_confirmation": "self_created_confirmed",
                    }
                ]
            },
        )

        ctx = AgentExecutionContext(
            run_dir=run_dir,
            topic="Phase 4 人工真实运行证据接收验收",
            platforms=VIDEO_PLATFORMS,
            produced_artifacts=[],
        )
        for agent_id in [
            "licensed-media-ingest-agent",
            "licensed-media-proxy-agent",
            "edit-project-agent",
            "export-project-agent",
            "editor-replacement-instructions-agent",
        ]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        write_json(
            run_dir / "assets" / platform / "edit" / "replacement_execution" / "human_execution_approval.json",
            {
                "approval_status": "approved_for_execution",
                "human_execution_approval": True,
                "approved_asset_ids": [asset_id],
                "approved_by": "human",
                "approval_note": "Test approval: reviewed rights, timing, and manual execution scope.",
            },
        )
        result = run_agent({"agent": "editor-replacement-execution-agent", "metadata": {"platform": platform}}, ctx)
        write_agent_outputs(run_dir, result.outputs)

        write_json(
            run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "human_mutation_approval.json",
            {
                "approval_status": "approved_for_project_mutation_sandbox",
                "human_mutation_approval": True,
                "approved_asset_ids": [asset_id],
                "approved_by": "human",
                "approval_note": "Test approval: reviewed execution plan and allow sandbox patched project generation.",
            },
        )
        result = run_agent({"agent": "editor-project-mutation-sandbox-agent", "metadata": {"platform": platform}}, ctx)
        write_agent_outputs(run_dir, result.outputs)

        patched_project = (
            run_dir / "assets" / platform / "edit" / "mutation_sandbox" / "patched_project.fcpxml"
        ).read_text(encoding="utf-8")
        write_json(
            run_dir
            / "assets"
            / platform
            / "edit"
            / "software_import_executor"
            / "human_software_import_approval.json",
            {
                "approval_status": "approved_for_editor_software_import",
                "human_software_import_approval": True,
                "approved_patched_project_sha256": sha256_text(patched_project),
                "approved_by": "human",
                "approval_note": "Test approval: reviewed sandbox patched project and isolated editor environment.",
            },
        )
        result = run_agent({"agent": "editor-software-import-executor-agent", "metadata": {"platform": platform}}, ctx)
        write_agent_outputs(run_dir, result.outputs)

        write_json(
            run_dir
            / "assets"
            / platform
            / "edit"
            / "software_real_runner_sandbox"
            / "human_real_run_approval.json",
            {
                "approval_status": "approved_for_editor_software_real_runner_sandbox",
                "human_real_run_approval": True,
                "approved_patched_project_sha256": sha256_text(patched_project),
                "approved_by": "human",
                "approval_note": "Test approval: reviewed external sandbox launch plan and evidence capture requirements.",
            },
        )
        result = run_agent({"agent": "editor-software-real-runner-sandbox-agent", "metadata": {"platform": platform}}, ctx)
        write_agent_outputs(run_dir, result.outputs)

        runner_manifest = load_json(
            run_dir / "assets" / platform / "edit" / "software_real_runner_sandbox" / "runner_sandbox_manifest.json"
        )
        evidence_dir = run_dir / "assets" / platform / "edit" / "software_run_evidence"
        evidence_file_path = f"assets/{platform}/edit/software_run_evidence/manual_export_log.txt"
        (run_dir / evidence_file_path).write_text("human captured external sandbox export log\n", encoding="utf-8")
        write_json(
            evidence_dir / "human_real_run_result.json",
            {
                "result_status": "human_real_run_completed",
                "human_real_run_completed": True,
                "completed_by": "human",
                "approved_runner_manifest_sha256": stable_sha256(runner_manifest),
                "evidence_files": [evidence_file_path],
                "rollback_required": False,
                "rollback_reason": "",
                "outcome_note": "External sandbox launch completed by a human; automation only ingests evidence.",
            },
        )
        for agent_id in ["editor-software-run-evidence-agent", "project-bundle-agent"]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        manifest = validate_platform_evidence_files(run_dir, platform, INGESTED_BOUNDARY, result_present=True)
        expect(manifest.get("human_real_run_result_valid") is True, "human result should be valid")
        expect(
            manifest.get("summary", {}).get("human_real_run_evidence_ingested_count", 0) >= 1,
            "human result should ingest at least one evidence item",
        )
        expect(manifest.get("summary", {}).get("existing_evidence_file_count") == 1, "human evidence file should exist")
        expect(manifest.get("rollback_decision") == "no_rollback_requested_pending_final_human_closeout", "rollback decision mismatch")
        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "software_run_evidence/real_run_evidence_manifest.json",
                "software_run_evidence/evidence_validation_report.json",
                "software_run_evidence/rollback_decision_report.json",
                "software_run_evidence/post_launch_evidence_checklist.md",
                "software_run_evidence/human_real_run_result.json",
                "software_run_evidence/README.md",
            ],
        )


def main() -> int:
    validate_workflow_evidence_steps()
    print("Phase 4 editor software run evidence drill passed: workflow evidence steps")
    validate_default_run()
    print("Phase 4 editor software run evidence drill passed: default blocked evidence ingest package")
    validate_human_result_path()
    print("Phase 4 editor software run evidence drill passed: human result ingest without automation execution")
    print("Phase 4 editor software run evidence validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
