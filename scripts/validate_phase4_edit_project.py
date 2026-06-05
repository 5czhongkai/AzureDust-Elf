from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]


def fail(message: str) -> None:
    print(f"Phase 4 edit project validation failed: {message}", file=sys.stderr)
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


def validate_workflow_edit_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    expect("final/edit_project_manifest.json" in workflow.outputs, "workflow must export final edit project manifest")
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_edit_project"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "edit-project-agent", f"{step_id} must use edit-project-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect(f"{platform}_storyboard_preview" in step.depends_on, f"{step_id} must depend on storyboard preview")
        expect(f"{platform}_voiceover_tts" in step.depends_on, f"{step_id} must depend on voiceover TTS")
        for output in [
            f"assets/{platform}/edit/edit_timeline.json",
            f"assets/{platform}/edit/edit_manifest.json",
            f"assets/{platform}/edit/draft_cut.edl",
        ]:
            expect(output in step.outputs, f"{step_id} missing output: {output}")
        expect(step_id in fact_check.depends_on, f"fact_check must depend on {step_id}")


def validate_edit_project_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 剪辑时间线验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        logs_by_step = {
            item.get("step_id"): load_json(run_dir / item["log_path"])
            for item in workflow_run.get("task_runs", [])
            if item.get("log_path")
        }
        video_package = load_json(run_dir / "final/video_production_package.json")
        final_manifest = load_json(run_dir / "final/edit_project_manifest.json")
        expect(
            video_package.get("export_boundary", {}).get("edit_project_generation")
            == "performed_locally_draft_no_editing_software",
            "video package must mark edit project generation as local draft",
        )
        expect(
            video_package.get("edit_project_manifest") == "final/edit_project_manifest.json",
            "video package must reference final edit project manifest",
        )
        expect(final_manifest.get("schema_version") == "phase4.edit_project_bundle_manifest.v1", "final edit manifest schema mismatch")
        expect(final_manifest.get("artifact_type") == "edit_project_bundle", "final edit manifest type mismatch")
        expect(final_manifest.get("video_production_package") == "final/video_production_package.json", "final edit manifest must reference video package")
        expect(final_manifest.get("validation", {}).get("status") == "PASSED", "final edit manifest validation must pass")
        expect(final_manifest.get("validation", {}).get("platform_count") == len(VIDEO_PLATFORMS), "final edit manifest platform count mismatch")
        source_artifacts = set(video_package.get("source_artifacts", []))
        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }
        final_projects = {
            project.get("platform"): project
            for project in final_manifest.get("platform_projects", [])
            if isinstance(project, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_edit_project"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(log_metadata.get("timeline_status") == "PASSED", f"{step_id} timeline status must pass")
            for source in [
                f"{platform}/storyboard.json",
                f"{platform}/shot_list.json",
                f"{platform}/timed_subtitles.json",
                f"assets/{platform}/voiceover/voiceover_manifest.json",
                f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
                f"{platform}/broll_list.json",
            ]:
                expect(source in log_metadata.get("source_artifacts", []), f"{step_id} missing source artifact: {source}")

            storyboard = load_json(run_dir / platform / "storyboard.json")
            timed = load_json(run_dir / platform / "timed_subtitles.json")
            timeline = load_json(run_dir / "assets" / platform / "edit" / "edit_timeline.json")
            manifest = load_json(run_dir / "assets" / platform / "edit" / "edit_manifest.json")
            edl_path = run_dir / "assets" / platform / "edit" / "draft_cut.edl"
            expect(edl_path.exists(), f"{platform} EDL missing")
            expect("FCM: NON-DROP FRAME" in edl_path.read_text(encoding="utf-8"), f"{platform} EDL missing header")
            expect(timeline.get("schema_version") == "phase4.edit_timeline.v1", f"{platform} timeline schema mismatch")
            expect(manifest.get("schema_version") == "phase4.edit_project_manifest.v1", f"{platform} manifest schema mismatch")
            expect(timeline.get("validation", {}).get("status") == "PASSED", f"{platform} timeline validation must pass")
            expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} manifest validation must pass")
            tracks = timeline.get("tracks", {})
            video_clips = tracks.get("video", [])
            audio_clips = tracks.get("audio", [])
            subtitle_clips = tracks.get("subtitles", [])
            expect(len(video_clips) == len(storyboard), f"{platform} video clip count must match storyboard")
            expect(len(audio_clips) == 1, f"{platform} timeline must include one voiceover clip")
            expect(len(subtitle_clips) == timed.get("subtitle_count"), f"{platform} subtitle clip count mismatch")
            expect(abs(float(timeline.get("duration_seconds")) - float(timed.get("total_duration_seconds"))) < 0.01, f"{platform} timeline duration mismatch")
            for clip in video_clips:
                expect(clip.get("source_path"), f"{platform} video clip missing storyboard keyframe source")
                expect((run_dir / clip["source_path"]).exists(), f"{platform} video clip source missing: {clip['source_path']}")
            expect(f"assets/{platform}/edit/edit_timeline.json" in source_artifacts, f"{platform} timeline missing from source_artifacts")
            expect(f"assets/{platform}/edit/edit_manifest.json" in source_artifacts, f"{platform} edit manifest missing from source_artifacts")
            expect(f"assets/{platform}/edit/draft_cut.edl" in source_artifacts, f"{platform} EDL missing from source_artifacts")

            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("edit_timeline") == f"assets/{platform}/edit/edit_timeline.json", f"{platform} package missing edit timeline")
            expect(deliverables.get("edit_manifest") == f"assets/{platform}/edit/edit_manifest.json", f"{platform} package missing edit manifest")
            expect(deliverables.get("draft_cut_edl") == f"assets/{platform}/edit/draft_cut.edl", f"{platform} package missing EDL")
            summary = package.get("edit_project", {})
            expect(summary.get("validation_status") == "PASSED", f"{platform} edit project summary must pass")
            expect(summary.get("video_duration_matches") is True, f"{platform} edit project video duration mismatch")
            expect(summary.get("audio_duration_matches") is True, f"{platform} edit project audio duration mismatch")
            expect(summary.get("subtitle_duration_matches") is True, f"{platform} edit project subtitle duration mismatch")
            final_project = final_projects.get(platform)
            expect(isinstance(final_project, dict), f"final edit manifest missing platform: {platform}")
            expect(final_project.get("timeline_path") == f"assets/{platform}/edit/edit_timeline.json", f"{platform} final manifest missing timeline")
            expect(final_project.get("manifest_path") == f"assets/{platform}/edit/edit_manifest.json", f"{platform} final manifest missing edit manifest")
            expect(final_project.get("edl_path") == f"assets/{platform}/edit/draft_cut.edl", f"{platform} final manifest missing EDL")
            expect(final_project.get("validation", {}).get("status") == "PASSED", f"{platform} final manifest validation must pass")


def main() -> int:
    validate_workflow_edit_steps()
    print("Phase 4 edit project drill passed: workflow edit steps")
    validate_edit_project_run()
    print("Phase 4 edit project drill passed: timeline, EDL, and package embedding")
    print("Phase 4 edit project validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
