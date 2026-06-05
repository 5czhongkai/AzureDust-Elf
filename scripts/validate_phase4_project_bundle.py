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
REQUIRED_BUNDLE_ARCHIVE_PATHS = {
    "README.md",
    "project/project.fcpxml",
    "docs/import_readme.md",
    "reports/offline_media_report.json",
    "metadata/export_manifest.json",
    "metadata/edit_timeline.json",
    "metadata/draft_cut.edl",
    "replacement_instructions/instruction_manifest.json",
    "replacement_instructions/replacement_commands.json",
    "replacement_instructions/editor_import_template.fcpxml",
    "replacement_instructions/human_confirmation_checklist.md",
    "replacement_instructions/README.md",
    "replacement_execution/execution_manifest.json",
    "replacement_execution/execution_plan.json",
    "replacement_execution/execution_audit_log.json",
    "replacement_execution/human_execution_approval_request.md",
    "replacement_execution/README.md",
    "mutation_sandbox/mutation_manifest.json",
    "mutation_sandbox/patched_project.fcpxml",
    "mutation_sandbox/mutation_diff.json",
    "mutation_sandbox/rollback_manifest.json",
    "mutation_sandbox/mutation_audit_log.json",
    "mutation_sandbox/human_final_review_checklist.md",
    "mutation_sandbox/README.md",
    "software_import_executor/import_executor_manifest.json",
    "software_import_executor/import_plan.json",
    "software_import_executor/import_commands.json",
    "software_import_executor/software_import_audit_log.json",
    "software_import_executor/rollback_safety_report.json",
    "software_import_executor/isolated_execution_request.md",
    "software_import_executor/README.md",
    "software_real_runner_sandbox/runner_sandbox_manifest.json",
    "software_real_runner_sandbox/runner_environment_snapshot.json",
    "software_real_runner_sandbox/runner_launch_plan.json",
    "software_real_runner_sandbox/runner_command_preview.json",
    "software_real_runner_sandbox/runner_audit_log.json",
    "software_real_runner_sandbox/runner_evidence_manifest.json",
    "software_real_runner_sandbox/human_real_run_approval_request.md",
    "software_real_runner_sandbox/README.md",
    "software_run_evidence/real_run_evidence_manifest.json",
    "software_run_evidence/evidence_validation_report.json",
    "software_run_evidence/rollback_decision_report.json",
    "software_run_evidence/post_launch_evidence_checklist.md",
    "software_run_evidence/README.md",
    "subtitles/timed_subtitles.srt",
    "audio/voiceover.wav",
}


def fail(message: str) -> None:
    print(f"Phase 4 project bundle validation failed: {message}", file=sys.stderr)
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


def validate_workflow_project_bundle_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("final/project_bundle_manifest.json" in workflow.outputs, "workflow must export final project bundle manifest")
    for platform in VIDEO_PLATFORMS:
        instruction_step_id = f"{platform}_editor_replacement_instructions"
        instruction_step = steps.get(instruction_step_id)
        expect(instruction_step is not None, f"workflow missing step: {instruction_step_id}")
        expect(
            instruction_step.agent == "editor-replacement-instructions-agent",
            f"{instruction_step_id} must use editor-replacement-instructions-agent",
        )
        expect(instruction_step_id in fact_check.depends_on, f"fact_check must depend on {instruction_step_id}")
        execution_step_id = f"{platform}_editor_replacement_execution"
        execution_step = steps.get(execution_step_id)
        expect(execution_step is not None, f"workflow missing step: {execution_step_id}")
        expect(
            execution_step.agent == "editor-replacement-execution-agent",
            f"{execution_step_id} must use editor-replacement-execution-agent",
        )
        expect(execution_step.platform == platform, f"{execution_step_id} platform mismatch")
        expect(instruction_step_id in execution_step.depends_on, f"{execution_step_id} must depend on editor replacement instructions")
        expect(execution_step_id in fact_check.depends_on, f"fact_check must depend on {execution_step_id}")
        mutation_step_id = f"{platform}_editor_project_mutation_sandbox"
        mutation_step = steps.get(mutation_step_id)
        expect(mutation_step is not None, f"workflow missing step: {mutation_step_id}")
        expect(
            mutation_step.agent == "editor-project-mutation-sandbox-agent",
            f"{mutation_step_id} must use editor-project-mutation-sandbox-agent",
        )
        expect(mutation_step.platform == platform, f"{mutation_step_id} platform mismatch")
        expect(execution_step_id in mutation_step.depends_on, f"{mutation_step_id} must depend on editor replacement execution")
        expect(mutation_step_id in fact_check.depends_on, f"fact_check must depend on {mutation_step_id}")
        import_step_id = f"{platform}_editor_software_import_executor"
        import_step = steps.get(import_step_id)
        expect(import_step is not None, f"workflow missing step: {import_step_id}")
        expect(
            import_step.agent == "editor-software-import-executor-agent",
            f"{import_step_id} must use editor-software-import-executor-agent",
        )
        expect(import_step.platform == platform, f"{import_step_id} platform mismatch")
        expect(mutation_step_id in import_step.depends_on, f"{import_step_id} must depend on editor project mutation sandbox")
        expect(import_step_id in fact_check.depends_on, f"fact_check must depend on {import_step_id}")
        runner_step_id = f"{platform}_editor_software_real_runner_sandbox"
        runner_step = steps.get(runner_step_id)
        expect(runner_step is not None, f"workflow missing step: {runner_step_id}")
        expect(
            runner_step.agent == "editor-software-real-runner-sandbox-agent",
            f"{runner_step_id} must use editor-software-real-runner-sandbox-agent",
        )
        expect(import_step_id in runner_step.depends_on, f"{runner_step_id} must depend on editor software import executor")
        expect(runner_step_id in fact_check.depends_on, f"fact_check must depend on {runner_step_id}")
        evidence_step_id = f"{platform}_editor_software_run_evidence"
        evidence_step = steps.get(evidence_step_id)
        expect(evidence_step is not None, f"workflow missing step: {evidence_step_id}")
        expect(
            evidence_step.agent == "editor-software-run-evidence-agent",
            f"{evidence_step_id} must use editor-software-run-evidence-agent",
        )
        expect(runner_step_id in evidence_step.depends_on, f"{evidence_step_id} must depend on editor software real runner sandbox")
        expect(evidence_step_id in fact_check.depends_on, f"fact_check must depend on {evidence_step_id}")
        step_id = f"{platform}_project_bundle"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "project-bundle-agent", f"{step_id} must use project-bundle-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect(
            depends_on_transitively(steps, step_id, evidence_step_id),
            f"{step_id} must be downstream of editor software run evidence",
        )
        for output in [
            f"assets/{platform}/bundle/project_bundle.zip",
            f"assets/{platform}/bundle/project_bundle_manifest.json",
            f"assets/{platform}/bundle/file_manifest.json",
            f"assets/{platform}/bundle/README.md",
        ]:
            expect(output in step.outputs, f"{step_id} missing output: {output}")
        expect(step_id in fact_check.depends_on, f"fact_check must depend on {step_id}")


def validate_project_bundle_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 工程交付包验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect(
            "final/project_bundle_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final project bundle manifest",
        )
        expect(
            "final/editor_replacement_instruction_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final editor replacement instruction manifest",
        )
        expect(
            "final/editor_replacement_execution_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final editor replacement execution manifest",
        )
        expect(
            "final/editor_project_mutation_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final editor project mutation manifest",
        )
        expect(
            "final/editor_software_import_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final editor software import manifest",
        )
        expect(
            "final/editor_software_real_runner_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final editor software real runner manifest",
        )
        expect(
            "final/editor_software_run_evidence_manifest.json" in workflow_run.get("artifacts", []),
            "workflow artifacts missing final editor software run evidence manifest",
        )

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        video_package = load_json(run_dir / "final/video_production_package.json")
        content_package = load_json(run_dir / "final/content_package_manifest.json")
        final_manifest = load_json(run_dir / "final/project_bundle_manifest.json")
        expect(
            video_package.get("project_bundle_manifest") == "final/project_bundle_manifest.json",
            "video package must reference final project bundle manifest",
        )
        expect(
            video_package.get("editor_replacement_instruction_manifest")
            == "final/editor_replacement_instruction_manifest.json",
            "video package must reference final editor replacement instruction manifest",
        )
        expect(
            video_package.get("editor_replacement_execution_manifest")
            == "final/editor_replacement_execution_manifest.json",
            "video package must reference final editor replacement execution manifest",
        )
        expect(
            video_package.get("editor_project_mutation_manifest") == "final/editor_project_mutation_manifest.json",
            "video package must reference final editor project mutation manifest",
        )
        expect(
            video_package.get("editor_software_import_manifest") == "final/editor_software_import_manifest.json",
            "video package must reference final editor software import manifest",
        )
        expect(
            video_package.get("editor_software_real_runner_manifest") == "final/editor_software_real_runner_manifest.json",
            "video package must reference final editor software real runner manifest",
        )
        expect(
            video_package.get("editor_software_run_evidence_manifest") == "final/editor_software_run_evidence_manifest.json",
            "video package must reference final editor software run evidence manifest",
        )
        expect(
            content_package.get("project_bundle_manifest") == "final/project_bundle_manifest.json",
            "content package must reference final project bundle manifest",
        )
        expect(
            content_package.get("editor_replacement_instruction_manifest")
            == "final/editor_replacement_instruction_manifest.json",
            "content package must reference final editor replacement instruction manifest",
        )
        expect(
            content_package.get("editor_replacement_execution_manifest")
            == "final/editor_replacement_execution_manifest.json",
            "content package must reference final editor replacement execution manifest",
        )
        expect(
            content_package.get("editor_project_mutation_manifest") == "final/editor_project_mutation_manifest.json",
            "content package must reference final editor project mutation manifest",
        )
        expect(
            content_package.get("editor_software_import_manifest") == "final/editor_software_import_manifest.json",
            "content package must reference final editor software import manifest",
        )
        expect(
            content_package.get("editor_software_real_runner_manifest") == "final/editor_software_real_runner_manifest.json",
            "content package must reference final editor software real runner manifest",
        )
        expect(
            content_package.get("editor_software_run_evidence_manifest") == "final/editor_software_run_evidence_manifest.json",
            "content package must reference final editor software run evidence manifest",
        )
        expect(
            video_package.get("export_boundary", {}).get("project_bundle_generation")
            == "performed_locally_draft_no_editing_software",
            "video package must mark project bundle generation as local draft",
        )
        expect(final_manifest.get("schema_version") == "phase4.project_bundle_bundle_manifest.v1", "final bundle schema mismatch")
        expect(final_manifest.get("artifact_type") == "project_bundle_bundle", "final bundle type mismatch")
        expect(final_manifest.get("validation", {}).get("status") == "PASSED", "final bundle validation must pass")

        final_bundles = {
            bundle.get("platform"): bundle
            for bundle in final_manifest.get("platform_bundles", [])
            if isinstance(bundle, dict)
        }
        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_project_bundle"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(log_metadata.get("bundle_status") == "PASSED", f"{step_id} bundle status must pass")

            bundle_path = run_dir / "assets" / platform / "bundle" / "project_bundle.zip"
            manifest_path = run_dir / "assets" / platform / "bundle" / "project_bundle_manifest.json"
            file_manifest_path = run_dir / "assets" / platform / "bundle" / "file_manifest.json"
            readme_path = run_dir / "assets" / platform / "bundle" / "README.md"
            for path in [bundle_path, manifest_path, file_manifest_path, readme_path]:
                expect(path.exists(), f"{platform} project bundle artifact missing: {path.relative_to(run_dir)}")

            manifest = load_json(manifest_path)
            file_manifest = load_json(file_manifest_path)
            expect(manifest.get("schema_version") == "phase4.project_bundle_manifest.v1", f"{platform} manifest schema mismatch")
            expect(manifest.get("bundle_format") == "zip", f"{platform} bundle format mismatch")
            expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} bundle validation must pass")
            expect(manifest.get("validation", {}).get("required_files_present") is True, f"{platform} required files must exist")
            expect(manifest.get("validation", {}).get("bundle_bytes", 0) > 0, f"{platform} bundle must not be empty")
            expect(manifest.get("validation", {}).get("offline_broll_count", 0) >= 1, f"{platform} should preserve B-roll slots")
            expect(
                file_manifest.get("schema_version") == "phase4.project_bundle_file_manifest.v1",
                f"{platform} file manifest schema mismatch",
            )
            for entry in file_manifest.get("files", []):
                if not isinstance(entry, dict) or not entry.get("required"):
                    continue
                expect(entry.get("exists") is True, f"{platform} required bundle source missing: {entry.get('source_path')}")

            try:
                with ZipFile(bundle_path) as archive:
                    archive_paths = set(archive.namelist())
            except BadZipFile as exc:
                fail(f"{platform} project bundle ZIP is invalid: {exc}")
            missing_archive_paths = sorted(REQUIRED_BUNDLE_ARCHIVE_PATHS - archive_paths)
            expect(not missing_archive_paths, f"{platform} bundle missing archive paths: {missing_archive_paths}")
            for entry in file_manifest.get("files", []):
                if isinstance(entry, dict) and entry.get("exists") is True:
                    expect(entry.get("archive_path") in archive_paths, f"{platform} bundle missing file manifest entry")

            readme = readme_path.read_text(encoding="utf-8")
            expect("Open `project/project.fcpxml`" in readme, f"{platform} bundle README missing import instruction")

            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("project_bundle_zip") == f"assets/{platform}/bundle/project_bundle.zip", f"{platform} package missing bundle ZIP")
            expect(
                deliverables.get("project_bundle_manifest") == f"assets/{platform}/bundle/project_bundle_manifest.json",
                f"{platform} package missing bundle manifest",
            )
            expect(
                deliverables.get("project_bundle_file_manifest") == f"assets/{platform}/bundle/file_manifest.json",
                f"{platform} package missing file manifest",
            )
            expect(deliverables.get("project_bundle_readme") == f"assets/{platform}/bundle/README.md", f"{platform} package missing bundle README")
            for key, expected_path in {
                "editor_replacement_instruction_manifest": f"assets/{platform}/edit/replacement_instructions/instruction_manifest.json",
                "editor_replacement_commands": f"assets/{platform}/edit/replacement_instructions/replacement_commands.json",
                "editor_import_template_fcpxml": f"assets/{platform}/edit/replacement_instructions/editor_import_template.fcpxml",
                "editor_human_confirmation_checklist": f"assets/{platform}/edit/replacement_instructions/human_confirmation_checklist.md",
                "editor_replacement_readme": f"assets/{platform}/edit/replacement_instructions/README.md",
                "editor_replacement_execution_manifest": f"assets/{platform}/edit/replacement_execution/execution_manifest.json",
                "editor_replacement_execution_plan": f"assets/{platform}/edit/replacement_execution/execution_plan.json",
                "editor_replacement_execution_audit_log": f"assets/{platform}/edit/replacement_execution/execution_audit_log.json",
                "editor_replacement_approval_request": f"assets/{platform}/edit/replacement_execution/human_execution_approval_request.md",
                "editor_replacement_execution_readme": f"assets/{platform}/edit/replacement_execution/README.md",
                "editor_project_mutation_manifest": f"assets/{platform}/edit/mutation_sandbox/mutation_manifest.json",
                "editor_project_patched_fcpxml": f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml",
                "editor_project_mutation_diff": f"assets/{platform}/edit/mutation_sandbox/mutation_diff.json",
                "editor_project_rollback_manifest": f"assets/{platform}/edit/mutation_sandbox/rollback_manifest.json",
                "editor_project_mutation_audit_log": f"assets/{platform}/edit/mutation_sandbox/mutation_audit_log.json",
                "editor_project_final_review_checklist": f"assets/{platform}/edit/mutation_sandbox/human_final_review_checklist.md",
                "editor_project_mutation_readme": f"assets/{platform}/edit/mutation_sandbox/README.md",
                "editor_software_import_manifest": f"assets/{platform}/edit/software_import_executor/import_executor_manifest.json",
                "editor_software_import_plan": f"assets/{platform}/edit/software_import_executor/import_plan.json",
                "editor_software_import_commands": f"assets/{platform}/edit/software_import_executor/import_commands.json",
                "editor_software_import_audit_log": f"assets/{platform}/edit/software_import_executor/software_import_audit_log.json",
                "editor_software_import_rollback_safety_report": f"assets/{platform}/edit/software_import_executor/rollback_safety_report.json",
                "editor_software_import_execution_request": f"assets/{platform}/edit/software_import_executor/isolated_execution_request.md",
                "editor_software_import_readme": f"assets/{platform}/edit/software_import_executor/README.md",
                "editor_software_real_runner_manifest": f"assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json",
                "editor_software_real_runner_environment_snapshot": f"assets/{platform}/edit/software_real_runner_sandbox/runner_environment_snapshot.json",
                "editor_software_real_runner_launch_plan": f"assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json",
                "editor_software_real_runner_command_preview": f"assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json",
                "editor_software_real_runner_audit_log": f"assets/{platform}/edit/software_real_runner_sandbox/runner_audit_log.json",
                "editor_software_real_runner_evidence_manifest": f"assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json",
                "editor_software_real_runner_approval_request": f"assets/{platform}/edit/software_real_runner_sandbox/human_real_run_approval_request.md",
                "editor_software_real_runner_readme": f"assets/{platform}/edit/software_real_runner_sandbox/README.md",
                "editor_software_run_evidence_manifest": f"assets/{platform}/edit/software_run_evidence/real_run_evidence_manifest.json",
                "editor_software_run_evidence_validation_report": f"assets/{platform}/edit/software_run_evidence/evidence_validation_report.json",
                "editor_software_run_evidence_rollback_decision_report": f"assets/{platform}/edit/software_run_evidence/rollback_decision_report.json",
                "editor_software_run_evidence_checklist": f"assets/{platform}/edit/software_run_evidence/post_launch_evidence_checklist.md",
                "editor_software_run_evidence_readme": f"assets/{platform}/edit/software_run_evidence/README.md",
            }.items():
                expect(deliverables.get(key) == expected_path, f"{platform} package missing editor deliverable: {key}")
                expect((run_dir / expected_path).exists(), f"{platform} editor deliverable missing: {expected_path}")
            summary = package.get("project_bundle", {})
            expect(summary.get("validation_status") == "PASSED", f"{platform} project bundle summary must pass")
            expect(summary.get("required_files_present") is True, f"{platform} project bundle summary must confirm required files")
            final_bundle = final_bundles.get(platform)
            expect(isinstance(final_bundle, dict), f"final bundle manifest missing platform: {platform}")
            expect(final_bundle.get("bundle_path") == f"assets/{platform}/bundle/project_bundle.zip", f"{platform} final manifest missing bundle ZIP")
            expect(
                final_bundle.get("manifest_path") == f"assets/{platform}/bundle/project_bundle_manifest.json",
                f"{platform} final manifest missing bundle manifest",
            )


def main() -> int:
    validate_workflow_project_bundle_steps()
    print("Phase 4 project bundle drill passed: workflow project bundle steps")
    validate_project_bundle_run()
    print("Phase 4 project bundle drill passed: ZIP bundle, file manifest, and package embedding")
    print("Phase 4 project bundle validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
