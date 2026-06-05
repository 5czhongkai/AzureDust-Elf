from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
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
BLOCKED_BOUNDARY = "blocked_pending_explicit_human_mutation_approval"
APPROVED_BOUNDARY = "sandbox_patch_generated_from_explicit_human_approval"
MUTATION_FILES = {
    "mutation_manifest": "mutation_manifest.json",
    "patched_project": "patched_project.fcpxml",
    "mutation_diff": "mutation_diff.json",
    "rollback_manifest": "rollback_manifest.json",
    "mutation_audit_log": "mutation_audit_log.json",
    "human_final_review_checklist": "human_final_review_checklist.md",
    "readme": "README.md",
}


def fail(message: str) -> None:
    print(f"Phase 4 editor project mutation sandbox validation failed: {message}", file=sys.stderr)
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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_workflow_mutation_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect(
        "final/editor_project_mutation_manifest.json" in workflow.outputs,
        "workflow must export editor project mutation manifest",
    )

    for platform in VIDEO_PLATFORMS:
        execution_step_id = f"{platform}_editor_replacement_execution"
        mutation_step_id = f"{platform}_editor_project_mutation_sandbox"
        bundle_step_id = f"{platform}_project_bundle"
        mutation_step = steps.get(mutation_step_id)
        bundle_step = steps.get(bundle_step_id)

        expect(mutation_step is not None, f"workflow missing step: {mutation_step_id}")
        expect(
            mutation_step.agent == "editor-project-mutation-sandbox-agent",
            f"{mutation_step_id} must use editor-project-mutation-sandbox-agent",
        )
        expect(mutation_step.platform == platform, f"{mutation_step_id} platform mismatch")
        expect(
            execution_step_id in mutation_step.depends_on,
            f"{mutation_step_id} must depend on editor replacement execution",
        )
        for filename in MUTATION_FILES.values():
            output_path = f"assets/{platform}/edit/mutation_sandbox/{filename}"
            expect(output_path in mutation_step.outputs, f"{mutation_step_id} missing output: {output_path}")

        expect(bundle_step is not None, f"workflow missing bundle step for {platform}")
        expect(
            depends_on_transitively(steps, bundle_step_id, mutation_step_id),
            f"{bundle_step_id} must be downstream of mutation sandbox",
        )
        expect(mutation_step_id in fact_check.depends_on, f"fact_check must depend on {mutation_step_id}")


def validate_default_blocked_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 工程改写沙盒默认阻断验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/editor_project_mutation_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor project mutation manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }

        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/editor_project_mutation_manifest.json")

        expect(
            video_package.get("editor_project_mutation_manifest") == "final/editor_project_mutation_manifest.json",
            "video package must reference editor project mutation manifest",
        )
        expect(
            content_package.get("editor_project_mutation_manifest") == "final/editor_project_mutation_manifest.json",
            "content package must reference editor project mutation manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("editor_project_mutation_sandbox") == BLOCKED_BOUNDARY,
            "video package mutation sandbox boundary mismatch",
        )
        validate_final_mutation_manifest(final_manifest, expected_boundary=BLOCKED_BOUNDARY, default_blocked=True)

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_manifest.get("platform_mutations", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            validate_default_platform_mutation(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                logs_by_step=logs_by_step,
                package=packages.get(platform),
                final_entry=final_entries.get(platform),
            )


def validate_default_platform_mutation(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    logs_by_step: dict[str, Any],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_editor_project_mutation_sandbox"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    expect(metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
    expect(metadata.get("editor_project_mutation_status") == "PASSED", f"{step_id} status must pass")
    expect(metadata.get("human_mutation_approval_required") is True, f"{step_id} must require mutation approval")
    expect(metadata.get("human_mutation_approval_present") is False, f"{step_id} default run must not have mutation approval")
    expect(metadata.get("human_mutation_approval_valid") is False, f"{step_id} default approval must be invalid")
    expect(metadata.get("original_project_mutated") is False, f"{step_id} must not mutate original project")
    expect(metadata.get("patched_copy_generated") is True, f"{step_id} must generate patched copy")
    expect(metadata.get("editing_software_opened") is False, f"{step_id} must not open editing software")
    expect(metadata.get("replacement_execution_performed") is False, f"{step_id} must not execute replacement")

    base = run_dir / "assets" / platform / "edit" / "mutation_sandbox"
    manifest = load_json(base / "mutation_manifest.json")
    mutation_diff = load_json(base / "mutation_diff.json")
    rollback_manifest = load_json(base / "rollback_manifest.json")
    audit_log = load_json(base / "mutation_audit_log.json")
    patched_project_path = base / "patched_project.fcpxml"
    final_checklist_path = base / "human_final_review_checklist.md"
    readme_path = base / "README.md"
    for path in [patched_project_path, final_checklist_path, readme_path]:
        expect(path.exists(), f"{platform} mutation sandbox file missing: {path.relative_to(run_dir)}")

    original_project = (run_dir / "assets" / platform / "edit" / "project.fcpxml").read_text(encoding="utf-8")
    patched_project = patched_project_path.read_text(encoding="utf-8")
    expect(sha256_text(original_project) == sha256_text(patched_project), f"{platform} default patched project should equal original")
    validate_fcpxml(patched_project_path, platform)
    validate_platform_mutation_manifest(manifest, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_mutation_diff(mutation_diff, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_rollback_manifest(rollback_manifest, platform=platform, original_sha=sha256_text(original_project))
    validate_audit_log(audit_log, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_mutation_docs(final_checklist_path, readme_path, platform)

    expect(manifest.get("summary", {}).get("mutation_applied_count") == 0, f"{platform} default run must not apply mutation")
    expect(manifest.get("validation", {}).get("patched_project_differs_from_original") is False, f"{platform} default copy should not differ")
    statuses = {item.get("mutation_status") for item in manifest.get("mutation_items", []) if isinstance(item, dict)}
    expect("sandbox_patch_applied" not in statuses, f"{platform} default run must not apply sandbox patch")
    expect(any(str(status).startswith("blocked_") for status in statuses), f"{platform} default run must block mutation items")

    with_zip_paths(
        run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
        platform,
        [
            "mutation_sandbox/mutation_manifest.json",
            "mutation_sandbox/patched_project.fcpxml",
            "mutation_sandbox/mutation_diff.json",
            "mutation_sandbox/rollback_manifest.json",
            "mutation_sandbox/mutation_audit_log.json",
            "mutation_sandbox/human_final_review_checklist.md",
            "mutation_sandbox/README.md",
        ],
    )

    expected_deliverables = expected_platform_deliverables(platform)
    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    for key, expected_path in expected_deliverables.items():
        expect(deliverables.get(key) == expected_path, f"{platform} package deliverable mismatch: {key}")
        expect((run_dir / expected_path).exists(), f"{platform} package deliverable path missing: {expected_path}")

    summary = package.get("editor_project_mutation_sandbox", {})
    validate_platform_package_summary(summary, platform=platform, expected_boundary=BLOCKED_BOUNDARY, default_blocked=True)
    expect(isinstance(final_entry, dict), f"final mutation manifest missing platform: {platform}")
    validate_final_platform_entry(final_entry, expected_deliverables, platform=platform)


def validate_explicit_approval_sandbox_patch_path() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 显式批准工程沙盒改写验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        platform = "douyin"
        asset_id = first_materialized_asset_id(run_dir, platform)
        source_media_path = f"assets/{platform}/licensed_media/human_supplied/{asset_id}_final.txt"
        source_media = run_dir / source_media_path
        source_media.parent.mkdir(parents=True, exist_ok=True)
        source_media.write_text(f"self-created mutation sandbox fixture for {asset_id}\n", encoding="utf-8")
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
            topic="Phase 4 显式批准工程沙盒改写验收",
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
        for agent_id in ["editor-project-mutation-sandbox-agent", "project-bundle-agent"]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        base = run_dir / "assets" / platform / "edit" / "mutation_sandbox"
        manifest = load_json(base / "mutation_manifest.json")
        mutation_diff = load_json(base / "mutation_diff.json")
        rollback_manifest = load_json(base / "rollback_manifest.json")
        audit_log = load_json(base / "mutation_audit_log.json")
        patched_project_path = base / "patched_project.fcpxml"
        original_project_path = run_dir / "assets" / platform / "edit" / "project.fcpxml"
        original_project = original_project_path.read_text(encoding="utf-8")
        patched_project = patched_project_path.read_text(encoding="utf-8")

        validate_platform_mutation_manifest(manifest, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_mutation_diff(mutation_diff, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_rollback_manifest(rollback_manifest, platform=platform, original_sha=sha256_text(original_project))
        validate_audit_log(audit_log, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_fcpxml(patched_project_path, platform)
        expect(manifest.get("human_mutation_approval_present") is True, "approved mutation manifest should record approval presence")
        expect(manifest.get("human_mutation_approval_valid") is True, "approved mutation manifest should validate approval")
        expect(manifest.get("summary", {}).get("mutation_applied_count", 0) >= 1, "approved path should apply at least one sandbox mutation")
        expect(manifest.get("validation", {}).get("patched_project_differs_from_original") is True, "approved patched project should differ")
        expect(sha256_text(original_project) != sha256_text(patched_project), "approved patched project text should differ from original")
        expect(original_project_path.read_text(encoding="utf-8") == original_project, "original project must remain unchanged")

        item = find_by_asset_id(manifest.get("mutation_items", []), asset_id)
        expect(item.get("mutation_status") == "sandbox_patch_applied", "approved asset should apply sandbox patch")
        expect(item.get("mutation_applied") is True, "approved asset mutation_applied mismatch")
        expect(item.get("original_project_mutated") is False, "approved path must not mutate original")
        expect(item.get("replacement_execution_performed") is False, "approved path must still not execute replacement")
        expect(item.get("editing_software_opened") is False, "approved path must still not open editor")
        expect(str(item.get("patched_src") or "").endswith(f"{asset_id}_proxy.txt"), "patched FCPXML should point to proxy copy")

        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "mutation_sandbox/mutation_manifest.json",
                "mutation_sandbox/patched_project.fcpxml",
                "mutation_sandbox/mutation_diff.json",
                "mutation_sandbox/rollback_manifest.json",
                "mutation_sandbox/mutation_audit_log.json",
                "mutation_sandbox/human_final_review_checklist.md",
                "mutation_sandbox/human_mutation_approval.json",
                "mutation_sandbox/README.md",
            ],
        )


def validate_platform_mutation_manifest(manifest: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(manifest.get("schema_version") == "phase4.editor_project_mutation_sandbox_manifest.v1", f"{platform} mutation schema mismatch")
    expect(manifest.get("artifact_type") == "editor_project_mutation_sandbox", f"{platform} mutation artifact type mismatch")
    expect(manifest.get("adapter") == "local-editor-project-mutation-sandbox-adapter", f"{platform} mutation adapter mismatch")
    expect(manifest.get("platform") == platform, f"{platform} mutation platform mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} mutation validation must pass")
    expect(manifest.get("manual_review_required") is True, f"{platform} mutation manifest must require review")
    expect(manifest.get("human_mutation_approval_required") is True, f"{platform} mutation manifest must require approval")
    expect(manifest.get("validation", {}).get("patched_copy_generated") is True, f"{platform} patched copy must be generated")
    expect(manifest.get("validation", {}).get("original_project_mutated") is False, f"{platform} original project must not mutate")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} must not execute replacement")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, f"{platform} must not open editor")
    validate_mutation_boundary(manifest.get("export_boundary", {}), platform, expected_boundary=expected_boundary)
    items = manifest.get("mutation_items", [])
    summary = manifest.get("summary", {})
    expect(isinstance(items, list) and items, f"{platform} mutation items must be non-empty")
    expect(summary.get("execution_item_count") == len(items), f"{platform} mutation item count mismatch")
    for item in items:
        expect(item.get("original_project_mutated") is False, f"{platform} item must not mutate original")
        expect(item.get("replacement_execution_performed") is False, f"{platform} item must not execute replacement")
        expect(item.get("editing_software_opened") is False, f"{platform} item must not open editor")


def validate_mutation_diff(diff: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(diff.get("schema_version") == "phase4.editor_project_mutation_diff.v1", f"{platform} diff schema mismatch")
    expect(diff.get("artifact_type") == "editor_project_mutation_diff", f"{platform} diff type mismatch")
    expect(diff.get("platform") == platform, f"{platform} diff platform mismatch")
    validate_mutation_boundary(diff.get("export_boundary", {}), f"{platform} diff", expected_boundary=expected_boundary)
    expect(isinstance(diff.get("mutation_items"), list), f"{platform} diff must include mutation items")


def validate_rollback_manifest(rollback: dict[str, Any], *, platform: str, original_sha: str) -> None:
    expect(rollback.get("schema_version") == "phase4.editor_project_mutation_rollback_manifest.v1", f"{platform} rollback schema mismatch")
    expect(rollback.get("artifact_type") == "editor_project_mutation_rollback_manifest", f"{platform} rollback type mismatch")
    expect(rollback.get("rollback_policy") == "discard_patched_copy_keep_original_project", f"{platform} rollback policy mismatch")
    expect(rollback.get("original_project_sha256") == original_sha, f"{platform} rollback original sha mismatch")
    expect(isinstance(rollback.get("patched_project_sha256"), str), f"{platform} rollback patched sha missing")


def validate_audit_log(audit_log: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(audit_log.get("schema_version") == "phase4.editor_project_mutation_audit_log.v1", f"{platform} audit schema mismatch")
    expect(audit_log.get("artifact_type") == "editor_project_mutation_audit_log", f"{platform} audit type mismatch")
    validate_mutation_boundary(audit_log.get("export_boundary", {}), f"{platform} audit", expected_boundary=expected_boundary)
    events = audit_log.get("events", [])
    expect(isinstance(events, list) and events, f"{platform} audit events must be non-empty")
    for event in events:
        expect(event.get("original_project_mutated") is False, f"{platform} audit must not record original mutation")
        expect(event.get("editing_software_opened") is False, f"{platform} audit must not record editor open")
        expect(event.get("replacement_execution_performed") is False, f"{platform} audit must not record replacement execution")


def validate_final_mutation_manifest(manifest: dict[str, Any], *, expected_boundary: str, default_blocked: bool) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_project_mutation_bundle_manifest.v1",
        "final mutation schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_project_mutation_bundle", "final mutation type mismatch")
    expect(manifest.get("platforms") == VIDEO_PLATFORMS, "final mutation platforms mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", "final mutation validation must pass")
    expect(manifest.get("validation", {}).get("execution_item_count", 0) >= 1, "final mutation item count must be non-empty")
    expect(manifest.get("validation", {}).get("human_mutation_approval_required") is True, "final mutation must require approval")
    expect(manifest.get("validation", {}).get("patched_copy_generated") is True, "final mutation must generate patched copies")
    expect(manifest.get("validation", {}).get("original_project_mutated") is False, "final mutation must not mutate originals")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, "final mutation must not execute replacement")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, "final mutation must not open editor")
    if default_blocked:
        expect(manifest.get("validation", {}).get("human_mutation_approval_present_count") == 0, "default final mutation approval count should be zero")
        expect(manifest.get("validation", {}).get("human_mutation_approval_valid_count") == 0, "default final mutation valid approval count should be zero")
        expect(manifest.get("validation", {}).get("mutation_applied_count") == 0, "default final mutation applied count should be zero")
    validate_mutation_boundary(manifest.get("export_boundary", {}), "final mutation", expected_boundary=expected_boundary)


def validate_mutation_boundary(boundary: dict[str, Any], label: str, *, expected_boundary: str) -> None:
    expect(boundary.get("editor_project_mutation_sandbox") == expected_boundary, f"{label} mutation boundary mismatch")
    expect(boundary.get("original_project_mutation") == "not_performed", f"{label} must not mutate original project")
    expect(boundary.get("replacement_execution") == "not_performed", f"{label} must not execute replacement")
    expect(boundary.get("editing_software") == "not_opened", f"{label} must not open editing software")
    expect(boundary.get("project_file_mutation") == "patched_copy_only_original_not_mutated", f"{label} project mutation policy mismatch")
    expect(boundary.get("requires_explicit_human_mutation_approval") is True, f"{label} must require explicit mutation approval")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} must mark {key} as not_performed")


def validate_platform_package_summary(
    summary: dict[str, Any],
    *,
    platform: str,
    expected_boundary: str,
    default_blocked: bool,
) -> None:
    expect(summary.get("validation_status") == "PASSED", f"{platform} package mutation summary must pass")
    expect(summary.get("editor_project_mutation_sandbox") == expected_boundary, f"{platform} package mutation boundary mismatch")
    expect(summary.get("execution_item_count", 0) >= 1, f"{platform} package mutation items must be non-empty")
    expect(summary.get("human_mutation_approval_required") is True, f"{platform} package must require mutation approval")
    expect(summary.get("patched_copy_generated") is True, f"{platform} package must generate patched copy")
    expect(summary.get("original_project_mutated") is False, f"{platform} package must not mutate original")
    expect(summary.get("replacement_execution_performed") is False, f"{platform} package must not execute replacement")
    expect(summary.get("editing_software_opened") is False, f"{platform} package must not open editor")
    if default_blocked:
        expect(summary.get("human_mutation_approval_present") is False, f"{platform} package default approval should be absent")
        expect(summary.get("human_mutation_approval_valid") is False, f"{platform} package default approval should be invalid")
        expect(summary.get("mutation_applied_count") == 0, f"{platform} package default mutation count should be zero")


def validate_final_platform_entry(final_entry: dict[str, Any], deliverables: dict[str, str], *, platform: str) -> None:
    expect(final_entry.get("manifest_path") == deliverables["editor_project_mutation_manifest"], f"{platform} final mutation manifest path mismatch")
    expect(final_entry.get("patched_project_path") == deliverables["editor_project_patched_fcpxml"], f"{platform} final patched project path mismatch")
    expect(final_entry.get("mutation_diff_path") == deliverables["editor_project_mutation_diff"], f"{platform} final mutation diff path mismatch")
    expect(final_entry.get("rollback_manifest_path") == deliverables["editor_project_rollback_manifest"], f"{platform} final rollback path mismatch")
    expect(final_entry.get("audit_log_path") == deliverables["editor_project_mutation_audit_log"], f"{platform} final audit path mismatch")
    expect(final_entry.get("final_review_checklist_path") == deliverables["editor_project_final_review_checklist"], f"{platform} final checklist path mismatch")
    expect(final_entry.get("readme_path") == deliverables["editor_project_mutation_readme"], f"{platform} final readme path mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final mutation validation must pass")
    expect(final_entry.get("validation", {}).get("original_project_mutated") is False, f"{platform} final entry must not mutate original")
    expect(final_entry.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} final entry must not execute replacement")
    expect(final_entry.get("validation", {}).get("editing_software_opened") is False, f"{platform} final entry must not open editor")


def validate_mutation_docs(checklist_path: Path, readme_path: Path, platform: str) -> None:
    checklist = checklist_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    expect("Editor Project Mutation Sandbox Final Review" in checklist, f"{platform} checklist missing heading")
    expect("does not open editing software" in checklist, f"{platform} checklist missing no editor boundary")
    expect("Editor Project Mutation Sandbox" in readme, f"{platform} README missing heading")
    expect("never mutates the original project file" in readme, f"{platform} README missing original mutation boundary")


def validate_fcpxml(path: Path, platform: str) -> None:
    text = path.read_text(encoding="utf-8")
    xml_text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("<!DOCTYPE"))
    try:
        ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        fail(f"{platform} patched FCPXML is not parseable: {exc}")


def with_zip_paths(bundle_path: Path, platform: str, required_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in required_paths:
        expect(archive_path in archive_paths, f"{platform} bundle missing mutation sandbox file: {archive_path}")


def expected_platform_deliverables(platform: str) -> dict[str, str]:
    return {
        "editor_project_mutation_manifest": f"assets/{platform}/edit/mutation_sandbox/mutation_manifest.json",
        "editor_project_patched_fcpxml": f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml",
        "editor_project_mutation_diff": f"assets/{platform}/edit/mutation_sandbox/mutation_diff.json",
        "editor_project_rollback_manifest": f"assets/{platform}/edit/mutation_sandbox/rollback_manifest.json",
        "editor_project_mutation_audit_log": f"assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json",
        "editor_project_final_review_checklist": f"assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md",
        "editor_project_mutation_readme": f"assets/{platform}/edit/mutation_sandbox/README.md",
    }


def first_materialized_asset_id(run_dir: Path, platform: str) -> str:
    material_manifest = load_json(run_dir / "assets" / platform / "materials" / "material_manifest.json")
    material_assets = material_manifest.get("materialized_assets", [])
    expect(isinstance(material_assets, list) and material_assets, f"{platform} material manifest must contain assets")
    asset_id = str(material_assets[0].get("asset_id") or "")
    expect(bool(asset_id), f"{platform} first material asset must have asset_id")
    return asset_id


def find_by_asset_id(items: Any, asset_id: str) -> dict[str, Any]:
    if not isinstance(items, list):
        fail(f"expected list while finding asset: {asset_id}")
    for item in items:
        if isinstance(item, dict) and str(item.get("asset_id")) == asset_id:
            return item
    fail(f"missing asset_id in collection: {asset_id}")
    raise AssertionError("unreachable")


def main() -> int:
    validate_workflow_mutation_steps()
    print("Phase 4 editor project mutation sandbox drill passed: workflow mutation steps")
    validate_default_blocked_run()
    print("Phase 4 editor project mutation sandbox drill passed: default blocked sandbox copy")
    validate_explicit_approval_sandbox_patch_path()
    print("Phase 4 editor project mutation sandbox drill passed: explicit approval patches sandbox copy only")
    print("Phase 4 editor project mutation sandbox validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
