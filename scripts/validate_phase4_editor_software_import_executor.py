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
BLOCKED_BOUNDARY = "blocked_pending_explicit_human_software_import_approval"
APPROVED_BOUNDARY = "approved_for_isolated_manual_import_not_executed"
IMPORT_FILES = {
    "manifest": "import_executor_manifest.json",
    "plan": "import_plan.json",
    "commands": "import_commands.json",
    "audit_log": "software_import_audit_log.json",
    "rollback_safety_report": "rollback_safety_report.json",
    "execution_request": "isolated_execution_request.md",
    "readme": "README.md",
}


def fail(message: str) -> None:
    print(f"Phase 4 editor software import executor validation failed: {message}", file=sys.stderr)
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


def validate_workflow_import_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect(
        "final/editor_software_import_manifest.json" in workflow.outputs,
        "workflow must export editor software import manifest",
    )

    for platform in VIDEO_PLATFORMS:
        mutation_step_id = f"{platform}_editor_project_mutation_sandbox"
        import_step_id = f"{platform}_editor_software_import_executor"
        bundle_step_id = f"{platform}_project_bundle"
        import_step = steps.get(import_step_id)
        bundle_step = steps.get(bundle_step_id)

        expect(import_step is not None, f"workflow missing step: {import_step_id}")
        expect(
            import_step.agent == "editor-software-import-executor-agent",
            f"{import_step_id} must use editor-software-import-executor-agent",
        )
        expect(import_step.platform == platform, f"{import_step_id} platform mismatch")
        expect(
            mutation_step_id in import_step.depends_on,
            f"{import_step_id} must depend on editor project mutation sandbox",
        )
        for filename in IMPORT_FILES.values():
            output_path = f"assets/{platform}/edit/software_import_executor/{filename}"
            expect(output_path in import_step.outputs, f"{import_step_id} missing output: {output_path}")

        expect(bundle_step is not None, f"workflow missing bundle step for {platform}")
        expect(
            depends_on_transitively(steps, bundle_step_id, import_step_id),
            f"{bundle_step_id} must be downstream of software import executor",
        )
        expect(import_step_id in fact_check.depends_on, f"fact_check must depend on {import_step_id}")


def validate_default_blocked_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 剪辑软件导入执行器默认阻断验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/editor_software_import_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor software import manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }

        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/editor_software_import_manifest.json")
        expect(
            video_package.get("editor_software_import_manifest") == "final/editor_software_import_manifest.json",
            "video package must reference editor software import manifest",
        )
        expect(
            content_package.get("editor_software_import_manifest") == "final/editor_software_import_manifest.json",
            "content package must reference editor software import manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("editor_software_import_executor") == BLOCKED_BOUNDARY,
            "video package software import boundary mismatch",
        )
        validate_final_import_manifest(final_manifest, expected_boundary=BLOCKED_BOUNDARY, default_blocked=True)

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_manifest.get("platform_imports", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            validate_default_platform_import(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                logs_by_step=logs_by_step,
                package=packages.get(platform),
                final_entry=final_entries.get(platform),
            )


def validate_default_platform_import(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    logs_by_step: dict[str, Any],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_editor_software_import_executor"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    expect(metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
    expect(metadata.get("editor_software_import_status") == "PASSED", f"{step_id} status must pass")
    expect(metadata.get("human_software_import_approval_required") is True, f"{step_id} must require software import approval")
    expect(metadata.get("human_software_import_approval_present") is False, f"{step_id} default run must not have approval")
    expect(metadata.get("human_software_import_approval_valid") is False, f"{step_id} default approval must be invalid")
    expect(metadata.get("software_import_execution_performed") is False, f"{step_id} must not execute import")
    expect(metadata.get("editing_software_opened") is False, f"{step_id} must not open editing software")
    expect(metadata.get("project_file_mutation_performed") is False, f"{step_id} must not mutate project files")

    base = run_dir / "assets" / platform / "edit" / "software_import_executor"
    manifest = load_json(base / "import_executor_manifest.json")
    import_plan = load_json(base / "import_plan.json")
    import_commands = load_json(base / "import_commands.json")
    audit_log = load_json(base / "software_import_audit_log.json")
    rollback_safety_report = load_json(base / "rollback_safety_report.json")
    execution_request_path = base / "isolated_execution_request.md"
    readme_path = base / "README.md"
    for path in [execution_request_path, readme_path]:
        expect(path.exists(), f"{platform} software import file missing: {path.relative_to(run_dir)}")

    validate_platform_import_manifest(manifest, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_import_plan(import_plan, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_import_commands(import_commands, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_import_audit_log(audit_log, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_rollback_safety_report(rollback_safety_report, platform=platform)
    validate_import_docs(execution_request_path, readme_path, platform)

    expect(manifest.get("summary", {}).get("ready_for_isolated_manual_import_count") == 0, f"{platform} default import should have no ready items")
    expect(manifest.get("summary", {}).get("blocked_pending_approval_count", 0) >= 1, f"{platform} default import should block on approval")
    statuses = {item.get("import_status") for item in manifest.get("import_items", []) if isinstance(item, dict)}
    expect("ready_for_isolated_manual_import" not in statuses, f"{platform} default import must not be ready")
    expect("blocked_pending_human_software_import_approval" in statuses, f"{platform} default import must block pending approval")

    with_zip_paths(
        run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
        platform,
        [
            "software_import_executor/import_executor_manifest.json",
            "software_import_executor/import_plan.json",
            "software_import_executor/import_commands.json",
            "software_import_executor/software_import_audit_log.json",
            "software_import_executor/rollback_safety_report.json",
            "software_import_executor/isolated_execution_request.md",
            "software_import_executor/README.md",
        ],
    )

    expected_deliverables = expected_platform_deliverables(platform)
    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    for key, expected_path in expected_deliverables.items():
        expect(deliverables.get(key) == expected_path, f"{platform} package deliverable mismatch: {key}")
        expect((run_dir / expected_path).exists(), f"{platform} package deliverable path missing: {expected_path}")

    summary = package.get("editor_software_import_executor", {})
    validate_platform_package_summary(summary, platform=platform, expected_boundary=BLOCKED_BOUNDARY, default_blocked=True)
    expect(isinstance(final_entry, dict), f"final software import manifest missing platform: {platform}")
    validate_final_platform_entry(final_entry, expected_deliverables, platform=platform)


def validate_explicit_approval_import_path() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 显式批准剪辑软件导入执行器验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        platform = "douyin"
        asset_id = first_materialized_asset_id(run_dir, platform)
        source_media_path = f"assets/{platform}/licensed_media/human_supplied/{asset_id}_final.txt"
        source_media = run_dir / source_media_path
        source_media.parent.mkdir(parents=True, exist_ok=True)
        source_media.write_text(f"self-created software import fixture for {asset_id}\n", encoding="utf-8")
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
            topic="Phase 4 显式批准剪辑软件导入执行器验收",
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
        for agent_id in ["editor-software-import-executor-agent", "project-bundle-agent"]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        base = run_dir / "assets" / platform / "edit" / "software_import_executor"
        manifest = load_json(base / "import_executor_manifest.json")
        import_plan = load_json(base / "import_plan.json")
        import_commands = load_json(base / "import_commands.json")
        audit_log = load_json(base / "software_import_audit_log.json")
        rollback_safety_report = load_json(base / "rollback_safety_report.json")

        validate_platform_import_manifest(manifest, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_import_plan(import_plan, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_import_commands(import_commands, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_import_audit_log(audit_log, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_rollback_safety_report(rollback_safety_report, platform=platform)
        expect(manifest.get("human_software_import_approval_present") is True, "approved import should record approval presence")
        expect(manifest.get("human_software_import_approval_valid") is True, "approved import should validate approval")
        expect(
            manifest.get("summary", {}).get("ready_for_isolated_manual_import_count", 0) >= 1,
            "approved import should expose at least one manual import ready item",
        )
        item = find_by_asset_id(manifest.get("import_items", []), asset_id)
        expect(item.get("import_status") == "ready_for_isolated_manual_import", "approved asset should be ready for isolated manual import")
        expect(item.get("import_execution_performed") is False, "approved import must still not execute")
        expect(item.get("editing_software_opened") is False, "approved import must still not open editor")
        expect(item.get("project_file_mutation_performed") is False, "approved import must still not mutate project")
        command = find_by_asset_id(import_commands.get("commands", []), asset_id)
        expect(command.get("execution_status") == "ready_for_isolated_manual_import", "approved command status mismatch")
        expect(command.get("dry_run_only") is True, "approved command must remain dry-run")
        expect(command.get("auto_execute") is False, "approved command must not auto-execute")

        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "software_import_executor/import_executor_manifest.json",
                "software_import_executor/import_plan.json",
                "software_import_executor/import_commands.json",
                "software_import_executor/software_import_audit_log.json",
                "software_import_executor/rollback_safety_report.json",
                "software_import_executor/isolated_execution_request.md",
                "software_import_executor/human_software_import_approval.json",
                "software_import_executor/README.md",
            ],
        )


def validate_platform_import_manifest(manifest: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_software_import_executor_manifest.v1",
        f"{platform} import schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_software_import_executor", f"{platform} import artifact type mismatch")
    expect(manifest.get("adapter") == "local-editor-software-import-executor-adapter", f"{platform} import adapter mismatch")
    expect(manifest.get("platform") == platform, f"{platform} import platform mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} import validation must pass")
    expect(manifest.get("manual_review_required") is True, f"{platform} import manifest must require review")
    expect(manifest.get("human_software_import_approval_required") is True, f"{platform} import manifest must require approval")
    expect(manifest.get("validation", {}).get("patched_project_exists") is True, f"{platform} patched project must exist")
    expect(manifest.get("validation", {}).get("rollback_available") is True, f"{platform} rollback must be available")
    expect(manifest.get("validation", {}).get("software_import_execution_performed") is False, f"{platform} must not execute import")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, f"{platform} must not open editor")
    expect(manifest.get("validation", {}).get("project_file_mutation_performed") is False, f"{platform} must not mutate project")
    expect(manifest.get("validation", {}).get("original_project_mutated") is False, f"{platform} must not mutate original")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} must not execute replacement")
    validate_import_boundary(manifest.get("export_boundary", {}), platform, expected_boundary=expected_boundary)
    items = manifest.get("import_items", [])
    summary = manifest.get("summary", {})
    expect(isinstance(items, list) and items, f"{platform} import items must be non-empty")
    expect(summary.get("import_item_count") == len(items), f"{platform} import item count mismatch")
    for item in items:
        expect(item.get("import_execution_performed") is False, f"{platform} item must not execute import")
        expect(item.get("editing_software_opened") is False, f"{platform} item must not open editor")
        expect(item.get("project_file_mutation_performed") is False, f"{platform} item must not mutate project")
        expect(item.get("upload_performed") is False, f"{platform} item must not upload")
        expect(item.get("publishing_performed") is False, f"{platform} item must not publish")


def validate_import_plan(plan: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(plan.get("schema_version") == "phase4.editor_software_import_plan.v1", f"{platform} import plan schema mismatch")
    expect(plan.get("artifact_type") == "editor_software_import_plan", f"{platform} import plan type mismatch")
    expect(plan.get("platform") == platform, f"{platform} import plan platform mismatch")
    validate_import_boundary(plan.get("export_boundary", {}), f"{platform} import plan", expected_boundary=expected_boundary)
    expect(isinstance(plan.get("import_items"), list) and plan["import_items"], f"{platform} import plan must include items")
    validate_command_list(plan.get("commands", []), platform=platform)


def validate_import_commands(commands: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        commands.get("schema_version") == "phase4.editor_software_import_commands.v1",
        f"{platform} import commands schema mismatch",
    )
    expect(commands.get("artifact_type") == "editor_software_import_commands", f"{platform} import commands type mismatch")
    validate_import_boundary(commands.get("export_boundary", {}), f"{platform} import commands", expected_boundary=expected_boundary)
    validate_command_list(commands.get("commands", []), platform=platform)


def validate_command_list(commands: Any, *, platform: str) -> None:
    expect(isinstance(commands, list) and commands, f"{platform} import commands must be non-empty")
    for command in commands:
        expect(command.get("command_type") == "editor_software_import", f"{platform} command type mismatch")
        expect(command.get("isolated_execution_required") is True, f"{platform} command must require isolation")
        expect(command.get("auto_execute") is False, f"{platform} command must not auto-execute")
        expect(command.get("dry_run_only") is True, f"{platform} command must be dry-run")
        expect(command.get("human_software_import_approval_required") is True, f"{platform} command must require approval")
        expect(command.get("import_execution_performed") is False, f"{platform} command must not execute import")
        expect(command.get("editing_software_opened") is False, f"{platform} command must not open editor")
        expect(command.get("project_file_mutation_performed") is False, f"{platform} command must not mutate project")
        expect(command.get("upload_performed") is False, f"{platform} command must not upload")
        expect(command.get("publishing_performed") is False, f"{platform} command must not publish")


def validate_import_audit_log(audit_log: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        audit_log.get("schema_version") == "phase4.editor_software_import_audit_log.v1",
        f"{platform} audit schema mismatch",
    )
    expect(audit_log.get("artifact_type") == "editor_software_import_audit_log", f"{platform} audit type mismatch")
    validate_import_boundary(audit_log.get("export_boundary", {}), f"{platform} audit", expected_boundary=expected_boundary)
    events = audit_log.get("events", [])
    expect(isinstance(events, list) and events, f"{platform} audit events must be non-empty")
    for event in events:
        expect(event.get("software_import_execution_performed") is False, f"{platform} audit must not record import execution")
        expect(event.get("editing_software_opened") is False, f"{platform} audit must not record editor open")
        expect(event.get("project_file_mutation_performed") is False, f"{platform} audit must not record project mutation")


def validate_rollback_safety_report(report: dict[str, Any], *, platform: str) -> None:
    expect(
        report.get("schema_version") == "phase4.editor_software_import_rollback_safety_report.v1",
        f"{platform} rollback safety schema mismatch",
    )
    expect(
        report.get("artifact_type") == "editor_software_import_rollback_safety_report",
        f"{platform} rollback safety type mismatch",
    )
    expect(report.get("rollback_policy"), f"{platform} rollback safety report must include policy")
    expect(report.get("software_import_execution_performed") is False, f"{platform} rollback safety must not execute import")
    expect(report.get("editing_software_opened") is False, f"{platform} rollback safety must not open editor")
    expect(report.get("project_file_mutation_performed") is False, f"{platform} rollback safety must not mutate project")


def validate_final_import_manifest(manifest: dict[str, Any], *, expected_boundary: str, default_blocked: bool) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_software_import_bundle_manifest.v1",
        "final import schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_software_import_bundle", "final import type mismatch")
    expect(manifest.get("platforms") == VIDEO_PLATFORMS, "final import platforms mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", "final import validation must pass")
    expect(manifest.get("validation", {}).get("import_item_count", 0) >= 1, "final import item count must be non-empty")
    expect(manifest.get("validation", {}).get("human_software_import_approval_required") is True, "final import must require approval")
    expect(manifest.get("validation", {}).get("software_import_execution_performed") is False, "final import must not execute")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, "final import must not open editor")
    expect(manifest.get("validation", {}).get("project_file_mutation_performed") is False, "final import must not mutate project")
    expect(manifest.get("validation", {}).get("original_project_mutated") is False, "final import must not mutate original")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, "final import must not execute replacement")
    expect(manifest.get("validation", {}).get("isolated_manual_launch_required") is True, "final import must require isolated launch")
    if default_blocked:
        expect(manifest.get("validation", {}).get("human_software_import_approval_present_count") == 0, "default final import approval count should be zero")
        expect(manifest.get("validation", {}).get("human_software_import_approval_valid_count") == 0, "default final import valid approval count should be zero")
        expect(manifest.get("validation", {}).get("ready_for_isolated_manual_import_count") == 0, "default final import ready count should be zero")
    validate_import_boundary(manifest.get("export_boundary", {}), "final import", expected_boundary=expected_boundary)


def validate_import_boundary(boundary: dict[str, Any], label: str, *, expected_boundary: str) -> None:
    expect(boundary.get("editor_software_import_executor") == expected_boundary, f"{label} import boundary mismatch")
    expect(boundary.get("software_import_execution") == "not_performed", f"{label} must not perform software import")
    expect(boundary.get("editing_software") == "not_opened", f"{label} must not open editing software")
    expect(boundary.get("project_file_mutation") == "not_performed_by_executor", f"{label} project mutation policy mismatch")
    expect(boundary.get("original_project_mutation") == "not_performed", f"{label} must not mutate original project")
    expect(boundary.get("replacement_execution") == "not_performed", f"{label} must not execute replacement")
    expect(boundary.get("requires_explicit_human_software_import_approval") is True, f"{label} must require explicit software import approval")
    expect(boundary.get("external_software_isolation") == "required_before_manual_launch", f"{label} must require external software isolation")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} must mark {key} as not_performed")


def validate_platform_package_summary(
    summary: dict[str, Any],
    *,
    platform: str,
    expected_boundary: str,
    default_blocked: bool,
) -> None:
    expect(summary.get("validation_status") == "PASSED", f"{platform} package import summary must pass")
    expect(summary.get("editor_software_import_executor") == expected_boundary, f"{platform} package import boundary mismatch")
    expect(summary.get("import_item_count", 0) >= 1, f"{platform} package import items must be non-empty")
    expect(summary.get("patched_project_exists") is True, f"{platform} package import must see patched project")
    expect(summary.get("rollback_available") is True, f"{platform} package import must see rollback")
    expect(summary.get("human_software_import_approval_required") is True, f"{platform} package must require software import approval")
    expect(summary.get("software_import_execution_performed") is False, f"{platform} package must not execute import")
    expect(summary.get("editing_software_opened") is False, f"{platform} package must not open editor")
    expect(summary.get("project_file_mutation_performed") is False, f"{platform} package must not mutate project")
    if default_blocked:
        expect(summary.get("human_software_import_approval_present") is False, f"{platform} package default approval should be absent")
        expect(summary.get("human_software_import_approval_valid") is False, f"{platform} package default approval should be invalid")
        expect(summary.get("ready_for_isolated_manual_import_count") == 0, f"{platform} package default ready count should be zero")
        expect(summary.get("blocked_pending_approval_count", 0) >= 1, f"{platform} package default pending approval count should be non-empty")


def validate_final_platform_entry(final_entry: dict[str, Any], deliverables: dict[str, str], *, platform: str) -> None:
    expect(final_entry.get("manifest_path") == deliverables["editor_software_import_manifest"], f"{platform} final import manifest path mismatch")
    expect(final_entry.get("import_plan_path") == deliverables["editor_software_import_plan"], f"{platform} final import plan path mismatch")
    expect(final_entry.get("import_commands_path") == deliverables["editor_software_import_commands"], f"{platform} final import commands path mismatch")
    expect(final_entry.get("audit_log_path") == deliverables["editor_software_import_audit_log"], f"{platform} final import audit path mismatch")
    expect(
        final_entry.get("rollback_safety_report_path") == deliverables["editor_software_import_rollback_safety_report"],
        f"{platform} final import rollback safety path mismatch",
    )
    expect(
        final_entry.get("execution_request_path") == deliverables["editor_software_import_execution_request"],
        f"{platform} final import request path mismatch",
    )
    expect(final_entry.get("readme_path") == deliverables["editor_software_import_readme"], f"{platform} final import readme path mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final import validation must pass")
    expect(final_entry.get("validation", {}).get("software_import_execution_performed") is False, f"{platform} final entry must not execute import")
    expect(final_entry.get("validation", {}).get("editing_software_opened") is False, f"{platform} final entry must not open editor")
    expect(final_entry.get("validation", {}).get("project_file_mutation_performed") is False, f"{platform} final entry must not mutate project")


def validate_import_docs(execution_request_path: Path, readme_path: Path, platform: str) -> None:
    request = execution_request_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    expect("Editor Software Import Execution Request" in request, f"{platform} request missing heading")
    expect("No editing software was opened" in request, f"{platform} request missing no-editor boundary")
    expect("Editor Software Import Executor" in readme, f"{platform} README missing heading")
    expect("does not open editing software" in readme, f"{platform} README missing no-editor boundary")


def with_zip_paths(bundle_path: Path, platform: str, required_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in required_paths:
        expect(archive_path in archive_paths, f"{platform} bundle missing software import file: {archive_path}")


def expected_platform_deliverables(platform: str) -> dict[str, str]:
    return {
        "editor_software_import_manifest": f"assets/{platform}/edit/software_import_executor/import_executor_manifest.json",
        "editor_software_import_plan": f"assets/{platform}/edit/software_import_executor/import_plan.json",
        "editor_software_import_commands": f"assets/{platform}/edit/software_import_executor/import_commands.json",
        "editor_software_import_audit_log": f"assets/{platform}/edit/software_import_executor/software_import_audit_log.json",
        "editor_software_import_rollback_safety_report": f"assets/{platform}/edit/software_import_executor/rollback_safety_report.json",
        "editor_software_import_execution_request": f"assets/{platform}/edit/software_import_executor/isolated_execution_request.md",
        "editor_software_import_readme": f"assets/{platform}/edit/software_import_executor/README.md",
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
    validate_workflow_import_steps()
    print("Phase 4 editor software import executor drill passed: workflow import steps")
    validate_default_blocked_run()
    print("Phase 4 editor software import executor drill passed: default blocked import adapter")
    validate_explicit_approval_import_path()
    print("Phase 4 editor software import executor drill passed: explicit approval remains manual and non-executing")
    print("Phase 4 editor software import executor validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
