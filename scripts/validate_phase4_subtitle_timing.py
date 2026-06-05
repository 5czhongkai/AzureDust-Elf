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
    print(f"Phase 4 subtitle timing validation failed: {message}", file=sys.stderr)
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


def validate_workflow_subtitle_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_subtitle_timing"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "subtitle-timing-agent", f"{step_id} must use subtitle-timing-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect(f"{platform}_video" in step.depends_on, f"{step_id} must depend on {platform}_video")
        expect(f"{platform}_storyboard_preview" in step.depends_on, f"{step_id} must depend on storyboard preview")
        expect(f"{platform}/timed_subtitles.json" in step.outputs, f"{step_id} missing timed_subtitles.json")
        expect(f"{platform}/timed_subtitles.srt" in step.outputs, f"{step_id} missing timed_subtitles.srt")
        expect(step_id in fact_check.depends_on, f"fact_check must depend on {step_id}")


def validate_subtitle_timing_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 字幕时间轴校正验收",
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
        expect(
            video_package.get("export_boundary", {}).get("subtitle_timing_correction")
            == "performed_locally_deterministic_no_tts",
            "video package must mark subtitle timing correction as deterministic and no-TTS",
        )
        source_artifacts = set(video_package.get("source_artifacts", []))
        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_subtitle_timing"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(log_metadata.get("timeline_status") == "PASSED", f"{step_id} timeline must pass")
            for source in [f"{platform}/storyboard.json", f"{platform}/shot_list.json", f"{platform}/subtitles.srt"]:
                expect(source in log_metadata.get("source_artifacts", []), f"{step_id} missing source artifact: {source}")

            storyboard = load_json(run_dir / platform / "storyboard.json")
            shot_list = load_json(run_dir / platform / "shot_list.json")
            timed_path = run_dir / platform / "timed_subtitles.json"
            timed_srt_path = run_dir / platform / "timed_subtitles.srt"
            timed = load_json(timed_path)
            expect(timed_srt_path.exists(), f"{platform} timed SRT missing")
            expect(timed.get("schema_version") == "phase4.timed_subtitles.v1", f"{platform} timed schema mismatch")
            expect(timed.get("adapter") == "local-subtitle-timing-adapter", f"{platform} adapter mismatch")
            expect(timed.get("storyboard_scene_count") == len(storyboard), f"{platform} scene count mismatch")
            expect(timed.get("source_subtitle_blocks") == len(storyboard), f"{platform} source subtitle count mismatch")
            expected_duration = sum(int(scene["duration_seconds"]) for scene in storyboard)
            expect(timed.get("total_duration_seconds") == expected_duration, f"{platform} duration mismatch")
            validation = timed.get("validation", {})
            expect(validation.get("status") == "PASSED", f"{platform} validation must pass")
            expect(validation.get("no_overlap") is True, f"{platform} subtitles must not overlap")
            expect(validation.get("no_cross_shot_subtitles") is True, f"{platform} subtitles must stay inside shot")
            expect(validation.get("ends_at_total_duration") is True, f"{platform} subtitles must end at total duration")

            subtitles = timed.get("subtitles", [])
            expect(isinstance(subtitles, list) and len(subtitles) >= len(storyboard), f"{platform} subtitles missing")
            shot_ids = [shot.get("shot_id") for shot in shot_list]
            for item in subtitles:
                expect(item.get("shot_id") in shot_ids, f"{platform} subtitle shot_id must come from shot_list")
                expect(item.get("start_seconds") < item.get("end_seconds"), f"{platform} subtitle duration must be positive")
                shot_index = int(item.get("shot_index"))
                shot_start = sum(int(scene["duration_seconds"]) for scene in storyboard[: shot_index - 1])
                shot_end = shot_start + int(storyboard[shot_index - 1]["duration_seconds"])
                expect(item.get("start_seconds") >= shot_start, f"{platform} subtitle starts before shot")
                expect(item.get("end_seconds") <= shot_end, f"{platform} subtitle ends after shot")
                expect(item.get("review_required") is True, f"{platform} subtitle must require review")

            srt_text = timed_srt_path.read_text(encoding="utf-8")
            expect(srt_text.count("-->") == len(subtitles), f"{platform} timed SRT block count mismatch")
            expect(f"{platform}/timed_subtitles.json" in source_artifacts, f"{platform} timed JSON missing from source_artifacts")
            expect(f"{platform}/timed_subtitles.srt" in source_artifacts, f"{platform} timed SRT missing from source_artifacts")

            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("timed_subtitles") == f"{platform}/timed_subtitles.json", f"{platform} package missing timed subtitles")
            expect(deliverables.get("timed_subtitles_srt") == f"{platform}/timed_subtitles.srt", f"{platform} package missing timed SRT")
            summary = package.get("timed_subtitles", {})
            expect(summary.get("path") == f"{platform}/timed_subtitles.json", f"{platform} package summary path mismatch")
            expect(summary.get("tts_ready") is True, f"{platform} timed subtitles must be TTS-ready")
            expect(summary.get("validation_status") == "PASSED", f"{platform} package timed validation mismatch")


def main() -> int:
    validate_workflow_subtitle_steps()
    print("Phase 4 subtitle timing drill passed: workflow subtitle timing steps")
    validate_subtitle_timing_run()
    print("Phase 4 subtitle timing drill passed: local timing correction and package embedding")
    print("Phase 4 subtitle timing validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
