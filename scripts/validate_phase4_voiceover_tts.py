from __future__ import annotations

import json
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_agent_os.runner import run_workflow  # noqa: E402
from content_agent_os.workflow import load_workflow  # noqa: E402


VIDEO_PLATFORMS = ["douyin", "shipinhao", "bilibili"]
EXPECTED_VOICEOVER_TTS_BOUNDARIES = {
    "performed_locally_draft_no_external_provider",
    "performed_external_openai_speech_pending_human_review",
    "performed_external_siliconflow_speech_pending_human_review",
    "performed_mixed_voiceover_tts_pending_human_review",
}
EXPECTED_EXTERNAL_VOICEOVER_MODES = {
    "openai-speech-api": "openai_speech_api",
    "siliconflow-audio-speech-api": "siliconflow_speech_api",
}


def fail(message: str) -> None:
    print(f"Phase 4 voiceover TTS validation failed: {message}", file=sys.stderr)
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


def validate_workflow_voiceover_steps() -> None:
    workflow = load_workflow(ROOT / "workflows/one_topic_multi_platform.yaml")
    steps = {step.id: step for step in workflow.steps}
    fact_check = steps.get("fact_check")
    expect(fact_check is not None, "workflow missing fact_check step")
    for platform in VIDEO_PLATFORMS:
        step_id = f"{platform}_voiceover_tts"
        step = steps.get(step_id)
        expect(step is not None, f"workflow missing step: {step_id}")
        expect(step.agent == "voiceover-tts-agent", f"{step_id} must use voiceover-tts-agent")
        expect(step.platform == platform, f"{step_id} platform mismatch")
        expect(step.depends_on == [f"{platform}_subtitle_timing"], f"{step_id} must depend only on subtitle timing")
        expect(f"assets/{platform}/voiceover/voiceover.wav" in step.outputs, f"{step_id} missing WAV output")
        expect(f"assets/{platform}/voiceover/voiceover_manifest.json" in step.outputs, f"{step_id} missing manifest output")
        expect(step_id in fact_check.depends_on, f"fact_check must depend on {step_id}")


def validate_voiceover_run() -> None:
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "runs"
        run_dir = run_workflow(
            workflow_path=ROOT / "workflows/one_topic_multi_platform.yaml",
            topic="Phase 4 配音 TTS 验收",
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
        voiceover_boundary = video_package.get("export_boundary", {}).get("voiceover_tts_generation")
        expect(
            voiceover_boundary in EXPECTED_VOICEOVER_TTS_BOUNDARIES,
            "video package must mark voiceover TTS boundary with a supported mode",
        )
        source_artifacts = set(video_package.get("source_artifacts", []))
        packages = {
            package.get("platform"): package
            for package in video_package.get("platform_packages", [])
            if isinstance(package, dict)
        }

        for platform in VIDEO_PLATFORMS:
            step_id = f"{platform}_voiceover_tts"
            expect(modes_by_step.get(step_id) == "agent-local", f"{step_id} must run through run_agent")
            log_metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
            expect(log_metadata.get("agent_interface") == "run_agent(task_spec)", f"{step_id} missing run_agent proof")
            expect(log_metadata.get("voiceover_status") == "PASSED", f"{step_id} voiceover status must pass")
            for source in [f"{platform}/timed_subtitles.json", f"{platform}/timed_subtitles.srt"]:
                expect(source in log_metadata.get("source_artifacts", []), f"{step_id} missing source artifact: {source}")

            timed = load_json(run_dir / platform / "timed_subtitles.json")
            manifest_path = run_dir / "assets" / platform / "voiceover" / "voiceover_manifest.json"
            audio_path = run_dir / "assets" / platform / "voiceover" / "voiceover.wav"
            manifest = load_json(manifest_path)
            expect(audio_path.exists(), f"{platform} voiceover WAV missing")
            expect(audio_path.read_bytes()[:4] == b"RIFF", f"{platform} voiceover must be a WAV/RIFF file")
            expect(manifest.get("schema_version") == "phase4.voiceover_tts_manifest.v1", f"{platform} manifest schema mismatch")
            expect(
                manifest.get("adapter") == "hybrid-voiceover-tts-adapter",
                f"{platform} adapter mismatch",
            )
            expect(
                isinstance(manifest.get("provider_external"), bool),
                f"{platform} provider_external must be boolean",
            )
            if manifest.get("provider_external") is True:
                provider = manifest.get("provider")
                expect(provider in EXPECTED_EXTERNAL_VOICEOVER_MODES, f"{platform} external provider mismatch")
                expect(
                    manifest.get("audio_generation_mode") == EXPECTED_EXTERNAL_VOICEOVER_MODES.get(provider),
                    f"{platform} external audio mode mismatch",
                )
                expect(
                    manifest.get("generation_status") == "generated_external_tts_pending_human_review",
                    f"{platform} external generation status mismatch",
                )
                expect(
                    manifest.get("rights_status") == "ai_generated_pending_human_review",
                    f"{platform} external rights status mismatch",
                )
            else:
                expect(manifest.get("provider") == "local-deterministic-draft", f"{platform} local provider mismatch")
                expect(manifest.get("audio_generation_mode") == "local_deterministic_draft", f"{platform} local audio mode mismatch")
                expect(
                    manifest.get("generation_status") == "generated_local_draft_pending_human_review",
                    f"{platform} local generation status mismatch",
                )
                expect(
                    manifest.get("rights_status") == "self_generated_pending_human_review",
                    f"{platform} local rights status mismatch",
                )
            expect(manifest.get("timed_subtitle_count") == timed.get("subtitle_count"), f"{platform} timed subtitle count mismatch")
            expect(manifest.get("segment_count") == timed.get("subtitle_count"), f"{platform} segment count mismatch")
            expect(manifest.get("validation", {}).get("status") == "PASSED", f"{platform} manifest validation must pass")
            expect(manifest.get("validation", {}).get("audio_duration_matches_timeline") is True, f"{platform} duration validation must pass")
            with wave.open(str(audio_path), "rb") as wav:
                expect(wav.getnchannels() == 1, f"{platform} voiceover must be mono")
                expect(wav.getsampwidth() == 2, f"{platform} voiceover must be 16-bit")
                duration = wav.getnframes() / wav.getframerate()
            expect(abs(duration - timed.get("total_duration_seconds")) < 0.01, f"{platform} WAV duration must match timeline")

            expect(f"assets/{platform}/voiceover/voiceover.wav" in source_artifacts, f"{platform} voiceover WAV missing from source_artifacts")
            expect(f"assets/{platform}/voiceover/voiceover_manifest.json" in source_artifacts, f"{platform} voiceover manifest missing from source_artifacts")
            package = packages.get(platform)
            expect(isinstance(package, dict), f"video package missing platform: {platform}")
            deliverables = package.get("deliverables", {})
            expect(deliverables.get("voiceover_audio") == f"assets/{platform}/voiceover/voiceover.wav", f"{platform} package missing voiceover audio")
            expect(deliverables.get("voiceover_manifest") == f"assets/{platform}/voiceover/voiceover_manifest.json", f"{platform} package missing voiceover manifest")
            summary = package.get("voiceover_tts", {})
            expect(summary.get("validation_status") == "PASSED", f"{platform} voiceover summary must pass")
            expect(summary.get("audio_duration_matches_timeline") is True, f"{platform} voiceover summary duration mismatch")
            expect(summary.get("provider_external") == manifest.get("provider_external"), f"{platform} summary/provider mode mismatch")


def main() -> int:
    validate_workflow_voiceover_steps()
    print("Phase 4 voiceover drill passed: workflow TTS steps")
    validate_voiceover_run()
    print("Phase 4 voiceover drill passed: local draft WAV generation and package embedding")
    print("Phase 4 voiceover TTS validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
