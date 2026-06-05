from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]


def fail(message: str) -> None:
    print(f"Phase 4 cover adapter validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> dict:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


def validate_workflow_cover_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_cover_image"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "cover-image-agent", f"{step_id} must use cover-image-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect("visual_assets" in step.depends_on, f"{step_id} must depend on visual_assets")
        expect(f"assets/{platform}/cover/cover.png" in step.outputs, f"{step_id} missing cover png output")
        expect(f"assets/{platform}/cover/cover_metadata.json" in step.outputs, f"{step_id} missing cover metadata output")


def validate_cover_generation_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 封面图生成适配器验收",
            platforms=VIDEO_PLATFORMS,
            output_root=output_root,
        )
        workflow_run = load_json(run_dir / "workflow_run.json")
        expect(workflow_run.get("status") == "DONE", "workflow should finish")

        modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in workflow_run.get("task_runs", [])}
        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_cover_image"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            cover_path = run_dir / "assets" / platform / "cover" / "cover.png"
            metadata_path = run_dir / "assets" / platform / "cover" / "cover_metadata.json"
            expect(cover_path.exists(), f"{platform} cover image missing")
            expect(metadata_path.exists(), f"{platform} cover metadata missing")
            with Image.open(cover_path) as image:
                width, height = image.size
                expect(width >= 700 and height >= 700, f"{platform} cover image is too small")
                if platform == "bilibili":
                    expect(width > height, "bilibili cover should be horizontal")
                else:
                    expect(height > width, f"{platform} cover should be vertical")

            metadata = load_json(metadata_path)
            expect(metadata.get("schema_version") == "phase4.cover_image_metadata.v1", f"{platform} metadata schema mismatch")
            expect(metadata.get("adapter") == "local-pillow-cover-adapter", f"{platform} adapter mismatch")
            expect(metadata.get("generation_status") == "generated_pending_review", f"{platform} cover must await review")
            expect(metadata.get("rights_status") == "pending_human_review", f"{platform} rights must await review")
            expect(metadata.get("manual_review_required") is True, f"{platform} cover must require manual review")

        asset_tasks = load_json(run_dir / "assets/asset_generation_tasks.json")
        for task in asset_tasks.get("tasks", []):
            if task.get("asset_type") == "broll":
                expect(not (run_dir / task["target_path"]).exists(), f"B-roll asset should not be generated: {task['target_path']}")

        video_package = load_json(run_dir / "final/video_production_package.json")
        expect(
            video_package.get("export_boundary", {}).get("cover_image_generation")
            == "performed_locally_pending_human_review",
            "video package must mark cover generation as performed pending review",
        )
        source_artifacts = set(video_package.get("source_artifacts", []))
        for package in video_package.get("platform_packages", []):
            platform = package.get("platform")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("generated_cover_image") == f"assets/{platform}/cover/cover.png", f"{platform} package missing generated cover")
            expect(package.get("generated_assets"), f"{platform} package missing generated asset metadata")
            expect(f"assets/{platform}/cover/cover.png" in source_artifacts, f"{platform} cover png missing from source_artifacts")
            expect(f"assets/{platform}/cover/cover_metadata.json" in source_artifacts, f"{platform} cover metadata missing from source_artifacts")


def main() -> int:
    validate_workflow_cover_steps()
    print("Phase 4 cover drill passed: workflow cover steps")
    validate_cover_generation_run()
    print("Phase 4 cover drill passed: local cover generation")
    print("Phase 4 cover adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
