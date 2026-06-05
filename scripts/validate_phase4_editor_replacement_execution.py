from __future__ import annotations

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
EXECUTION_BOUNDARY = "blocked_pending_explicit_human_approval"
APPROVED_BOUNDARY = "approved_but_not_executed_by_default"
EXECUTION_FILES = {
    "execution_manifest": "execution_manifest.json",
    "execution_plan": "execution_plan.json",
    "execution_audit_log": "execution_audit_log.json",
    "human_execution_approval_request": "human_execution_approval_request.md",
    "readme": "README.md",
}


def fail(message: str) -> None:
    print(f"Phase 4 editor replacement execution validation failed: {message}", file=sys.stderr)
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


def validate_workflow_execution_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect(
        "final/editor_replacement_execution_manifest.json" in workflow.outputs,
        "workflow must export editor replacement execution manifest",
    )

    for platform in VIDEO_PLATFORMS:
        instruction_step_id = f"{platform}_editor_replacement_instructions"
        execution_step_id = f"{platform}_editor_replacement_execution"
        bundle_step_id = f"{platform}_project_bundle"
        execution_step = steps.get(execution_step_id)
        bundle_step = steps.get(bundle_step_id)

        expect(execution_step is not None, f"workflow missing step: {execution_step_id}")
        expect(
            execution_step.agent == "editor-replacement-execution-agent",
            f"{execution_step_id} must use editor-replacement-execution-agent",
        )
        expect(execution_step.platform == platform, f"{execution_step_id} platform mismatch")
        expect(
            instruction_step_id in execution_step.depends_on,
            f"{execution_step_id} must depend on editor replacement instructions",
        )
        for filename in EXECUTION_FILES.values():
            output_path = f"assets/{platform}/edit/replacement_execution/{filename}"
            expect(output_path in execution_step.outputs, f"{execution_step_id} missing output: {output_path}")

        expect(bundle_step is not None, f"workflow missing bundle step for {platform}")
        expect(
            depends_on_transitively(steps, bundle_step_id, execution_step_id),
            f"{bundle_step_id} must be downstream of editor execution",
        )
        expect(execution_step_id in fact_check.depends_on, f"fact_check must depend on {execution_step_id}")


def validate_default_no_approval_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 剪辑替换执行预检验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/editor_replacement_execution_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor replacement execution manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }

        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/editor_replacement_execution_manifest.json")

        expect(
            video_package.get("editor_replacement_execution_manifest")
            == "final/editor_replacement_execution_manifest.json",
            "video package must reference editor replacement execution manifest",
        )
        expect(
            content_package.get("editor_replacement_execution_manifest")
            == "final/editor_replacement_execution_manifest.json",
            "content package must reference editor replacement execution manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("editor_replacement_execution") == EXECUTION_BOUNDARY,
            "video package execution boundary mismatch",
        )
        validate_final_execution_manifest(final_manifest, expected_boundary=EXECUTION_BOUNDARY, default_no_approval=True)

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_manifest.get("platform_executions", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            validate_default_platform_execution(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                logs_by_step=logs_by_step,
                package=packages.get(platform),
                final_entry=final_entries.get(platform),
            )


def validate_default_platform_execution(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    logs_by_step: dict[str, Any],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_editor_replacement_execution"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    expect(metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
    expect(metadata.get("editor_replacement_execution_status") == "PASSED", f"{step_id} status must pass")
    expect(metadata.get("human_execution_approval_required") is True, f"{step_id} must require approval")
    expect(metadata.get("human_execution_approval_present") is False, f"{step_id} default run must not have approval")
    expect(metadata.get("human_execution_approval_valid") is False, f"{step_id} default approval must be invalid")
    expect(metadata.get("replacement_execution_performed") is False, f"{step_id} must not execute replacement")
    expect(metadata.get("editing_software_opened") is False, f"{step_id} must not open editing software")
    expect(metadata.get("project_file_mutation_performed") is False, f"{step_id} must not mutate project files")

    base = run_dir / "assets" / platform / "edit" / "replacement_execution"
    manifest = load_json(base / "execution_manifest.json")
    execution_plan = load_json(base / "execution_plan.json")
    audit_log = load_json(base / "execution_audit_log.json")
    approval_request_path = base / "human_execution_approval_request.md"
    readme_path = base / "README.md"
    for path in [approval_request_path, readme_path]:
        expect(path.exists(), f"{platform} execution file missing: {path.relative_to(run_dir)}")

    validate_platform_execution_manifest(manifest, platform=platform, expected_boundary=EXECUTION_BOUNDARY)
    validate_execution_plan(execution_plan, platform=platform, expected_boundary=EXECUTION_BOUNDARY)
    validate_audit_log(audit_log, platform=platform, expected_boundary=EXECUTION_BOUNDARY)
    validate_execution_docs(approval_request_path, readme_path, platform)

    statuses = {item.get("execution_status") for item in manifest.get("execution_items", []) if isinstance(item, dict)}
    expect("ready_for_manual_execution" not in statuses, f"{platform} default run must not mark commands ready")
    expect(any(str(status).startswith("blocked_") for status in statuses), f"{platform} default run must block commands")

    with_zip_paths(
        run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
        platform,
        [
            "replacement_execution/execution_manifest.json",
            "replacement_execution/execution_plan.json",
            "replacement_execution/execution_audit_log.json",
            "replacement_execution/human_execution_approval_request.md",
            "replacement_execution/README.md",
        ],
    )

    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    expected_deliverables = {
        "editor_replacement_execution_manifest": f"assets/{platform}/edit/replacement_execution/execution_manifest.json",
        "editor_replacement_execution_plan": f"assets/{platform}/edit/replacement_execution/execution_plan.json",
        "editor_replacement_execution_audit_log": f"assets/{platform}/edit/replacement_execution/execution_audit_log.json",
        "editor_replacement_approval_request": f"assets/{platform}/edit/replacement_execution/human_execution_approval_request.md",
        "editor_replacement_execution_readme": f"assets/{platform}/edit/replacement_execution/README.md",
    }
    for key, expected_path in expected_deliverables.items():
        expect(deliverables.get(key) == expected_path, f"{platform} package deliverable mismatch: {key}")
        expect((run_dir / expected_path).exists(), f"{platform} package deliverable path missing: {expected_path}")

    summary = package.get("editor_replacement_execution", {})
    expect(summary.get("validation_status") == "PASSED", f"{platform} package execution summary must pass")
    expect(summary.get("command_count", 0) >= 1, f"{platform} package execution commands must be non-empty")
    expect(summary.get("human_execution_approval_required") is True, f"{platform} package must require approval")
    expect(summary.get("human_execution_approval_present") is False, f"{platform} package default approval should be absent")
    expect(summary.get("human_execution_approval_valid") is False, f"{platform} package default approval should be invalid")
    expect(summary.get("replacement_execution_performed") is False, f"{platform} package must not execute replacement")
    expect(summary.get("editing_software_opened") is False, f"{platform} package must not open editing software")
    expect(summary.get("project_file_mutation_performed") is False, f"{platform} package must not mutate project files")

    expect(isinstance(final_entry, dict), f"final execution manifest missing platform: {platform}")
    expect(final_entry.get("manifest_path") == expected_deliverables["editor_replacement_execution_manifest"], f"{platform} final execution manifest path mismatch")
    expect(final_entry.get("execution_plan_path") == expected_deliverables["editor_replacement_execution_plan"], f"{platform} final execution plan path mismatch")
    expect(final_entry.get("audit_log_path") == expected_deliverables["editor_replacement_execution_audit_log"], f"{platform} final audit path mismatch")
    expect(final_entry.get("approval_request_path") == expected_deliverables["editor_replacement_approval_request"], f"{platform} final approval request path mismatch")
    expect(final_entry.get("readme_path") == expected_deliverables["editor_replacement_execution_readme"], f"{platform} final readme path mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final execution validation must pass")
    expect(final_entry.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} final entry must not execute replacement")


def validate_approved_but_not_executed_path() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 显式批准但不执行验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        platform = "douyin"
        material_manifest = load_json(run_dir / "assets" / platform / "materials" / "material_manifest.json")
        material_assets = material_manifest.get("materialized_assets", [])
        expect(isinstance(material_assets, list) and material_assets, "douyin material manifest must contain assets")
        asset_id = str(material_assets[0]["asset_id"])
        source_media_path = f"assets/{platform}/licensed_media/human_supplied/{asset_id}_final.txt"
        source_media = run_dir / source_media_path
        source_media.parent.mkdir(parents=True, exist_ok=True)
        source_media.write_text(f"self-created execution fixture for {asset_id}\n", encoding="utf-8")
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
            topic="Phase 4 显式批准但不执行验收",
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
                "approval_note": "Test approval: reviewed rights, timeline, and final editor replacement scope.",
            },
        )

        for agent_id in ["editor-replacement-execution-agent", "project-bundle-agent"]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        manifest = load_json(run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_manifest.json")
        execution_plan = load_json(run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_plan.json")
        audit_log = load_json(run_dir / "assets" / platform / "edit" / "replacement_execution" / "execution_audit_log.json")
        validate_platform_execution_manifest(manifest, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_execution_plan(execution_plan, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_audit_log(audit_log, platform=platform, expected_boundary=APPROVED_BOUNDARY)

        item = _find_by_asset_id(manifest.get("execution_items", []), asset_id)
        plan_item = _find_by_asset_id(execution_plan.get("commands", []), asset_id)
        expect(item.get("execution_status") == "ready_for_manual_execution", "approved item should be ready for manual execution")
        expect(item.get("human_execution_approved") is True, "approved item must record human execution approval")
        expect(item.get("execution_performed") is False, "approved item must still not execute")
        expect(item.get("editing_software_opened") is False, "approved item must still not open editor")
        expect(item.get("project_file_mutation_performed") is False, "approved item must still not mutate project")
        expect(plan_item.get("execution_status") == "ready_for_manual_execution", "approved plan item status mismatch")
        expect(manifest.get("validation", {}).get("executable_after_approval_count", 0) >= 1, "approved manifest should expose manual-ready command")
        expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, "approved manifest must not execute")

        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "replacement_execution/execution_manifest.json",
                "replacement_execution/execution_plan.json",
                "replacement_execution/execution_audit_log.json",
                "replacement_execution/human_execution_approval_request.md",
                "replacement_execution/human_execution_approval.json",
                "replacement_execution/README.md",
            ],
        )


def validate_platform_execution_manifest(manifest: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(manifest.get("schema_version") == "phase4.editor_replacement_execution_manifest.v1", f"{platform} execution schema mismatch")
    expect(manifest.get("artifact_type") == "editor_replacement_execution", f"{platform} execution artifact type mismatch")
    expect(manifest.get("adapter") == "local-editor-replacement-execution-adapter", f"{platform} execution adapter mismatch")
    expect(manifest.get("platform") == platform, f"{platform} execution platform mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} execution validation must pass")
    expect(manifest.get("manual_review_required") is True, f"{platform} execution manifest must require review")
    expect(manifest.get("human_execution_approval_required") is True, f"{platform} execution manifest must require approval")
    validate_execution_boundary(manifest.get("export_boundary", {}), platform, expected_boundary=expected_boundary)

    items = manifest.get("execution_items", [])
    summary = manifest.get("summary", {})
    expect(isinstance(items, list) and items, f"{platform} execution items must be non-empty")
    expect(summary.get("command_count") == len(items), f"{platform} execution command count mismatch")
    for item in items:
        expect(item.get("execution_performed") is False, f"{platform} item must not execute")
        expect(item.get("editing_software_opened") is False, f"{platform} item must not open editor")
        expect(item.get("project_file_mutation_performed") is False, f"{platform} item must not mutate project")
        expect(item.get("execution_mode") == "manual_execution_only", f"{platform} item mode mismatch")


def validate_execution_plan(plan: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(plan.get("schema_version") == "phase4.editor_replacement_execution_plan.v1", f"{platform} plan schema mismatch")
    expect(plan.get("artifact_type") == "editor_replacement_execution_plan", f"{platform} plan type mismatch")
    expect(plan.get("platform") == platform, f"{platform} plan platform mismatch")
    expect(plan.get("validation", {}).get("status") == "PASSED", f"{platform} plan validation must pass")
    validate_execution_boundary(plan.get("export_boundary", {}), f"{platform} plan", expected_boundary=expected_boundary)
    commands = plan.get("commands", [])
    expect(isinstance(commands, list) and commands, f"{platform} plan commands must be non-empty")
    for command in commands:
        expect(command.get("execution_performed") is False, f"{platform} plan command must not execute")
        expect(command.get("editing_software_opened") is False, f"{platform} plan command must not open editor")
        expect(command.get("project_file_mutation_performed") is False, f"{platform} plan command must not mutate project")


def validate_audit_log(audit_log: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(audit_log.get("schema_version") == "phase4.editor_replacement_execution_audit_log.v1", f"{platform} audit schema mismatch")
    expect(audit_log.get("artifact_type") == "editor_replacement_execution_audit_log", f"{platform} audit type mismatch")
    validate_execution_boundary(audit_log.get("export_boundary", {}), f"{platform} audit", expected_boundary=expected_boundary)
    events = audit_log.get("events", [])
    expect(isinstance(events, list) and events, f"{platform} audit events must be non-empty")
    for event in events:
        expect(event.get("replacement_execution_performed") is False, f"{platform} audit must not record execution")
        expect(event.get("editing_software_opened") is False, f"{platform} audit must not record editor open")
        expect(event.get("project_file_mutation_performed") is False, f"{platform} audit must not record project mutation")


def validate_final_execution_manifest(manifest: dict[str, Any], *, expected_boundary: str, default_no_approval: bool) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_replacement_execution_bundle_manifest.v1",
        "final execution schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_replacement_execution_bundle", "final execution type mismatch")
    expect(manifest.get("platforms") == VIDEO_PLATFORMS, "final execution platforms mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", "final execution validation must pass")
    expect(manifest.get("validation", {}).get("command_count", 0) >= 1, "final execution command count must be non-empty")
    expect(manifest.get("validation", {}).get("human_execution_approval_required") is True, "final execution must require approval")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, "final execution must not execute")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, "final execution must not open editor")
    expect(manifest.get("validation", {}).get("project_file_mutation_performed") is False, "final execution must not mutate project")
    if default_no_approval:
        expect(manifest.get("validation", {}).get("human_execution_approval_present_count") == 0, "default final approval count should be zero")
        expect(manifest.get("validation", {}).get("human_execution_approval_valid_count") == 0, "default final valid approval count should be zero")
    validate_execution_boundary(manifest.get("export_boundary", {}), "final execution", expected_boundary=expected_boundary)


def validate_execution_boundary(boundary: dict[str, Any], label: str, *, expected_boundary: str) -> None:
    expect(boundary.get("editor_replacement_execution") == expected_boundary, f"{label} execution boundary mismatch")
    expect(boundary.get("replacement_execution") == "not_performed", f"{label} must not execute replacement")
    expect(boundary.get("editing_software") == "not_opened", f"{label} must not open editing software")
    expect(boundary.get("project_file_mutation") == "not_performed", f"{label} must not mutate project files")
    expect(boundary.get("requires_explicit_human_approval") is True, f"{label} must require explicit approval")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} must mark {key} as not_performed")


def validate_execution_docs(approval_request_path: Path, readme_path: Path, platform: str) -> None:
    approval_request = approval_request_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    expect("Editor Replacement Execution Approval Request" in approval_request, f"{platform} approval request missing heading")
    expect("No replacement was executed" in approval_request, f"{platform} approval request missing no-execution boundary")
    expect("auditable execution adapter plan" in readme, f"{platform} README missing adapter plan wording")
    expect("does not open editing software" in readme, f"{platform} README missing no editor boundary")


def with_zip_paths(bundle_path: Path, platform: str, required_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in required_paths:
        expect(archive_path in archive_paths, f"{platform} bundle missing execution file: {archive_path}")


def _find_by_asset_id(items: Any, asset_id: str) -> dict[str, Any]:
    if not isinstance(items, list):
        fail(f"expected list while finding asset: {asset_id}")
    for item in items:
        if isinstance(item, dict) and str(item.get("asset_id")) == asset_id:
            return item
    fail(f"missing asset_id in collection: {asset_id}")
    raise AssertionError("unreachable")


def main() -> int:
    validate_workflow_execution_steps()
    print("Phase 4 editor replacement execution drill passed: workflow execution steps")
    validate_default_no_approval_run()
    print("Phase 4 editor replacement execution drill passed: default blocked execution adapter")
    validate_approved_but_not_executed_path()
    print("Phase 4 editor replacement execution drill passed: explicit approval remains non-executing")
    print("Phase 4 editor replacement execution validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
