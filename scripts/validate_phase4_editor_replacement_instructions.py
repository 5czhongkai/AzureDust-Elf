from __future__ import annotations

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
INSTRUCTION_BOUNDARY = "performed_locally_template_and_instruction_only"
INSTRUCTION_FILES = {
    "instruction_manifest": "instruction_manifest.json",
    "replacement_commands": "replacement_commands.json",
    "editor_import_template_fcpxml": "editor_import_template.fcpxml",
    "human_confirmation_checklist": "human_confirmation_checklist.md",
    "readme": "README.md",
}


def fail(message: str) -> None:
    print(f"Phase 4 editor replacement instructions validation failed: {message}", file=sys.stderr)
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


def depends_on_transitively(steps: dict[str, Any], step_id: str, required_dependency_id: str) -> bool:
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


def validate_workflow_instruction_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect(
        "final/editor_replacement_instruction_manifest.json" in workflow.outputs,
        "workflow must export editor replacement instruction manifest",
    )

    for platform in VIDEO_PLATFORMS:
        export_step_id = f"{platform}_export_project"
        proxy_step_id = f"{platform}_licensed_media_proxy"
        instruction_step_id = f"{platform}_editor_replacement_instructions"
        execution_step_id = f"{platform}_editor_replacement_execution"
        bundle_step_id = f"{platform}_project_bundle"
        instruction_step = steps.get(instruction_step_id)
        execution_step = steps.get(execution_step_id)
        bundle_step = steps.get(bundle_step_id)

        expect(instruction_step is not None, f"workflow missing step: {instruction_step_id}")
        expect(
            instruction_step.agent == "editor-replacement-instructions-agent",
            f"{instruction_step_id} must use editor-replacement-instructions-agent",
        )
        expect(instruction_step.platform == platform, f"{instruction_step_id} platform mismatch")
        expect(export_step_id in instruction_step.depends_on, f"{instruction_step_id} must depend on export project")
        expect(proxy_step_id in instruction_step.depends_on, f"{instruction_step_id} must depend on licensed media proxy")
        for filename in INSTRUCTION_FILES.values():
            output_path = f"assets/{platform}/edit/replacement_instructions/{filename}"
            expect(output_path in instruction_step.outputs, f"{instruction_step_id} missing output: {output_path}")

        expect(execution_step is not None, f"workflow missing execution step for {platform}")
        expect(
            execution_step.agent == "editor-replacement-execution-agent",
            f"{execution_step_id} must use editor-replacement-execution-agent",
        )
        expect(instruction_step_id in execution_step.depends_on, f"{execution_step_id} must depend on editor instructions")
        expect(bundle_step is not None, f"workflow missing bundle step for {platform}")
        expect(
            depends_on_transitively(steps, bundle_step_id, instruction_step_id),
            f"{bundle_step_id} must be downstream of editor instructions",
        )
        expect(instruction_step_id in fact_check.depends_on, f"fact_check must depend on {instruction_step_id}")


def validate_default_no_registry_run() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 剪辑替换指令验收",
            platforms=VIDEO_PLATFORMS,
            output_root=Path(tmp) / "runs",
        )

        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/editor_replacement_instruction_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing editor replacement instruction manifest",
        )
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }

        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/editor_replacement_instruction_manifest.json")

        expect(
            video_package.get("editor_replacement_instruction_manifest")
            == "final/editor_replacement_instruction_manifest.json",
            "video package must reference editor replacement instruction manifest",
        )
        expect(
            content_package.get("editor_replacement_instruction_manifest")
            == "final/editor_replacement_instruction_manifest.json",
            "content package must reference editor replacement instruction manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("editor_replacement_instructions") == INSTRUCTION_BOUNDARY,
            "video package editor instruction boundary mismatch",
        )
        validate_final_instruction_manifest(final_manifest, default_pending=True)

        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_entries = {
            item.get("platform"): item
            for item in final_manifest.get("platform_instructions", [])
            if isinstance(item, dict)
        }
        for platform in VIDEO_PLATFORMS:
            validate_default_platform_instructions(
                run_dir=run_dir,
                platform=platform,
                modes_by_step=modes_by_step,
                logs_by_step=logs_by_step,
                package=packages.get(platform),
                final_entry=final_entries.get(platform),
            )


def validate_default_platform_instructions(
    *,
    run_dir: Path,
    platform: str,
    modes_by_step: dict[str, str | None],
    logs_by_step: dict[str, Any],
    package: dict[str, Any] | None,
    final_entry: dict[str, Any] | None,
) -> None:
    step_id = f"{platform}_editor_replacement_instructions"
    expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    expect(metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
    expect(metadata.get("editor_replacement_instruction_status") == "PASSED", f"{step_id} status must pass")
    expect(metadata.get("human_confirmation_gate_active") is True, f"{step_id} must keep human gate active")
    expect(metadata.get("replacement_execution_performed") is False, f"{step_id} must not execute replacement")

    base = run_dir / "assets" / platform / "edit" / "replacement_instructions"
    manifest = load_json(base / "instruction_manifest.json")
    commands = load_json(base / "replacement_commands.json")
    fcpxml_path = base / "editor_import_template.fcpxml"
    checklist_path = base / "human_confirmation_checklist.md"
    readme_path = base / "README.md"
    for path in [fcpxml_path, checklist_path, readme_path]:
        expect(path.exists(), f"{platform} editor instruction file missing: {path.relative_to(run_dir)}")

    validate_platform_instruction_manifest(manifest, platform=platform, default_pending=True)
    validate_replacement_commands(commands, platform=platform, expected_count=manifest["summary"]["instruction_count"])
    validate_fcpxml(fcpxml_path, platform)
    validate_instruction_docs(checklist_path, readme_path, platform)

    with_zip_paths(
        run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
        platform,
        [
            "replacement_instructions/instruction_manifest.json",
            "replacement_instructions/replacement_commands.json",
            "replacement_instructions/editor_import_template.fcpxml",
            "replacement_instructions/human_confirmation_checklist.md",
            "replacement_instructions/README.md",
        ],
    )

    expect(isinstance(package, dict), f"video package missing platform: {platform}")
    deliverables = package.get("deliverables", {})
    expected_deliverables = {
        "editor_replacement_instruction_manifest": f"assets/{platform}/edit/replacement_instructions/instruction_manifest.json",
        "editor_replacement_commands": f"assets/{platform}/edit/replacement_instructions/replacement_commands.json",
        "editor_import_template_fcpxml": f"assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml",
        "editor_human_confirmation_checklist": f"assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md",
        "editor_replacement_readme": f"assets/{platform}/edit/replacement_instructions/README.md",
    }
    for key, expected_path in expected_deliverables.items():
        expect(deliverables.get(key) == expected_path, f"{platform} package deliverable mismatch: {key}")
        expect((run_dir / expected_path).exists(), f"{platform} package deliverable path missing: {expected_path}")

    summary = package.get("editor_replacement_instructions", {})
    expect(summary.get("validation_status") == "PASSED", f"{platform} package editor instructions must pass")
    expect(summary.get("instruction_count", 0) >= 1, f"{platform} package editor instructions must be non-empty")
    expect(summary.get("ready_pending_human_confirmation_count") == 0, f"{platform} default run should have no ready commands")
    expect(summary.get("pending_human_media_count", 0) >= 1, f"{platform} default run should keep pending media")
    expect(summary.get("human_confirmation_gate_active") is True, f"{platform} package must keep human gate active")
    expect(summary.get("replacement_execution_performed") is False, f"{platform} package must not execute replacement")
    expect(summary.get("editing_software_opened") is False, f"{platform} package must not open editing software")

    expect(isinstance(final_entry, dict), f"final instruction manifest missing platform: {platform}")
    expect(final_entry.get("manifest_path") == expected_deliverables["editor_replacement_instruction_manifest"], f"{platform} final instruction manifest path mismatch")
    expect(final_entry.get("replacement_commands_path") == expected_deliverables["editor_replacement_commands"], f"{platform} final commands path mismatch")
    expect(final_entry.get("editor_import_template_path") == expected_deliverables["editor_import_template_fcpxml"], f"{platform} final import template path mismatch")
    expect(final_entry.get("human_confirmation_checklist_path") == expected_deliverables["editor_human_confirmation_checklist"], f"{platform} final checklist path mismatch")
    expect(final_entry.get("readme_path") == expected_deliverables["editor_replacement_readme"], f"{platform} final readme path mismatch")
    expect(final_entry.get("validation", {}).get("status") == "PASSED", f"{platform} final instruction validation must pass")
    expect(final_entry.get("validation", {}).get("human_confirmation_gate_active") is True, f"{platform} final entry must keep human gate active")
    expect(final_entry.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} final entry must not execute replacement")


def validate_human_registry_ready_instructions() -> None:
    with TemporaryDirectory() as tmp:
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 人工素材剪辑替换指令验收",
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
        source_media.write_text(f"self-created editor instruction fixture for {asset_id}\n", encoding="utf-8")
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
            topic="Phase 4 人工素材剪辑替换指令验收",
            platforms=VIDEO_PLATFORMS,
            produced_artifacts=[],
        )
        for agent_id in [
            "licensed-media-ingest-agent",
            "licensed-media-proxy-agent",
            "edit-project-agent",
            "export-project-agent",
            "editor-replacement-instructions-agent",
            "project-bundle-agent",
        ]:
            result = run_agent({"agent": agent_id, "metadata": {"platform": platform}}, ctx)
            write_agent_outputs(run_dir, result.outputs)

        proxy_manifest = load_json(run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json")
        instruction_manifest = load_json(
            run_dir / "assets" / platform / "edit" / "replacement_instructions" / "instruction_manifest.json"
        )
        replacement_commands = load_json(
            run_dir / "assets" / platform / "edit" / "replacement_instructions" / "replacement_commands.json"
        )
        proxy_asset = _find_by_asset_id(proxy_manifest.get("proxy_assets", []), asset_id)
        instruction = _find_by_asset_id(instruction_manifest.get("instructions", []), asset_id)
        command = _find_by_asset_id(replacement_commands.get("commands", []), asset_id)

        expect(proxy_asset.get("replacement_status") == "proxy_ready_for_editor_replacement", "proxy should be ready")
        expect(instruction.get("instruction_status") == "ready_pending_human_confirmation", "ready instruction status mismatch")
        expect(instruction.get("can_execute_after_human_confirmation") is True, "ready instruction should be executable only after confirmation")
        expect(instruction.get("human_confirmation_required") is True, "ready instruction must require confirmation")
        expect(instruction.get("confirmation_gate_status") == "pending_human_confirmation", "ready instruction gate mismatch")
        expect(instruction.get("execution_status") == "not_executed", "ready instruction must not be executed")
        expect(instruction.get("editing_software_opened") is False, "ready instruction must not open editing software")
        expect(instruction.get("proxy_media_path") == proxy_asset.get("proxy_media_path"), "ready instruction proxy path mismatch")
        expect(command.get("dry_run_only") is True, "ready command must stay dry-run")
        expect(command.get("execution_status") == "not_executed", "ready command must not execute")
        expect(command.get("can_execute_after_human_confirmation") is True, "ready command should only become executable after confirmation")
        validate_platform_instruction_manifest(instruction_manifest, platform=platform, default_pending=False)
        validate_replacement_commands(
            replacement_commands,
            platform=platform,
            expected_count=instruction_manifest["summary"]["instruction_count"],
        )
        validate_fcpxml(run_dir / instruction_manifest["editor_import_template_path"], platform)
        with_zip_paths(
            run_dir / "assets" / platform / "bundle" / "project_bundle.zip",
            platform,
            [
                "replacement_instructions/instruction_manifest.json",
                "replacement_instructions/replacement_commands.json",
                "replacement_instructions/editor_import_template.fcpxml",
                "replacement_instructions/human_confirmation_checklist.md",
                "replacement_instructions/README.md",
            ],
        )


def validate_platform_instruction_manifest(manifest: dict[str, Any], *, platform: str, default_pending: bool) -> None:
    expect(manifest.get("schema_version") == "phase4.editor_replacement_instruction_manifest.v1", f"{platform} instruction schema mismatch")
    expect(manifest.get("artifact_type") == "editor_replacement_instructions", f"{platform} instruction artifact type mismatch")
    expect(manifest.get("adapter") == "local-editor-replacement-instruction-adapter", f"{platform} instruction adapter mismatch")
    expect(manifest.get("platform") == platform, f"{platform} instruction platform mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} instruction validation must pass")
    expect(manifest.get("manual_review_required") is True, f"{platform} instruction manifest must require manual review")
    expect(manifest.get("human_confirmation_required") is True, f"{platform} instruction manifest must require confirmation")
    validate_instruction_boundary(manifest.get("export_boundary", {}), platform)

    instructions = manifest.get("instructions", [])
    summary = manifest.get("summary", {})
    expect(isinstance(instructions, list) and instructions, f"{platform} instructions must be non-empty")
    expect(summary.get("instruction_count") == len(instructions), f"{platform} instruction count mismatch")
    expect(summary.get("human_confirmation_required_count") == len(instructions), f"{platform} all instructions must require confirmation")
    expect(manifest.get("validation", {}).get("human_confirmation_gate_active") is True, f"{platform} human gate must be active")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, f"{platform} replacement must not execute")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, f"{platform} editor must not open")
    for instruction in instructions:
        expect(instruction.get("human_confirmation_required") is True, f"{platform} instruction must require confirmation")
        expect(instruction.get("confirmation_gate_status") == "pending_human_confirmation", f"{platform} confirmation gate mismatch")
        expect(instruction.get("execution_status") == "not_executed", f"{platform} instruction must not execute")
        expect(instruction.get("editing_software_opened") is False, f"{platform} instruction must not open editor")
        if instruction.get("instruction_status") == "ready_pending_human_confirmation":
            expect(instruction.get("proxy_media_exists") is True, f"{platform} ready instruction must have proxy media")
            expect(instruction.get("can_execute_after_human_confirmation") is True, f"{platform} ready instruction should be gated executable")
        else:
            expect(instruction.get("can_execute_after_human_confirmation") is False, f"{platform} non-ready instruction must not be executable")
    if default_pending:
        expect(summary.get("ready_pending_human_confirmation_count") == 0, f"{platform} default run should have no ready instructions")
        expect(summary.get("pending_human_media_count", 0) >= 1, f"{platform} default run should keep pending media")
        expect(summary.get("executable_after_human_confirmation_count") == 0, f"{platform} default run should have no executable commands")
    else:
        expect(summary.get("ready_pending_human_confirmation_count", 0) >= 1, f"{platform} ready run should produce ready instructions")
        expect(summary.get("executable_after_human_confirmation_count", 0) >= 1, f"{platform} ready run should produce gated commands")


def validate_replacement_commands(commands: dict[str, Any], *, platform: str, expected_count: int) -> None:
    expect(commands.get("schema_version") == "phase4.editor_replacement_commands.v1", f"{platform} commands schema mismatch")
    expect(commands.get("artifact_type") == "editor_replacement_commands", f"{platform} commands artifact type mismatch")
    expect(commands.get("platform") == platform, f"{platform} commands platform mismatch")
    expect(commands.get("validation", {}).get("status") == "PASSED", f"{platform} commands validation must pass")
    validate_instruction_boundary(commands.get("export_boundary", {}), f"{platform} commands")
    items = commands.get("commands", [])
    expect(isinstance(items, list) and len(items) == expected_count, f"{platform} commands count mismatch")
    for command in items:
        expect(command.get("command_type") == "nle_broll_replacement", f"{platform} command type mismatch")
        expect(command.get("target_editor") == "fcpxml_compatible_editor", f"{platform} command target editor mismatch")
        expect(command.get("dry_run_only") is True, f"{platform} command must be dry-run only")
        expect(command.get("human_confirmation_required") is True, f"{platform} command must require confirmation")
        expect(command.get("confirmation_gate_status") == "pending_human_confirmation", f"{platform} command gate mismatch")
        expect(command.get("execution_status") == "not_executed", f"{platform} command must not execute")


def validate_final_instruction_manifest(manifest: dict[str, Any], *, default_pending: bool) -> None:
    expect(
        manifest.get("schema_version") == "phase4.editor_replacement_instruction_bundle_manifest.v1",
        "final editor instruction schema mismatch",
    )
    expect(manifest.get("artifact_type") == "editor_replacement_instruction_bundle", "final editor instruction type mismatch")
    expect(manifest.get("platforms") == VIDEO_PLATFORMS, "final editor instruction platforms mismatch")
    expect(manifest.get("validation", {}).get("status") == "PASSED", "final editor instruction validation must pass")
    expect(manifest.get("validation", {}).get("human_confirmation_gate_active") is True, "final human gate must be active")
    expect(manifest.get("validation", {}).get("replacement_execution_performed") is False, "final replacement must not execute")
    expect(manifest.get("validation", {}).get("editing_software_opened") is False, "final editor must not open")
    expect(manifest.get("validation", {}).get("instruction_count", 0) >= 1, "final instruction count must be non-empty")
    if default_pending:
        expect(manifest.get("validation", {}).get("ready_pending_human_confirmation_count") == 0, "default final ready count should be zero")
        expect(manifest.get("validation", {}).get("pending_human_media_count", 0) >= 1, "default final pending count must be non-empty")
    validate_instruction_boundary(manifest.get("export_boundary", {}), "final editor instruction")


def validate_instruction_boundary(boundary: dict[str, Any], label: str) -> None:
    expect(boundary.get("editor_replacement_instructions") == INSTRUCTION_BOUNDARY, f"{label} boundary mismatch")
    expect(boundary.get("replacement_execution") == "not_performed", f"{label} must not execute replacement")
    expect(boundary.get("editing_software") == "not_opened", f"{label} must not open editing software")
    expect(boundary.get("project_file_mutation") == "not_performed", f"{label} must not mutate project files")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        expect(boundary.get(key) == "not_performed", f"{label} must mark {key} as not_performed")


def validate_fcpxml(path: Path, platform: str) -> None:
    expect(path.exists(), f"{platform} FCPXML import template missing")
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        fail(f"{platform} FCPXML import template is invalid XML: {exc}")
    expect(root.tag == "fcpxml", f"{platform} FCPXML root must be fcpxml")


def validate_instruction_docs(checklist_path: Path, readme_path: Path, platform: str) -> None:
    checklist = checklist_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    expect("Human Confirmation Gate" in checklist, f"{platform} checklist missing confirmation heading")
    expect("No editing software was opened" in checklist, f"{platform} checklist missing safety boundary")
    expect("dry-run automation contract" in readme, f"{platform} README missing dry-run instruction")
    expect("does not open editing software" in readme, f"{platform} README missing no editor boundary")


def with_zip_paths(bundle_path: Path, platform: str, required_paths: list[str]) -> None:
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    for archive_path in required_paths:
        expect(archive_path in archive_paths, f"{platform} bundle missing editor instruction file: {archive_path}")


def _find_by_asset_id(items: Any, asset_id: str) -> dict[str, Any]:
    if not isinstance(items, list):
        fail(f"expected list while finding asset: {asset_id}")
    for item in items:
        if isinstance(item, dict) and str(item.get("asset_id")) == asset_id:
            return item
    fail(f"missing asset_id in collection: {asset_id}")
    raise AssertionError("unreachable")


def main() -> int:
    validate_workflow_instruction_steps()
    print("Phase 4 editor replacement instruction drill passed: workflow instruction steps")
    validate_default_no_registry_run()
    print("Phase 4 editor replacement instruction drill passed: default pending dry-run instructions")
    validate_human_registry_ready_instructions()
    print("Phase 4 editor replacement instruction drill passed: ready proxy to gated editor instructions")
    print("Phase 4 editor replacement instructions validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
