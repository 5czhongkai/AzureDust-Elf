from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
FRAME_IDS = {
    "douyin": [f"douyin_{index:02d}" for index in range(1, 7)],
    "shipinhao": [f"shipinhao_{index:02d}" for index in range(1, 7)],
    "bilibili": [f"bili_{index:02d}" for index in range(1, 7)],
}


def fail(message: str) -> None:
    print(f"Phase 4 storyboard adapter validation failed: {message}", file=sys.stderr)
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


def validate_workflow_storyboard_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_storyboard_preview"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "storyboard-preview-agent", f"{step_id} must use storyboard-preview-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect("visual_assets" in step.depends_on, f"{step_id} must depend on visual_assets")
        expect(f"{platform}_video" in step.depends_on, f"{step_id} must depend on {platform}_video")
        expected_outputs = {
            f"assets/{platform}/storyboard/storyboard_preview.png",
            f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
        } | {f"assets/{platform}/storyboard/{frame_id}.png" for frame_id in FRAME_IDS[platform]}
        missing = sorted(expected_outputs - set(step.outputs))
        expect(not missing, f"{step_id} missing outputs: {missing}")


def validate_storyboard_generation_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 分镜关键帧适配器验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")
        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}

        asset_tasks = load_json(run_dir / "assets/asset_generation_tasks.json")
        task_targets = {
            task.get("target_path")
            for task in asset_tasks.get("tasks", [])
            if isinstance(task, dict) and task.get("asset_type") == "storyboard_frame"
        }

        video_package = load_json(run_dir / "final/video_production_package.json")
        expect(
            video_package.get("export_boundary", {}).get("storyboard_preview_generation")
            == "performed_locally_pending_human_review",
            "video package must mark storyboard preview generation as pending review",
        )
        source_artifacts = set(video_package.get("source_artifacts", []))
        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_storyboard_preview"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            storyboard = load_json(run_dir / platform / "storyboard.json")
            expect(isinstance(storyboard, list) and len(storyboard) == 6, f"{platform} storyboard should have 6 scenes")

            preview_path = run_dir / "assets" / platform / "storyboard" / "storyboard_preview.png"
            metadata_path = run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json"
            expect(preview_path.exists(), f"{platform} storyboard preview image missing")
            expect(metadata_path.exists(), f"{platform} storyboard preview metadata missing")

            with Image.open(preview_path) as image:
                width, height = image.size
                if platform == "bilibili":
                    expect(width > height, f"{platform} preview sheet should be horizontal")
                else:
                    expect(height > width, f"{platform} preview sheet should be vertical")

            metadata = load_json(metadata_path)
            expect(metadata.get("schema_version") == "phase4.storyboard_preview_metadata.v1", f"{platform} metadata schema mismatch")
            expect(metadata.get("asset_type") == "storyboard_preview", f"{platform} metadata asset_type mismatch")
            expect(metadata.get("adapter") == "local-pillow-storyboard-preview-adapter", f"{platform} adapter mismatch")
            expect(metadata.get("generation_status") == "generated_pending_review", f"{platform} preview must await review")
            expect(metadata.get("rights_status") == "pending_human_review", f"{platform} rights must await review")
            expect(metadata.get("manual_review_required") is True, f"{platform} preview must require manual review")
            frames = metadata.get("frames", [])
            expect(isinstance(frames, list) and len(frames) == len(storyboard), f"{platform} frame count must match storyboard")
            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform package: {platform}")
            deliverables = package.get("deliverables", {})
            generated_assets = package.get("generated_assets", [])
            expect(deliverables.get("storyboard_preview") == f"assets/{platform}/storyboard/storyboard_preview.png", f"{platform} package missing preview sheet")
            expect(
                deliverables.get("storyboard_preview_metadata") == f"assets/{platform}/storyboard/storyboard_preview_metadata.json",
                f"{platform} package missing preview metadata",
            )
            expect(
                f"assets/{platform}/storyboard/storyboard_preview.png" in source_artifacts,
                f"{platform} preview png missing from source_artifacts",
            )
            expect(
                f"assets/{platform}/storyboard/storyboard_preview_metadata.json" in source_artifacts,
                f"{platform} preview metadata missing from source_artifacts",
            )

            generated_frame_assets = [
                asset
                for asset in generated_assets
                if isinstance(asset, dict) and asset.get("asset_type") == "storyboard_frame"
            ]
            expect(len(generated_frame_assets) == len(storyboard), f"{platform} package must embed frame assets")
            expect(
                any(asset.get("asset_type") == "storyboard_preview" for asset in generated_assets if isinstance(asset, dict)),
                f"{platform} package must embed storyboard preview metadata",
            )
            for index, frame in enumerate(frames, start=1):
                expect(frame.get("schema_version") == "phase4.storyboard_frame_metadata.v1", f"{platform} frame schema mismatch")
                expect(frame.get("asset_type") == "storyboard_frame", f"{platform} frame asset_type mismatch")
                expect(frame.get("platform") == platform, f"{platform} frame platform mismatch")
                expect(frame.get("frame_index") == index, f"{platform} frame index mismatch")
                expect(frame.get("generation_status") == "generated_pending_review", f"{platform} frame must await review")
                expect(frame.get("rights_status") == "pending_human_review", f"{platform} frame rights must await review")
                expect(frame.get("manual_review_required") is True, f"{platform} frame must require manual review")
                frame_path = str(frame.get("path"))
                expect(frame_path in task_targets, f"{platform} frame path must come from asset task target: {frame_path}")
                expect(frame_path in source_artifacts, f"{platform} frame path missing from source_artifacts: {frame_path}")
                expect(deliverables.get(f"storyboard_keyframe_{frame.get('shot_id')}") == frame_path, f"{platform} deliverables missing keyframe {frame.get('shot_id')}")
                with Image.open(run_dir / frame_path) as image:
                    width, height = image.size
                    expect(width >= 700 and height >= 700, f"{platform} keyframe image is too small")
                    if platform == "bilibili":
                        expect(width > height, f"{platform} keyframe should be horizontal")
                    else:
                        expect(height > width, f"{platform} keyframe should be vertical")


def main() -> int:
    validate_workflow_storyboard_steps()
    print("Phase 4 storyboard drill passed: workflow storyboard preview steps")
    validate_storyboard_generation_run()
    print("Phase 4 storyboard drill passed: local keyframe generation and package embedding")
    print("Phase 4 storyboard adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
