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
BLOCKED_BOUNDARY = "blocked_pending_explicit_human_real_run_approval"
APPROVED_BOUNDARY = "approved_for_manual_external_sandbox_launch_not_executed"
RUNNER_FILES = {
    "manifest": "runner_sandbox_manifest.json",
    "environment": "runner_environment_snapshot.json",
    "launch_plan": "runner_launch_plan.json",
    "command_preview": "runner_command_preview.json",
    "audit_log": "runner_audit_log.json",
    "evidence": "runner_evidence_manifest.json",
    "approval_request": "human_real_run_approval_request.md",
    "readme": "README.md",
}


def fail(message: str) -> None:
    print(f"Phase 4 editor software real runner sandbox validation failed: {message}", file=sys.stderr)
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


def validate_workflow_runner_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect(
        "final/editor_software_real_runner_manifest.json" in workflow.outputs,
        "workflow must export editor software real runner manifest",
    )

    for platform in VIDEO_PLATFORMS:
        import_step_id = f"{platform}_editor_software_import_executor"
        runner_step_id = f"{platform}_editor_software_real_runner_sandbox"
        bundle_step_id = f"{platform}_project_bundle"
        runner_step = steps.get(runner_step_id)
        bundle_step = steps.get(bundle_step_id)
        expect(runner_step is not None, f"workflow missing step: {runner_step_id}")
        expect(
            runner_step.agent == "editor-software-real-runner-sandbox-agent",
            f"{runner_step_id} must use editor-software-real-runner-sandbox-agent",
        )
        expect(runner_step.platform == platform, f"{runner_step_id} platform mismatch")
        expect(import_step_id in runner_step.depends_on, f"{runner_step_id} must depend on software import executor")
        for filename in RUNNER_FILES.values():
            output_path = f"assets/{platform}/edit/software_real_runner_sandbox/{filename}"
            expect(output_path in runner_step.outputs, f"{runner_step_id} missing output: {output_path}")
        expect(bundle_step is not None, f"workflow missing bundle step for {platform}")
        expect(
            depends_on_transitively(steps, bundle_step_id, runner_step_id),
            f"{bundle_step_id} must be downstream of real runner sandbox",
        )
        expect(runner_step_id in fact_check.depends_on, f"fact_check must depend on {runner_step_id}")


def validate_default_blocked_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 真实软件运行沙盒默认阻断验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/editor_software_real_runner_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor software real runner manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/editor_software_real_runner_manifest.json")
        expect(
            video_package.get("editor_software_real_runner_manifest")
            == "final/editor_software_real_runner_manifest.json",
            "video package must reference editor software real runner manifest",
        )
        expect(
            content_package.get("editor_software_real_runner_manifest")
            == "final/editor_software_real_runner_manifest.json",
            "content package must reference editor software real runner manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("editor_software_real_runner_sandbox") == BLOCKED_BOUNDARY,
            "video package real runner boundary mismatch",
        )
        validate_final_runner_manifest(final_manifest, expected_boundary=BLOCKED_BOUNDARY, default_blocked=True)

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_manifest.get("platform_runners", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            validate_default_platform_runner(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                logs_by_step=logs_by_step,
                package=packages.get(platform),
                final_entry=final_entries.get(platform),
            )


def validate_default_platform_runner(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    logs_by_step: dict[str, Any],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_editor_software_real_runner_sandbox"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    expect(metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
    expect(metadata.get("editor_software_real_runner_status") == "PASSED", f"{step_id} status must pass")
    expect(metadata.get("human_real_run_approval_required") is True, f"{step_id} must require approval")
    expect(metadata.get("human_real_run_approval_present") is False, f"{step_id} default run must not have approval")
    expect(metadata.get("real_software_launch_performed") is False, f"{step_id} must not launch software")
    expect(metadata.get("process_spawned") is False, f"{step_id} must not spawn process")
    expect(metadata.get("editing_software_opened") is False, f"{step_id} must not open editor")
    expect(metadata.get("project_file_mutation_performed") is False, f"{step_id} must not mutate project")

    base = run_dir / "assets" / platform / "edit" / "software_real_runner_sandbox"
    manifest = load_json(base / "runner_sandbox_manifest.json")
    launch_plan = load_json(base / "runner_launch_plan.json")
    command_preview = load_json(base / "runner_command_preview.json")
    audit_log = load_json(base / "runner_audit_log.json")
    evidence_manifest = load_json(base / "runner_evidence_manifest.json")
    environment_snapshot = load_json(base / "runner_environment_snapshot.json")
    approval_request_path = base / "human_real_run_approval_request.md"
    readme_path = base / "README.md"
    for path in [approval_request_path, readme_path]:
        expect(path.exists(), f"{platform} real runner doc missing: {path.relative_to(run_dir)}")

    validate_platform_runner_manifest(manifest, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_launch_plan(launch_plan, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_command_preview(command_preview, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_runner_audit_log(audit_log, platform=platform, expected_boundary=BLOCKED_BOUNDARY)
    validate_environment_snapshot(environment_snapshot, platform=platform)
    validate_evidence_manifest(evidence_manifest, platform=platform)
    validate_runner_docs(approval_request_path, readme_path, platform=platform)

    expect(manifest.get("summary", {}).get("ready_for_manual_external_sandbox_launch_count") == 0, f"{platform} default runner should not be ready")
    expect(manifest.get("summary", {}).get("blocked_runner_count", 0) >= 1, f"{platform} default runner should block items")
    statuses = {item.get("real_run_status") for item in manifest.get("runner_items", []) if isinstance(item, dict)}
    expect("ready_for_manual_external_sandbox_launch" not in statuses, f"{platform} default runner must not be ready")

    with_zip_paths(
        run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
        platform,
        [
            "software_real_runner_sandbox/runner_sandbox_manifest.json",
            "software_real_runner_sandbox/runner_environment_snapshot.json",
            "software_real_runner_sandbox/runner_launch_plan.json",
            "software_real_runner_sandbox/runner_command_preview.json",
            "software_real_runner_sandbox/runner_audit_log.json",
            "software_real_runner_sandbox/runner_evidence_manifest.json",
            "software_real_runner_sandbox/human_real_run_approval_request.md",
            "software_real_runner_sandbox/README.md",
        ],
    )

    expected_deliverables = expected_platform_deliverables(platform)
    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    for key, expected_path in expected_deliverables.items():
        expect(deliverables.get(key) == expected_path, f"{platform} package deliverable mismatch: {key}")
        expect((run_dir / expected_path).exists(), f"{platform} package deliverable path missing: {expected_path}")
    summary = package.get("editor_software_real_runner_sandbox", {})
    validate_platform_package_summary(summary, platform=platform, expected_boundary=BLOCKED_BOUNDARY, default_blocked=True)
    expect(isinstance(final_entry, dict), f"final real runner manifest missing platform: {platform}")
    validate_final_platform_entry(final_entry, expected_deliverables, platform=platform)


def validate_explicit_approval_runner_path() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 显式批准真实软件运行沙盒验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        platform = "douyin"
        asset_id = first_materialized_asset_id(run_dir, platform)
        source_media_path = f"assets/{platform}/licensed_media/human_supplied/{asset_id}_final.txt"
        source_media = run_dir / source_media_path
        source_media.parent.mkdir(parents=True, exist_ok=True)
        source_media.write_text(f"self-created real runner fixture for {asset_id}\n", encoding="utf-8")
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
            topic="Phase 4 显式批准真实软件运行沙盒验收",
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
        for agent_id in ["editor-software-real-runner-sandbox-agent", "project-bundle-agent"]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        base = run_dir / "assets" / platform / "edit" / "software_real_runner_sandbox"
        manifest = load_json(base / "runner_sandbox_manifest.json")
        launch_plan = load_json(base / "runner_launch_plan.json")
        command_preview = load_json(base / "runner_command_preview.json")
        audit_log = load_json(base / "runner_audit_log.json")

        validate_platform_runner_manifest(manifest, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_launch_plan(launch_plan, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_command_preview(command_preview, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        validate_runner_audit_log(audit_log, platform=platform, expected_boundary=APPROVED_BOUNDARY)
        expect(manifest.get("human_real_run_approval_present") is True, "approved runner should record approval presence")
        expect(manifest.get("human_real_run_approval_valid") is True, "approved runner should validate approval")
        expect(
            manifest.get("summary", {}).get("ready_for_manual_external_sandbox_launch_count", 0) >= 1,
            "approved runner should expose at least one ready item",
        )
        item = find_by_asset_id(manifest.get("runner_items", []), asset_id)
        expect(item.get("real_run_status") == "ready_for_manual_external_sandbox_launch", "approved asset runner status mismatch")
        expect(item.get("real_software_launch_performed") is False, "approved runner must still not launch software")
        expect(item.get("process_spawned") is False, "approved runner must still not spawn process")
        expect(item.get("editing_software_opened") is False, "approved runner must still not open editor")
        command = find_by_asset_id(command_preview.get("commands", []), asset_id)
        expect(command.get("execution_status") == "ready_for_manual_external_sandbox_launch", "approved runner command status mismatch")
        expect(command.get("dry_run_only") is True, "approved runner command must remain dry-run")
        expect(command.get("auto_execute") is False, "approved runner command must not auto-execute")
        expect(command.get("real_software_launch_performed") is False, "approved runner command must not launch software")

        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "software_real_runner_sandbox/runner_sandbox_manifest.json",
                "software_real_runner_sandbox/runner_environment_snapshot.json",
                "software_real_runner_sandbox/runner_launch_plan.json",
                "software_real_runner_sandbox/runner_command_preview.json",
                "software_real_runner_sandbox/runner_audit_log.json",
                "software_real_runner_sandbox/runner_evidence_manifest.json",
                "software_real_runner_sandbox/human_real_run_approval_request.md",
                "software_real_runner_sandbox/human_real_run_approval.json",
                "software_real_runner_sandbox/README.md",
            ],
        )


def validate_platform_runner_manifest(manifest: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_software_real_runner_sandbox_manifest.v1",
        f"{platform} real runner schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_software_real_runner_sandbox", f"{platform} real runner type mismatch")
    expect(manifest.get("adapter") == "local-editor-software-real-runner-sandbox-adapter", f"{platform} real runner adapter mismatch")
    expect(manifest.get("platform") == platform, f"{platform} real runner platform mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} real runner validation must pass")
    expect(manifest.get("manual_review_required") is True, f"{platform} real runner manifest must require review")
    expect(manifest.get("human_real_run_approval_required") is True, f"{platform} real runner must require approval")
    expect(manifest.get("validation", {}).get("real_software_launch_performed") is False, f"{platform} must not launch software")
    expect(manifest.get("validation", {}).get("software_import_execution_performed") is False, f"{platform} must not import")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, f"{platform} must not open editor")
    expect(manifest.get("validation", {}).get("project_file_mutation_performed") is False, f"{platform} must not mutate project")
    expect(manifest.get("validation", {}).get("process_spawned") is False, f"{platform} must not spawn process")
    validate_runner_boundary(manifest.get("export_boundary", {}), platform, expected_boundary=expected_boundary)
    items = manifest.get("runner_items", [])
    summary = manifest.get("summary", {})
    expect(isinstance(items, list) and items, f"{platform} runner items must be non-empty")
    expect(summary.get("runner_item_count") == len(items), f"{platform} runner item count mismatch")
    for item in items:
        expect(item.get("real_software_launch_performed") is False, f"{platform} item must not launch software")
        expect(item.get("software_import_execution_performed") is False, f"{platform} item must not execute import")
        expect(item.get("editing_software_opened") is False, f"{platform} item must not open editor")
        expect(item.get("project_file_mutation_performed") is False, f"{platform} item must not mutate project")
        expect(item.get("process_spawned") is False, f"{platform} item must not spawn process")
        expect(item.get("upload_performed") is False, f"{platform} item must not upload")
        expect(item.get("publishing_performed") is False, f"{platform} item must not publish")


def validate_launch_plan(plan: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        plan.get("schema_version") == "phase4.editor_software_real_runner_launch_plan.v1",
        f"{platform} real runner launch plan schema mismatch",
    )
    expect(plan.get("artifact_type") == "editor_software_real_runner_launch_plan", f"{platform} real runner launch plan type mismatch")
    expect(plan.get("platform") == platform, f"{platform} real runner launch plan platform mismatch")
    validate_runner_boundary(plan.get("export_boundary", {}), f"{platform} launch plan", expected_boundary=expected_boundary)
    expect(isinstance(plan.get("runner_items"), list) and plan["runner_items"], f"{platform} launch plan must include runner items")
    validate_command_list(plan.get("launch_commands", []), platform=platform)


def validate_command_preview(command_preview: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        command_preview.get("schema_version") == "phase4.editor_software_real_runner_command_preview.v1",
        f"{platform} real runner command preview schema mismatch",
    )
    expect(command_preview.get("artifact_type") == "editor_software_real_runner_command_preview", f"{platform} real runner command preview type mismatch")
    validate_runner_boundary(command_preview.get("export_boundary", {}), f"{platform} command preview", expected_boundary=expected_boundary)
    validate_command_list(command_preview.get("commands", []), platform=platform)


def validate_command_list(commands: Any, *, platform: str) -> None:
    expect(isinstance(commands, list) and commands, f"{platform} real runner commands must be non-empty")
    for command in commands:
        expect(command.get("command_type") == "editor_software_real_runner_sandbox", f"{platform} real runner command type mismatch")
        expect(command.get("external_sandbox_required") is True, f"{platform} command must require external sandbox")
        expect(command.get("auto_execute") is False, f"{platform} command must not auto-execute")
        expect(command.get("dry_run_only") is True, f"{platform} command must be dry-run")
        expect(command.get("human_real_run_approval_required") is True, f"{platform} command must require approval")
        expect(command.get("real_software_launch_performed") is False, f"{platform} command must not launch software")
        expect(command.get("software_import_execution_performed") is False, f"{platform} command must not execute import")
        expect(command.get("editing_software_opened") is False, f"{platform} command must not open editor")
        expect(command.get("project_file_mutation_performed") is False, f"{platform} command must not mutate project")
        expect(command.get("process_spawned") is False, f"{platform} command must not spawn process")
        expect(command.get("upload_performed") is False, f"{platform} command must not upload")
        expect(command.get("publishing_performed") is False, f"{platform} command must not publish")


def validate_runner_audit_log(audit_log: dict[str, Any], *, platform: str, expected_boundary: str) -> None:
    expect(
        audit_log.get("schema_version") == "phase4.editor_software_real_runner_audit_log.v1",
        f"{platform} real runner audit schema mismatch",
    )
    expect(audit_log.get("artifact_type") == "editor_software_real_runner_audit_log", f"{platform} real runner audit type mismatch")
    validate_runner_boundary(audit_log.get("export_boundary", {}), f"{platform} audit", expected_boundary=expected_boundary)
    events = audit_log.get("events", [])
    expect(isinstance(events, list) and events, f"{platform} real runner audit events must be non-empty")
    for event in events:
        expect(event.get("real_software_launch_performed") is False, f"{platform} audit must not record launch")
        expect(event.get("software_import_execution_performed") is False, f"{platform} audit must not record import")
        expect(event.get("editing_software_opened") is False, f"{platform} audit must not record editor open")
        expect(event.get("project_file_mutation_performed") is False, f"{platform} audit must not record mutation")
        expect(event.get("process_spawned") is False, f"{platform} audit must not record process spawn")


def validate_environment_snapshot(snapshot: dict[str, Any], *, platform: str) -> None:
    expect(
        snapshot.get("schema_version") == "phase4.editor_software_real_runner_environment_snapshot.v1",
        f"{platform} environment snapshot schema mismatch",
    )
    expect(snapshot.get("artifact_type") == "editor_software_real_runner_environment_snapshot", f"{platform} environment snapshot type mismatch")
    expect(snapshot.get("platform") == platform, f"{platform} environment snapshot platform mismatch")
    expect(snapshot.get("validation", {}).get("real_software_launch_performed") is False, f"{platform} environment must not launch")
    expect(snapshot.get("validation", {}).get("process_spawned") is False, f"{platform} environment must not spawn process")


def validate_evidence_manifest(evidence: dict[str, Any], *, platform: str) -> None:
    expect(
        evidence.get("schema_version") == "phase4.editor_software_real_runner_evidence_manifest.v1",
        f"{platform} evidence manifest schema mismatch",
    )
    expect(evidence.get("artifact_type") == "editor_software_real_runner_evidence_manifest", f"{platform} evidence manifest type mismatch")
    expect(evidence.get("evidence_collection_status") == "not_started_no_real_software_launch", f"{platform} evidence status mismatch")
    expect(evidence.get("real_software_launch_performed") is False, f"{platform} evidence must not launch")
    expect(evidence.get("software_import_execution_performed") is False, f"{platform} evidence must not import")
    expect(evidence.get("editing_software_opened") is False, f"{platform} evidence must not open editor")
    expect(evidence.get("project_file_mutation_performed") is False, f"{platform} evidence must not mutate project")


def validate_final_runner_manifest(manifest: dict[str, Any], *, expected_boundary: str, default_blocked: bool) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_software_real_runner_bundle_manifest.v1",
        "final real runner schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_software_real_runner_bundle", "final real runner type mismatch")
    expect(manifest.get("platforms") == VIDEO_PLATFORMS, "final real runner platforms mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", "final real runner validation must pass")
    expect(manifest.get("validation", {}).get("runner_item_count", 0) >= 1, "final real runner item count must be non-empty")
    expect(manifest.get("validation", {}).get("human_real_run_approval_required") is True, "final real runner must require approval")
    expect(manifest.get("validation", {}).get("real_software_launch_performed") is False, "final real runner must not launch")
    expect(manifest.get("validation", {}).get("software_import_execution_performed") is False, "final real runner must not import")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, "final real runner must not open editor")
    expect(manifest.get("validation", {}).get("project_file_mutation_performed") is False, "final real runner must not mutate project")
    expect(manifest.get("validation", {}).get("process_spawned") is False, "final real runner must not spawn process")
    expect(manifest.get("validation", {}).get("manual_external_launch_required") is True, "final real runner must require manual launch")
    if default_blocked:
        expect(manifest.get("validation", {}).get("human_real_run_approval_present_count") == 0, "default final real runner approval count should be zero")
        expect(manifest.get("validation", {}).get("human_real_run_approval_valid_count") == 0, "default final real runner valid approval count should be zero")
        expect(manifest.get("validation", {}).get("ready_for_manual_external_sandbox_launch_count") == 0, "default final real runner ready count should be zero")
    validate_runner_boundary(manifest.get("export_boundary", {}), "final real runner", expected_boundary=expected_boundary)


def validate_runner_boundary(boundary: dict[str, Any], label: str, *, expected_boundary: str) -> None:
    expect(boundary.get("editor_software_real_runner_sandbox") == expected_boundary, f"{label} real runner boundary mismatch")
    expect(boundary.get("real_software_launch") == "not_performed", f"{label} must not launch software")
    expect(boundary.get("software_import_execution") == "not_performed", f"{label} must not execute software import")
    expect(boundary.get("editing_software") == "not_opened", f"{label} must not open editing software")
    expect(boundary.get("project_file_mutation") == "not_performed_by_runner", f"{label} project mutation policy mismatch")
    expect(boundary.get("original_project_mutation") == "not_performed", f"{label} must not mutate original project")
    expect(boundary.get("replacement_execution") == "not_performed", f"{label} must not execute replacement")
    expect(boundary.get("requires_explicit_human_real_run_approval") is True, f"{label} must require explicit real-run approval")
    expect(boundary.get("external_process_isolation") == "required_before_human_launch", f"{label} must require external process isolation")
    expect(boundary.get("process_spawn") == "not_performed", f"{label} must not spawn process")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} must mark {key} as not_performed")


def validate_platform_package_summary(
    summary: dict[str, Any],
    *,
    platform: str,
    expected_boundary: str,
    default_blocked: bool,
) -> None:
    expect(summary.get("validation_status") == "PASSED", f"{platform} package real runner summary must pass")
    expect(summary.get("editor_software_real_runner_sandbox") == expected_boundary, f"{platform} package real runner boundary mismatch")
    expect(summary.get("runner_item_count", 0) >= 1, f"{platform} package real runner items must be non-empty")
    expect(summary.get("human_real_run_approval_required") is True, f"{platform} package must require real run approval")
    expect(summary.get("real_software_launch_performed") is False, f"{platform} package must not launch software")
    expect(summary.get("software_import_execution_performed") is False, f"{platform} package must not import")
    expect(summary.get("editing_software_opened") is False, f"{platform} package must not open editor")
    expect(summary.get("project_file_mutation_performed") is False, f"{platform} package must not mutate project")
    expect(summary.get("process_spawned") is False, f"{platform} package must not spawn process")
    if default_blocked:
        expect(summary.get("human_real_run_approval_present") is False, f"{platform} package default approval should be absent")
        expect(summary.get("human_real_run_approval_valid") is False, f"{platform} package default approval should be invalid")
        expect(summary.get("ready_for_manual_external_sandbox_launch_count") == 0, f"{platform} package default ready count should be zero")
        expect(summary.get("blocked_runner_count", 0) >= 1, f"{platform} package default blocked count should be non-empty")


def validate_final_platform_entry(final_entry: dict[str, Any], deliverables: dict[str, str], *, platform: str) -> None:
    expect(final_entry.get("manifest_path") == deliverables["editor_software_real_runner_manifest"], f"{platform} final runner manifest path mismatch")
    expect(final_entry.get("environment_snapshot_path") == deliverables["editor_software_real_runner_environment_snapshot"], f"{platform} final runner environment path mismatch")
    expect(final_entry.get("launch_plan_path") == deliverables["editor_software_real_runner_launch_plan"], f"{platform} final runner launch plan path mismatch")
    expect(final_entry.get("command_preview_path") == deliverables["editor_software_real_runner_command_preview"], f"{platform} final runner command preview path mismatch")
    expect(final_entry.get("audit_log_path") == deliverables["editor_software_real_runner_audit_log"], f"{platform} final runner audit path mismatch")
    expect(final_entry.get("evidence_manifest_path") == deliverables["editor_software_real_runner_evidence_manifest"], f"{platform} final runner evidence path mismatch")
    expect(final_entry.get("approval_request_path") == deliverables["editor_software_real_runner_approval_request"], f"{platform} final runner approval request path mismatch")
    expect(final_entry.get("readme_path") == deliverables["editor_software_real_runner_readme"], f"{platform} final runner readme path mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final runner validation must pass")
    expect(final_entry.get("validation", {}).get("real_software_launch_performed") is False, f"{platform} final entry must not launch")
    expect(final_entry.get("validation", {}).get("software_import_execution_performed") is False, f"{platform} final entry must not import")
    expect(final_entry.get("validation", {}).get("editing_software_opened") is False, f"{platform} final entry must not open editor")
    expect(final_entry.get("validation", {}).get("project_file_mutation_performed") is False, f"{platform} final entry must not mutate project")
    expect(final_entry.get("validation", {}).get("process_spawned") is False, f"{platform} final entry must not spawn process")


def validate_runner_docs(approval_request_path: Path, readme_path: Path, *, platform: str) -> None:
    request = approval_request_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    expect("Editor Software Real Runner Sandbox Approval Request" in request, f"{platform} request missing heading")
    expect("did not launch editing software" in request, f"{platform} request missing no-launch boundary")
    expect("Editor Software Real Runner Sandbox" in readme, f"{platform} README missing heading")
    expect("does not open editing software" in readme, f"{platform} README missing no-editor boundary")


def with_zip_paths(bundle_path: Path, platform: str, required_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in required_paths:
        expect(archive_path in archive_paths, f"{platform} bundle missing real runner file: {archive_path}")


def expected_platform_deliverables(platform: str) -> dict[str, str]:
    return {
        "editor_software_real_runner_manifest": f"assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json",
        "editor_software_real_runner_environment_snapshot": f"assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json",
        "editor_software_real_runner_launch_plan": f"assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json",
        "editor_software_real_runner_command_preview": f"assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json",
        "editor_software_real_runner_audit_log": f"assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json",
        "editor_software_real_runner_evidence_manifest": f"assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json",
        "editor_software_real_runner_approval_request": f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md",
        "editor_software_real_runner_readme": f"assets/{platform}/edit/software_real_runner_sandbox/README.md",
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
    validate_workflow_runner_steps()
    print("Phase 4 editor software real runner sandbox drill passed: workflow runner steps")
    validate_default_blocked_run()
    print("Phase 4 editor software real runner sandbox drill passed: default blocked runner sandbox")
    validate_explicit_approval_runner_path()
    print("Phase 4 editor software real runner sandbox drill passed: explicit approval remains manual and non-executing")
    print("Phase 4 editor software real runner sandbox validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
