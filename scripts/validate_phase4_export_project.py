from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]


def fail(message: str) -> None:
    print(f"Phase 4 export project validation failed: {message}", file=sys.stderr)
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


def validate_workflow_export_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("final/export_project_manifest.json" in workflow.outputs, "workflow must export final export project manifest")
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_export_project"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "export-project-agent", f"{step_id} must use export-project-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect(f"{platform}_edit_project" in step.depends_on, f"{step_id} must depend on edit project")
        for output in [
            f"assets/{platform}/edit/project.fcpxml",
            f"assets/{platform}/edit/import_readme.md",
            f"assets/{platform}/edit/offline_media_report.json",
            f"assets/{platform}/edit/export_manifest.json",
        ]:
            expect(output in step.outputs, f"{step_id} missing output: {output}")
        expect(step_id in fact_check.depends_on, f"fact_check must depend on {step_id}")


def validate_export_project_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 剪辑工程导出验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        expect("final/export_project_manifest.json" in workflow_run.get("artifacts", []), "workflow artifacts missing final export manifest")
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        video_package = load_json(run_dir / "final/video_production_package.json")
        final_manifest = load_json(run_dir / "final/export_project_manifest.json")
        expect(
            video_package.get("export_boundary", {}).get("export_project_generation")
            == "performed_locally_draft_no_editing_software",
            "video package must mark export project generation as local draft",
        )
        expect(
            video_package.get("export_project_manifest") == "final/export_project_manifest.json",
            "video package must reference final export project manifest",
        )
        expect(final_manifest.get("schema_version") == "phase4.export_project_bundle_manifest.v1", "final export manifest schema mismatch")
        expect(final_manifest.get("artifact_type") == "export_project_bundle", "final export manifest type mismatch")
        expect(final_manifest.get("validation", {}).get("status") == "PASSED", "final export manifest validation must pass")
        final_projects = {
            project.get("platform"): project
            for project in final_manifest.get("platform_projects", [])
            if isinstance(project, dict)
        }
        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_export_project"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(log_metadata.get("export_status") == "PASSED", f"{step_id} export status must pass")

            project_path = run_dir / "assets" / platform / "edit" / "project.fcpxml"
            readme_path = run_dir / "assets" / platform / "edit" / "import_readme.md"
            offline_path = run_dir / "assets" / platform / "edit" / "offline_media_report.json"
            manifest_path = run_dir / "assets" / platform / "edit" / "export_manifest.json"
            for path in [project_path, readme_path, offline_path, manifest_path]:
                expect(path.exists(), f"{platform} export artifact missing: {path.relative_to(run_dir)}")
            try:
                ET.parse(project_path)
            except ET.ParseError as exc:
                fail(f"{platform} FCPXML is not well-formed: {exc}")

            offline_report = load_json(offline_path)
            manifest = load_json(manifest_path)
            expect(manifest.get("schema_version") == "phase4.export_project_manifest.v1", f"{platform} export manifest schema mismatch")
            expect(manifest.get("project_format") == "fcpxml", f"{platform} export format mismatch")
            expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} export manifest validation must pass")
            expect(manifest.get("validation", {}).get("referenced_media_files_exist") is True, f"{platform} media refs must exist")
            expect(offline_report.get("missing_source_count") == 0, f"{platform} should have no missing storyboard/voiceover sources")
            expect(offline_report.get("offline_broll_count") >= 1, f"{platform} should report offline B-roll slots")
            readme = readme_path.read_text(encoding="utf-8")
            expect("Import the FCPXML" in readme, f"{platform} import readme missing instructions")

            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("project_fcpxml") == f"assets/{platform}/edit/project.fcpxml", f"{platform} package missing FCPXML")
            expect(deliverables.get("project_import_readme") == f"assets/{platform}/edit/import_readme.md", f"{platform} package missing import readme")
            expect(deliverables.get("offline_media_report") == f"assets/{platform}/edit/offline_media_report.json", f"{platform} package missing offline report")
            expect(deliverables.get("export_manifest") == f"assets/{platform}/edit/export_manifest.json", f"{platform} package missing export manifest")
            summary = package.get("export_project", {})
            expect(summary.get("validation_status") == "PASSED", f"{platform} export project summary must pass")
            expect(summary.get("referenced_media_files_exist") is True, f"{platform} export project media refs must exist")
            final_project = final_projects.get(platform)
            expect(isinstance(final_project, dict), f"final export manifest missing platform: {platform}")
            expect(final_project.get("project_path") == f"assets/{platform}/edit/project.fcpxml", f"{platform} final manifest missing FCPXML")
            expect(final_project.get("manifest_path") == f"assets/{platform}/edit/export_manifest.json", f"{platform} final manifest missing export manifest")


def main() -> int:
    validate_workflow_export_steps()
    print("Phase 4 export project drill passed: workflow export steps")
    validate_export_project_run()
    print("Phase 4 export project drill passed: FCPXML, offline report, and package embedding")
    print("Phase 4 export project validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
