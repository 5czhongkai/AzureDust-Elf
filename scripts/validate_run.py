from __future__ import annotations

import json
import hashlib
import sqlite3
import sys
import xml.etree.ElementTree as ET
import wave
from pathlib import Path
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_OFFLINE_BROLL_STATUSES = {
    "reference_generated_pending_licensed_media",
    "pending_human_licensed_media",
    "licensed_media_candidate_pending_review",
    "licensed_media_ready_for_editor_replacement",
    "proxy_ready_for_editor_replacement",
}
LICENSED_MEDIA_INGEST_BOUNDARY = "review_handoff_only_pending_human_supplied_media"
LICENSED_MEDIA_PROXY_BOUNDARY = "performed_locally_from_human_registered_media_only"
EDITOR_REPLACEMENT_INSTRUCTION_BOUNDARY = "performed_locally_template_and_instruction_only"
EDITOR_REPLACEMENT_EXECUTION_BOUNDARY = "blocked_pending_explicit_human_approval"
APPROVED_EDITOR_REPLACEMENT_EXECUTION_BOUNDARY = "approved_but_not_executed_by_default"
EXPECTED_EDITOR_REPLACEMENT_EXECUTION_BOUNDARIES = {
    EDITOR_REPLACEMENT_EXECUTION_BOUNDARY,
    APPROVED_EDITOR_REPLACEMENT_EXECUTION_BOUNDARY,
}
EDITOR_PROJECT_MUTATION_BOUNDARY = "blocked_pending_explicit_human_mutation_approval"
APPROVED_EDITOR_PROJECT_MUTATION_BOUNDARY = "sandbox_patch_generated_from_explicit_human_approval"
EXPECTED_EDITOR_PROJECT_MUTATION_BOUNDARIES = {
    EDITOR_PROJECT_MUTATION_BOUNDARY,
    APPROVED_EDITOR_PROJECT_MUTATION_BOUNDARY,
}
EDITOR_SOFTWARE_IMPORT_BOUNDARY = "blocked_pending_explicit_human_software_import_approval"
APPROVED_EDITOR_SOFTWARE_IMPORT_BOUNDARY = "approved_for_isolated_manual_import_not_executed"
EXPECTED_EDITOR_SOFTWARE_IMPORT_BOUNDARIES = {
    EDITOR_SOFTWARE_IMPORT_BOUNDARY,
    APPROVED_EDITOR_SOFTWARE_IMPORT_BOUNDARY,
}
EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY = "blocked_pending_explicit_human_real_run_approval"
APPROVED_EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY = "approved_for_manual_external_sandbox_launch_not_executed"
EXPECTED_EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARIES = {
    EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY,
    APPROVED_EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY,
}
EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY = "blocked_pending_human_real_run_result"
INGESTED_EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY = "human_evidence_ingested_no_automation_execution"
EXPECTED_EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARIES = {
    EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY,
    INGESTED_EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY,
}
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
    print(f"Run validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_run_dir(value: str) -> Path:
    if not value:
        runs = sorted((ROOT / "outputs/runs").glob("run_*"))
        if not runs:
            fail("RUN_ID is empty and no outputs/runs/run_* directory exists")
        return runs[-1]

    path = Path(value)
    if path.exists():
        return path
    candidate = ROOT / "outputs/runs" / value
    if candidate.exists():
        return candidate
    fail(f"run directory not found: {value}")
    raise AssertionError("unreachable")


def load_json(path: Path) -> dict:
    if not path.exists():
        fail(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON file {path}: {exc}")


def validate_state_store(run_dir: Path, workflow_run: dict) -> None:
    state_db = run_dir.parent / "_state/workflow_state.sqlite"
    if not state_db.exists():
        return

    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT workflow_id, status FROM workflow_run WHERE run_id = ?",
        (workflow_run.get("run_id"),),
    ).fetchone()
    if row is None:
        return

    if row["workflow_id"] != workflow_run.get("workflow_id"):
        fail("state store workflow_id does not match workflow_run.json")
    if row["status"] != workflow_run.get("status"):
        fail("state store status does not match workflow_run.json")

    ledger_rows = conn.execute(
        "SELECT COUNT(*) AS count FROM task_ledger WHERE run_id = ?",
        (workflow_run.get("run_id"),),
    ).fetchone()
    if not ledger_rows or ledger_rows["count"] <= 0:
        fail("state store task_ledger has no rows for this run")


def _validate_generated_cover(run_dir: Path, platform: str) -> None:
    cover_path = run_dir / "assets" / platform / "cover" / "cover.png"
    metadata_path = run_dir / "assets" / platform / "cover" / "cover_metadata.json"
    if not cover_path.exists():
        fail(f"{platform} generated cover image is missing")
    if cover_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{platform} generated cover image is not a PNG")
    metadata = load_json(metadata_path)
    if metadata.get("schema_version") != "phase4.cover_image_metadata.v1":
        fail(f"{platform} cover metadata has wrong schema_version")
    if metadata.get("generation_status") != "generated_pending_review":
        fail(f"{platform} cover metadata must be generated_pending_review")
    if metadata.get("rights_status") != "pending_human_review":
        fail(f"{platform} cover metadata must keep rights pending human review")
    if metadata.get("manual_review_required") is not True:
        fail(f"{platform} cover metadata must require manual review")


def _validate_generated_storyboard_preview(run_dir: Path, platform: str, expected_frame_count: int) -> None:
    preview_path = run_dir / "assets" / platform / "storyboard" / "storyboard_preview.png"
    metadata_path = run_dir / "assets" / platform / "storyboard" / "storyboard_preview_metadata.json"
    if not preview_path.exists():
        fail(f"{platform} storyboard preview image is missing")
    if preview_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{platform} storyboard preview image is not a PNG")
    metadata = load_json(metadata_path)
    if metadata.get("schema_version") != "phase4.storyboard_preview_metadata.v1":
        fail(f"{platform} storyboard preview metadata has wrong schema_version")
    if metadata.get("generation_status") != "generated_pending_review":
        fail(f"{platform} storyboard preview must be generated_pending_review")
    if metadata.get("rights_status") != "pending_human_review":
        fail(f"{platform} storyboard preview must keep rights pending human review")
    if metadata.get("manual_review_required") is not True:
        fail(f"{platform} storyboard preview must require manual review")
    frames = metadata.get("frames", [])
    if not isinstance(frames, list) or len(frames) != expected_frame_count:
        fail(f"{platform} storyboard preview frame count must match storyboard")
    for frame in frames:
        if not isinstance(frame, dict):
            fail(f"{platform} storyboard preview frames must be objects")
        if frame.get("schema_version") != "phase4.storyboard_frame_metadata.v1":
            fail(f"{platform} storyboard frame metadata has wrong schema_version")
        if frame.get("generation_status") != "generated_pending_review":
            fail(f"{platform} storyboard frame must be generated_pending_review")
        if frame.get("rights_status") != "pending_human_review":
            fail(f"{platform} storyboard frame must keep rights pending human review")
        if frame.get("manual_review_required") is not True:
            fail(f"{platform} storyboard frame must require manual review")
        frame_path = frame.get("path")
        if not frame_path or not (run_dir / frame_path).exists():
            fail(f"{platform} storyboard frame image is missing: {frame_path}")
        if (run_dir / frame_path).read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            fail(f"{platform} storyboard frame image is not a PNG: {frame_path}")


def _validate_timed_subtitles(run_dir: Path, platform: str, storyboard: list[dict]) -> None:
    timed_path = run_dir / platform / "timed_subtitles.json"
    timed_srt_path = run_dir / platform / "timed_subtitles.srt"
    if not timed_path.exists():
        fail(f"{platform} timed subtitles JSON is missing")
    if not timed_srt_path.exists():
        fail(f"{platform} timed subtitles SRT is missing")
    timed = load_json(timed_path)
    if timed.get("schema_version") != "phase4.timed_subtitles.v1":
        fail(f"{platform} timed subtitles have wrong schema_version")
    if timed.get("adapter") != "local-subtitle-timing-adapter":
        fail(f"{platform} timed subtitles adapter mismatch")
    if timed.get("storyboard_scene_count") != len(storyboard):
        fail(f"{platform} timed subtitles scene count must match storyboard")
    expected_duration = sum(int(scene.get("duration_seconds") or 0) for scene in storyboard)
    if timed.get("total_duration_seconds") != expected_duration:
        fail(f"{platform} timed subtitles total duration must match storyboard")
    validation = timed.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} timed subtitles validation must pass")
    for key in ["no_overlap", "no_cross_shot_subtitles", "starts_at_zero", "ends_at_total_duration"]:
        if validation.get(key) is not True:
            fail(f"{platform} timed subtitles validation failed: {key}")
    subtitles = timed.get("subtitles", [])
    if not isinstance(subtitles, list) or len(subtitles) < len(storyboard):
        fail(f"{platform} timed subtitles must contain at least one subtitle per storyboard scene")
    if timed_srt_path.read_text(encoding="utf-8").count("-->") != len(subtitles):
        fail(f"{platform} timed subtitles SRT block count must match JSON subtitles")
    for item in subtitles:
        if not isinstance(item, dict):
            fail(f"{platform} timed subtitle entries must be objects")
        shot_index = int(item.get("shot_index") or 0)
        if shot_index < 1 or shot_index > len(storyboard):
            fail(f"{platform} timed subtitle has invalid shot_index")
        shot_start = sum(int(scene.get("duration_seconds") or 0) for scene in storyboard[: shot_index - 1])
        shot_end = shot_start + int(storyboard[shot_index - 1].get("duration_seconds") or 0)
        if item.get("start_seconds") < shot_start or item.get("end_seconds") > shot_end:
            fail(f"{platform} timed subtitle crosses shot boundary")
        if item.get("review_required") is not True:
            fail(f"{platform} timed subtitle entries must require review")


def _validate_voiceover_tts(run_dir: Path, platform: str) -> dict[str, Any]:
    manifest_path = run_dir / "assets" / platform / "voiceover" / "voiceover_manifest.json"
    audio_path = run_dir / "assets" / platform / "voiceover" / "voiceover.wav"
    timed_path = run_dir / platform / "timed_subtitles.json"
    if not manifest_path.exists():
        fail(f"{platform} voiceover manifest is missing")
    if not audio_path.exists():
        fail(f"{platform} voiceover audio is missing")
    if audio_path.read_bytes()[:4] != b"RIFF":
        fail(f"{platform} voiceover audio must be a WAV file")
    manifest = load_json(manifest_path)
    timed = load_json(timed_path)
    if manifest.get("schema_version") != "phase4.voiceover_tts_manifest.v1":
        fail(f"{platform} voiceover manifest has wrong schema_version")
    if manifest.get("adapter") != "hybrid-voiceover-tts-adapter":
        fail(f"{platform} voiceover adapter mismatch")
    provider_external = manifest.get("provider_external") is True
    if provider_external:
        provider = manifest.get("provider")
        if provider not in EXPECTED_EXTERNAL_VOICEOVER_MODES:
            fail(f"{platform} external voiceover provider mismatch")
        if manifest.get("generation_status") != "generated_external_tts_pending_human_review":
            fail(f"{platform} external voiceover must mark external generation status")
        if manifest.get("rights_status") != "ai_generated_pending_human_review":
            fail(f"{platform} external voiceover must mark AI-generated rights status")
        if manifest.get("audio_generation_mode") != EXPECTED_EXTERNAL_VOICEOVER_MODES.get(provider):
            fail(f"{platform} external voiceover must mark provider-specific speech generation mode")
        provider_metadata = manifest.get("provider_metadata")
        if not isinstance(provider_metadata, dict):
            fail(f"{platform} external voiceover must include provider metadata")
        for key in ["model", "voice_id", "endpoint", "response_format", "input_character_count"]:
            if key not in provider_metadata:
                fail(f"{platform} external voiceover provider metadata missing {key}")
    else:
        if manifest.get("provider") != "local-deterministic-draft":
            fail(f"{platform} local voiceover must use local deterministic draft provider")
        if manifest.get("generation_status") != "generated_local_draft_pending_human_review":
            fail(f"{platform} local voiceover must mark local draft generation status")
        if manifest.get("rights_status") != "self_generated_pending_human_review":
            fail(f"{platform} local voiceover must mark self-generated rights status")
        if manifest.get("audio_generation_mode") != "local_deterministic_draft":
            fail(f"{platform} local voiceover must mark local deterministic generation mode")
        provider_metadata = manifest.get("provider_metadata")
        if not isinstance(provider_metadata, dict):
            fail(f"{platform} local voiceover must include provider metadata")
        if "sample_rate" not in provider_metadata:
            fail(f"{platform} local voiceover provider metadata missing sample_rate")
    if manifest.get("segment_count") != timed.get("subtitle_count"):
        fail(f"{platform} voiceover segment count must match timed subtitles")
    if manifest.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} voiceover validation must pass")
    with wave.open(str(audio_path), "rb") as wav:
        if wav.getnchannels() != 1:
            fail(f"{platform} voiceover WAV must be mono")
        if wav.getsampwidth() != 2:
            fail(f"{platform} voiceover WAV must be 16-bit")
        duration = wav.getnframes() / wav.getframerate()
    if abs(duration - float(timed.get("total_duration_seconds") or 0)) >= 0.01:
        fail(f"{platform} voiceover WAV duration must match timed subtitles")
    return manifest


def _material_reference_paths(run_dir: Path, platform: str) -> set[str]:
    manifest_path = run_dir / "assets" / platform / "materials" / "material_manifest.json"
    if not manifest_path.exists():
        return set()
    manifest = load_json(manifest_path)
    assets = manifest.get("materialized_assets", [])
    return {
        str(asset.get("reference_path"))
        for asset in assets
        if isinstance(asset, dict) and asset.get("reference_path")
    }


def _validate_materialized_assets(run_dir: Path, platform: str) -> None:
    manifest_path = run_dir / "assets" / platform / "materials" / "material_manifest.json"
    readme_path = run_dir / "assets" / platform / "materials" / "README.md"
    if not manifest_path.exists():
        fail(f"{platform} material manifest is missing")
    if not readme_path.exists():
        fail(f"{platform} material README is missing")
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != "phase4.materialized_assets_manifest.v1":
        fail(f"{platform} material manifest has wrong schema_version")
    if manifest.get("adapter") != "local-asset-materialization-adapter":
        fail(f"{platform} materialization adapter mismatch")
    if manifest.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} materialization validation must pass")
    boundary = manifest.get("export_boundary", {})
    if boundary.get("asset_materialization") != "performed_locally_reference_only":
        fail(f"{platform} materialization boundary must be reference-only")
    for key in ["asset_download", "external_asset_search", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{platform} materialization boundary must mark {key} as not_performed")
    assets = manifest.get("materialized_assets", [])
    if not isinstance(assets, list) or len(assets) < 1:
        fail(f"{platform} material manifest must contain reference assets")
    for asset in assets:
        if not isinstance(asset, dict):
            fail(f"{platform} materialized asset entries must be objects")
        reference_path = str(asset.get("reference_path") or "")
        if not reference_path:
            fail(f"{platform} materialized asset missing reference_path")
        path = run_dir / reference_path
        if not path.exists():
            fail(f"{platform} material reference is missing: {reference_path}")
        if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            fail(f"{platform} material reference must be a PNG: {reference_path}")
        if asset.get("asset_type") != "broll_reference":
            fail(f"{platform} material asset_type must be broll_reference")
        if asset.get("source_task_asset_type") != "broll":
            fail(f"{platform} material source asset type must be broll")
        if asset.get("generation_status") != "generated_reference_pending_review":
            fail(f"{platform} material generation status mismatch")
        if asset.get("rights_status") != "self_created_reference_pending_human_review":
            fail(f"{platform} material rights status mismatch")
        if asset.get("licensed_final_media_required") is not True:
            fail(f"{platform} material reference must require licensed final media")
        planned_target = asset.get("planned_target_path")
        if isinstance(planned_target, str) and planned_target and (run_dir / planned_target).exists():
            fail(f"{platform} planned B-roll MP4 should not be generated: {planned_target}")
    readme = readme_path.read_text(encoding="utf-8")
    if "reference only" not in readme:
        fail(f"{platform} material README must state reference-only boundary")
    if "No external asset search" not in readme:
        fail(f"{platform} material README must state no external search")


def _licensed_media_by_reference(run_dir: Path, platform: str) -> dict[str, dict]:
    manifest_path = run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = load_json(manifest_path)
    licensed_media = manifest.get("licensed_media", [])
    if not isinstance(licensed_media, list):
        return {}
    return {
        str(item["reference_path"]): item
        for item in licensed_media
        if isinstance(item, dict) and item.get("reference_path")
    }


def _licensed_media_proxy_by_reference(run_dir: Path, platform: str) -> dict[str, dict]:
    manifest_path = run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = load_json(manifest_path)
    proxy_assets = manifest.get("proxy_assets", [])
    if not isinstance(proxy_assets, list):
        return {}
    return {
        str(item["reference_path"]): item
        for item in proxy_assets
        if isinstance(item, dict) and item.get("reference_path")
    }


def _validate_licensed_media_ingest(run_dir: Path, platform: str) -> None:
    manifest_path = run_dir / "assets" / platform / "licensed_media" / "ingest_manifest.json"
    readme_path = run_dir / "assets" / platform / "licensed_media" / "README.md"
    handoff_path = run_dir / "assets" / platform / "licensed_media" / "review_handoff.md"
    if not manifest_path.exists():
        fail(f"{platform} licensed media ingest manifest is missing")
    if not readme_path.exists():
        fail(f"{platform} licensed media ingest README is missing")
    if not handoff_path.exists():
        fail(f"{platform} licensed media review handoff is missing")

    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != "phase4.licensed_media_ingest_manifest.v1":
        fail(f"{platform} licensed media ingest manifest has wrong schema_version")
    if manifest.get("artifact_type") != "licensed_media_ingest":
        fail(f"{platform} licensed media ingest manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-licensed-media-ingest-adapter":
        fail(f"{platform} licensed media ingest adapter mismatch")
    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} licensed media ingest validation must pass")
    if validation.get("all_materialized_assets_covered") is not True:
        fail(f"{platform} licensed media ingest must cover all materialized assets")
    if validation.get("licensed_final_media_required") is not True:
        fail(f"{platform} licensed media ingest must require final licensed media")

    summary = manifest.get("summary", {})
    required_count = int(summary.get("required_final_media_count") or 0)
    if required_count < 1:
        fail(f"{platform} licensed media ingest must require at least one final media item")

    boundary = manifest.get("export_boundary", {})
    if boundary.get("licensed_media_ingest") != LICENSED_MEDIA_INGEST_BOUNDARY:
        fail(f"{platform} licensed media ingest boundary mismatch")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{platform} licensed media ingest must not open editing software")
    for key in ["asset_download", "external_asset_search", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{platform} licensed media ingest boundary must mark {key} as not_performed")

    licensed_media = manifest.get("licensed_media", [])
    if not isinstance(licensed_media, list) or len(licensed_media) != required_count:
        fail(f"{platform} licensed media ingest item count mismatch")
    for item in licensed_media:
        if not isinstance(item, dict):
            fail(f"{platform} licensed media entries must be objects")
        reference_path = str(item.get("reference_path") or "")
        if not reference_path:
            fail(f"{platform} licensed media entry missing reference_path")
        reference_file = run_dir / reference_path
        if not reference_file.exists():
            fail(f"{platform} licensed media reference path is missing: {reference_path}")
        if reference_file.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            fail(f"{platform} licensed media reference must be a PNG: {reference_path}")
        if item.get("asset_type") != "licensed_broll_media":
            fail(f"{platform} licensed media asset_type mismatch")
        if item.get("source_reference_asset_type") != "broll_reference":
            fail(f"{platform} licensed media source reference type mismatch")
        if item.get("intake_status") not in {
            "pending_human_media",
            "candidate_registered_pending_review",
            "approved_candidate_ready_for_editor_replacement",
        }:
            fail(f"{platform} licensed media intake status mismatch")
        if item.get("licensed_final_media_required") is not True:
            fail(f"{platform} licensed media entry must require final media")
        if item.get("manual_review_required") is not True:
            fail(f"{platform} licensed media entry must require manual review")
        if item.get("intake_status") == "pending_human_media":
            if item.get("licensed_media_path") is not None:
                fail(f"{platform} pending licensed media must not invent licensed_media_path")
            if item.get("license_proof_path") is not None:
                fail(f"{platform} pending licensed media must not invent license_proof_path")
            if item.get("media_exists") is not False:
                fail(f"{platform} pending licensed media should not mark media as existing")
            if item.get("ready_for_editor_replacement") is not False:
                fail(f"{platform} pending licensed media should not be editor-ready")
            if item.get("review_status") != "awaiting_human_review":
                fail(f"{platform} pending licensed media review status mismatch")
            if item.get("rights_confirmation") != "unconfirmed":
                fail(f"{platform} pending licensed media rights confirmation mismatch")
        actions = item.get("required_human_actions", [])
        if not isinstance(actions, list):
            fail(f"{platform} licensed media entry must list required human actions")

    readme = readme_path.read_text(encoding="utf-8")
    handoff = handoff_path.read_text(encoding="utf-8")
    if "does not search, download, license, upload, publish, or open editing software" not in readme:
        fail(f"{platform} licensed media README must state boundary")
    if "human_media_registry.json" not in readme:
        fail(f"{platform} licensed media README must explain human registry")
    if "Licensed Media Review Handoff" not in handoff:
        fail(f"{platform} licensed media handoff missing heading")
    if "Required actions" not in handoff:
        fail(f"{platform} licensed media handoff missing required actions")


def _validate_licensed_media_ingest_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_licensed_media_ingest"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_licensed_media_ingest(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("licensed_media_ingest_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED licensed media ingest")
    if int(metadata.get("required_final_media_count") or 0) < 1:
        fail(f"{step_id} metadata must require final media")
    for source in [
        f"assets/{platform}/materials/material_manifest.json",
        f"assets/{platform}/materials/README.md",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_licensed_media_proxy(run_dir: Path, platform: str) -> None:
    manifest_path = run_dir / "assets" / platform / "licensed_media" / "proxy_manifest.json"
    suggestions_path = run_dir / "assets" / platform / "licensed_media" / "replacement_suggestions.json"
    readme_path = run_dir / "assets" / platform / "licensed_media" / "proxy" / "README.md"
    if not manifest_path.exists():
        fail(f"{platform} licensed media proxy manifest is missing")
    if not suggestions_path.exists():
        fail(f"{platform} licensed media replacement suggestions are missing")
    if not readme_path.exists():
        fail(f"{platform} licensed media proxy README is missing")

    manifest = load_json(manifest_path)
    suggestions = load_json(suggestions_path)
    if manifest.get("schema_version") != "phase4.licensed_media_proxy_manifest.v1":
        fail(f"{platform} licensed media proxy manifest has wrong schema_version")
    if manifest.get("artifact_type") != "licensed_media_proxy":
        fail(f"{platform} licensed media proxy manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-licensed-media-proxy-adapter":
        fail(f"{platform} licensed media proxy adapter mismatch")
    if suggestions.get("schema_version") != "phase4.licensed_media_replacement_suggestions.v1":
        fail(f"{platform} replacement suggestions have wrong schema_version")
    if suggestions.get("artifact_type") != "licensed_media_replacement_suggestions":
        fail(f"{platform} replacement suggestions have wrong artifact_type")

    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} licensed media proxy validation must pass")
    if validation.get("all_licensed_media_slots_covered") is not True:
        fail(f"{platform} licensed media proxy must cover all ingest slots")
    if validation.get("proxy_copy_complete_for_ready_media") is not True:
        fail(f"{platform} proxy copy must be complete for ready media")

    summary = manifest.get("summary", {})
    required_count = int(summary.get("required_final_media_count") or 0)
    copied_count = int(summary.get("proxy_copied_count") or 0)
    ready_count = int(summary.get("ready_source_media_count") or 0)
    if required_count < 1:
        fail(f"{platform} licensed media proxy must require at least one final media item")
    if copied_count != ready_count:
        fail(f"{platform} proxy copied count must match ready source count")

    boundary = manifest.get("export_boundary", {})
    if boundary.get("licensed_media_proxy") != LICENSED_MEDIA_PROXY_BOUNDARY:
        fail(f"{platform} licensed media proxy boundary mismatch")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{platform} licensed media proxy must not open editing software")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{platform} licensed media proxy boundary must mark {key} as not_performed")

    proxy_assets = manifest.get("proxy_assets", [])
    if not isinstance(proxy_assets, list) or len(proxy_assets) != required_count:
        fail(f"{platform} licensed media proxy item count mismatch")
    for asset in proxy_assets:
        if not isinstance(asset, dict):
            fail(f"{platform} proxy asset entries must be objects")
        if asset.get("asset_type") != "licensed_broll_proxy":
            fail(f"{platform} proxy asset_type mismatch")
        if asset.get("manual_review_required") is not True:
            fail(f"{platform} proxy asset must require manual review")
        proxy_path = asset.get("proxy_media_path")
        if asset.get("editor_replacement_ready") is True:
            if not isinstance(proxy_path, str) or not proxy_path:
                fail(f"{platform} ready proxy asset must include proxy_media_path")
            proxy_file = run_dir / proxy_path
            if not proxy_file.exists():
                fail(f"{platform} proxy media file is missing: {proxy_path}")
            if asset.get("proxy_media_sha256") != _sha256(proxy_file):
                fail(f"{platform} proxy media checksum mismatch: {proxy_path}")
            if asset.get("replacement_status") != "proxy_ready_for_editor_replacement":
                fail(f"{platform} ready proxy asset replacement status mismatch")
        elif proxy_path is not None:
            fail(f"{platform} non-ready proxy asset must not include proxy_media_path")

    suggestion_items = suggestions.get("suggestions", [])
    if not isinstance(suggestion_items, list) or len(suggestion_items) != required_count:
        fail(f"{platform} replacement suggestions count mismatch")
    readme = readme_path.read_text(encoding="utf-8")
    if "local human-registered media" not in readme:
        fail(f"{platform} proxy README must state local human-registered boundary")
    if "does not search, download, purchase licenses, upload, publish, or open editing software" not in readme:
        fail(f"{platform} proxy README must state no external action boundary")


def _validate_licensed_media_proxy_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_licensed_media_proxy"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_licensed_media_proxy(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("licensed_media_proxy_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED licensed media proxy")
    if metadata.get("proxy_copy_complete_for_ready_media") is not True:
        fail(f"{step_id} metadata must confirm proxy copy completeness")
    if int(metadata.get("required_final_media_count") or 0) < 1:
        fail(f"{step_id} metadata must require final media")
    if int(metadata.get("proxy_copied_count") or 0) != int(metadata.get("ready_source_media_count") or 0):
        fail(f"{step_id} metadata copied count must match ready source count")
    if f"assets/{platform}/licensed_media/ingest_manifest.json" not in metadata.get("source_artifacts", []):
        fail(f"{step_id} source_artifacts must include licensed media ingest manifest")


def _validate_editor_replacement_instructions(run_dir: Path, platform: str) -> None:
    base_dir = run_dir / "assets" / platform / "edit" / "replacement_instructions"
    manifest_path = base_dir / "instruction_manifest.json"
    commands_path = base_dir / "replacement_commands.json"
    import_template_path = base_dir / "editor_import_template.fcpxml"
    checklist_path = base_dir / "human_confirmation_checklist.md"
    readme_path = base_dir / "README.md"
    for path in [manifest_path, commands_path, import_template_path, checklist_path, readme_path]:
        if not path.exists():
            fail(f"{platform} editor replacement instruction artifact is missing: {path.relative_to(run_dir)}")

    manifest = load_json(manifest_path)
    commands = load_json(commands_path)
    if manifest.get("schema_version") != "phase4.editor_replacement_instruction_manifest.v1":
        fail(f"{platform} editor instruction manifest has wrong schema_version")
    if manifest.get("artifact_type") != "editor_replacement_instructions":
        fail(f"{platform} editor instruction manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-editor-replacement-instruction-adapter":
        fail(f"{platform} editor instruction adapter mismatch")
    if manifest.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} editor instruction validation must pass")
    if manifest.get("manual_review_required") is not True:
        fail(f"{platform} editor instruction manifest must require manual review")
    if manifest.get("human_confirmation_required") is not True:
        fail(f"{platform} editor instruction manifest must require human confirmation")

    boundary = manifest.get("export_boundary", {})
    if boundary.get("editor_replacement_instructions") != EDITOR_REPLACEMENT_INSTRUCTION_BOUNDARY:
        fail(f"{platform} editor instruction boundary mismatch")
    if boundary.get("replacement_execution") != "not_performed":
        fail(f"{platform} editor instruction must not execute replacement")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{platform} editor instruction must not open editing software")
    if boundary.get("project_file_mutation") != "not_performed":
        fail(f"{platform} editor instruction must not mutate project files")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{platform} editor instruction boundary must mark {key} as not_performed")

    validation = manifest.get("validation", {})
    if validation.get("human_confirmation_gate_active") is not True:
        fail(f"{platform} editor instruction human confirmation gate must be active")
    if validation.get("replacement_execution_performed") is not False:
        fail(f"{platform} editor instruction must report no replacement execution")
    if validation.get("editing_software_opened") is not False:
        fail(f"{platform} editor instruction must report no editor opened")

    instructions = manifest.get("instructions", [])
    summary = manifest.get("summary", {})
    if not isinstance(instructions, list) or not instructions:
        fail(f"{platform} editor instruction manifest must contain instructions")
    if summary.get("instruction_count") != len(instructions):
        fail(f"{platform} editor instruction count mismatch")
    if summary.get("human_confirmation_required_count") != len(instructions):
        fail(f"{platform} every editor instruction must require human confirmation")
    for instruction in instructions:
        if not isinstance(instruction, dict):
            fail(f"{platform} editor instruction entries must be objects")
        if instruction.get("human_confirmation_required") is not True:
            fail(f"{platform} editor instruction entry must require human confirmation")
        if instruction.get("confirmation_gate_status") != "pending_human_confirmation":
            fail(f"{platform} editor instruction confirmation gate mismatch")
        if instruction.get("execution_status") != "not_executed":
            fail(f"{platform} editor instruction must not be executed")
        if instruction.get("editing_software_opened") is not False:
            fail(f"{platform} editor instruction entry must not open editing software")
        if instruction.get("instruction_status") == "ready_pending_human_confirmation":
            if instruction.get("can_execute_after_human_confirmation") is not True:
                fail(f"{platform} ready editor instruction must stay gated by human confirmation")
            proxy_path = instruction.get("proxy_media_path")
            if not isinstance(proxy_path, str) or not (run_dir / proxy_path).exists():
                fail(f"{platform} ready editor instruction proxy media is missing")
        elif instruction.get("can_execute_after_human_confirmation") is not False:
            fail(f"{platform} non-ready editor instruction must not be executable")

    if commands.get("schema_version") != "phase4.editor_replacement_commands.v1":
        fail(f"{platform} editor replacement commands have wrong schema_version")
    if commands.get("artifact_type") != "editor_replacement_commands":
        fail(f"{platform} editor replacement commands have wrong artifact_type")
    command_items = commands.get("commands", [])
    if not isinstance(command_items, list) or len(command_items) != len(instructions):
        fail(f"{platform} editor replacement command count mismatch")
    for command in command_items:
        if not isinstance(command, dict):
            fail(f"{platform} editor replacement command entries must be objects")
        if command.get("command_type") != "nle_broll_replacement":
            fail(f"{platform} editor replacement command type mismatch")
        if command.get("target_editor") != "fcpxml_compatible_editor":
            fail(f"{platform} editor replacement command target editor mismatch")
        if command.get("dry_run_only") is not True:
            fail(f"{platform} editor replacement command must be dry-run only")
        if command.get("human_confirmation_required") is not True:
            fail(f"{platform} editor replacement command must require human confirmation")
        if command.get("confirmation_gate_status") != "pending_human_confirmation":
            fail(f"{platform} editor replacement command confirmation gate mismatch")
        if command.get("execution_status") != "not_executed":
            fail(f"{platform} editor replacement command must not execute")

    try:
        root = ET.parse(import_template_path).getroot()
    except ET.ParseError as exc:
        fail(f"{platform} editor import template is not well-formed XML: {exc}")
    if root.tag != "fcpxml":
        fail(f"{platform} editor import template root must be fcpxml")

    checklist = checklist_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    if "Human Confirmation Gate" not in checklist:
        fail(f"{platform} editor confirmation checklist missing heading")
    if "No editing software was opened" not in checklist:
        fail(f"{platform} editor confirmation checklist missing no-editor boundary")
    if "dry-run automation contract" not in readme:
        fail(f"{platform} editor instruction README missing dry-run boundary")
    if "does not open editing software" not in readme:
        fail(f"{platform} editor instruction README missing no-editor boundary")


def _validate_editor_replacement_instructions_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_editor_replacement_instructions"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_editor_replacement_instructions(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("editor_replacement_instruction_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED editor replacement instructions")
    if metadata.get("human_confirmation_gate_active") is not True:
        fail(f"{step_id} metadata must keep human confirmation gate active")
    if metadata.get("replacement_execution_performed") is not False:
        fail(f"{step_id} metadata must report no replacement execution")
    for source in [
        f"assets/{platform}/licensed_media/replacement_suggestions.json",
        f"assets/{platform}/licensed_media/proxy_manifest.json",
        f"assets/{platform}/edit/export_manifest.json",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_editor_replacement_execution_boundary(
    boundary: dict,
    label: str,
    *,
    expected_boundary: str | None = None,
) -> None:
    boundary_state = boundary.get("editor_replacement_execution")
    if expected_boundary is not None:
        if boundary_state != expected_boundary:
            fail(f"{label} editor replacement execution boundary mismatch")
    elif boundary_state not in EXPECTED_EDITOR_REPLACEMENT_EXECUTION_BOUNDARIES:
        fail(f"{label} editor replacement execution boundary mismatch")
    if boundary.get("replacement_execution") != "not_performed":
        fail(f"{label} must not execute replacement")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{label} must not open editing software")
    if boundary.get("project_file_mutation") != "not_performed":
        fail(f"{label} must not mutate project files")
    if boundary.get("requires_explicit_human_approval") is not True:
        fail(f"{label} must require explicit human approval")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{label} must mark {key} as not_performed")


def _validate_editor_replacement_execution(run_dir: Path, platform: str) -> None:
    base_dir = run_dir / "assets" / platform / "edit" / "replacement_execution"
    manifest_path = base_dir / "execution_manifest.json"
    plan_path = base_dir / "execution_plan.json"
    audit_log_path = base_dir / "execution_audit_log.json"
    approval_request_path = base_dir / "human_execution_approval_request.md"
    readme_path = base_dir / "README.md"
    for path in [manifest_path, plan_path, audit_log_path, approval_request_path, readme_path]:
        if not path.exists():
            fail(f"{platform} editor replacement execution artifact is missing: {path.relative_to(run_dir)}")

    manifest = load_json(manifest_path)
    plan = load_json(plan_path)
    audit_log = load_json(audit_log_path)
    if manifest.get("schema_version") != "phase4.editor_replacement_execution_manifest.v1":
        fail(f"{platform} editor replacement execution manifest has wrong schema_version")
    if manifest.get("artifact_type") != "editor_replacement_execution":
        fail(f"{platform} editor replacement execution manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-editor-replacement-execution-adapter":
        fail(f"{platform} editor replacement execution adapter mismatch")
    if manifest.get("platform") != platform:
        fail(f"{platform} editor replacement execution platform mismatch")
    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} editor replacement execution validation must pass")
    if validation.get("human_execution_approval_required") is not True:
        fail(f"{platform} editor replacement execution must require approval")
    if validation.get("replacement_execution_performed") is not False:
        fail(f"{platform} editor replacement execution must report no replacement execution")
    if validation.get("editing_software_opened") is not False:
        fail(f"{platform} editor replacement execution must report no editing software opened")
    if validation.get("project_file_mutation_performed") is not False:
        fail(f"{platform} editor replacement execution must report no project mutation")
    if manifest.get("manual_review_required") is not True:
        fail(f"{platform} editor replacement execution manifest must require manual review")
    if manifest.get("human_execution_approval_required") is not True:
        fail(f"{platform} editor replacement execution manifest must require approval")
    _validate_editor_replacement_execution_boundary(manifest.get("export_boundary", {}), f"{platform} execution")

    execution_items = manifest.get("execution_items", [])
    summary = manifest.get("summary", {})
    if not isinstance(execution_items, list) or not execution_items:
        fail(f"{platform} editor replacement execution items must be non-empty")
    if int(summary.get("command_count") or 0) != len(execution_items):
        fail(f"{platform} editor replacement execution command count mismatch")
    for item in execution_items:
        if not isinstance(item, dict):
            fail(f"{platform} editor replacement execution items must be objects")
        if item.get("execution_performed") is not False:
            fail(f"{platform} editor replacement execution item must not execute")
        if item.get("editing_software_opened") is not False:
            fail(f"{platform} editor replacement execution item must not open editing software")
        if item.get("project_file_mutation_performed") is not False:
            fail(f"{platform} editor replacement execution item must not mutate project")
        if item.get("execution_mode") != "manual_execution_only":
            fail(f"{platform} editor replacement execution mode mismatch")
        status = str(item.get("execution_status") or "")
        if status == "ready_for_manual_execution":
            if item.get("human_execution_approved") is not True:
                fail(f"{platform} ready execution item must record human execution approval")
            proxy_path = item.get("proxy_media_path")
            if not isinstance(proxy_path, str) or not (run_dir / proxy_path).exists():
                fail(f"{platform} ready execution item proxy media is missing")
        elif not status.startswith("blocked_"):
            fail(f"{platform} execution item status must be blocked or ready for manual execution")

    if plan.get("schema_version") != "phase4.editor_replacement_execution_plan.v1":
        fail(f"{platform} editor replacement execution plan has wrong schema_version")
    if plan.get("artifact_type") != "editor_replacement_execution_plan":
        fail(f"{platform} editor replacement execution plan has wrong artifact_type")
    if plan.get("platform") != platform:
        fail(f"{platform} editor replacement execution plan platform mismatch")
    if plan.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} editor replacement execution plan validation must pass")
    _validate_editor_replacement_execution_boundary(plan.get("export_boundary", {}), f"{platform} execution plan")
    plan_commands = plan.get("commands", [])
    if not isinstance(plan_commands, list) or len(plan_commands) != len(execution_items):
        fail(f"{platform} editor replacement execution plan command count mismatch")
    for command in plan_commands:
        if command.get("execution_performed") is not False:
            fail(f"{platform} editor replacement execution plan command must not execute")
        if command.get("editing_software_opened") is not False:
            fail(f"{platform} editor replacement execution plan command must not open editing software")
        if command.get("project_file_mutation_performed") is not False:
            fail(f"{platform} editor replacement execution plan command must not mutate project")

    if audit_log.get("schema_version") != "phase4.editor_replacement_execution_audit_log.v1":
        fail(f"{platform} editor replacement execution audit log has wrong schema_version")
    if audit_log.get("artifact_type") != "editor_replacement_execution_audit_log":
        fail(f"{platform} editor replacement execution audit log has wrong artifact_type")
    _validate_editor_replacement_execution_boundary(audit_log.get("export_boundary", {}), f"{platform} execution audit")
    events = audit_log.get("events", [])
    if not isinstance(events, list) or not events:
        fail(f"{platform} editor replacement execution audit log must contain events")
    for event in events:
        if event.get("replacement_execution_performed") is not False:
            fail(f"{platform} editor replacement execution audit must not record execution")
        if event.get("editing_software_opened") is not False:
            fail(f"{platform} editor replacement execution audit must not record editing software opened")
        if event.get("project_file_mutation_performed") is not False:
            fail(f"{platform} editor replacement execution audit must not record project mutation")

    approval_request = approval_request_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    if "Editor Replacement Execution Approval Request" not in approval_request:
        fail(f"{platform} editor replacement execution approval request missing heading")
    if "No replacement was executed" not in approval_request:
        fail(f"{platform} editor replacement execution approval request missing no-execution boundary")
    if "auditable execution adapter plan" not in readme:
        fail(f"{platform} editor replacement execution README missing adapter plan wording")
    if "does not open editing software" not in readme:
        fail(f"{platform} editor replacement execution README missing no-editor boundary")


def _validate_editor_replacement_execution_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_editor_replacement_execution"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_editor_replacement_execution(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("editor_replacement_execution_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED editor replacement execution")
    if metadata.get("human_execution_approval_required") is not True:
        fail(f"{step_id} metadata must require explicit human approval")
    if metadata.get("replacement_execution_performed") is not False:
        fail(f"{step_id} metadata must report no replacement execution")
    if metadata.get("editing_software_opened") is not False:
        fail(f"{step_id} metadata must report no editing software opened")
    if metadata.get("project_file_mutation_performed") is not False:
        fail(f"{step_id} metadata must report no project mutation")
    for source in [
        f"assets/{platform}/edit/replacement_instructions/instruction_manifest.json",
        f"assets/{platform}/edit/replacement_instructions/replacement_commands.json",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_editor_project_mutation_boundary(
    boundary: dict,
    label: str,
    *,
    expected_boundary: str | None = None,
) -> None:
    boundary_state = boundary.get("editor_project_mutation_sandbox")
    if expected_boundary is not None:
        if boundary_state != expected_boundary:
            fail(f"{label} editor project mutation boundary mismatch")
    elif boundary_state not in EXPECTED_EDITOR_PROJECT_MUTATION_BOUNDARIES:
        fail(f"{label} editor project mutation boundary mismatch")
    if boundary.get("original_project_mutation") != "not_performed":
        fail(f"{label} must not mutate the original project")
    if boundary.get("replacement_execution") != "not_performed":
        fail(f"{label} must not execute replacement")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{label} must not open editing software")
    if boundary.get("project_file_mutation") != "patched_copy_only_original_not_mutated":
        fail(f"{label} project mutation policy mismatch")
    if boundary.get("requires_explicit_human_mutation_approval") is not True:
        fail(f"{label} must require explicit human mutation approval")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{label} must mark {key} as not_performed")


def _validate_editor_project_mutation_sandbox(run_dir: Path, platform: str) -> None:
    base_dir = run_dir / "assets" / platform / "edit" / "mutation_sandbox"
    manifest_path = base_dir / "mutation_manifest.json"
    patched_project_path = base_dir / "patched_project.fcpxml"
    diff_path = base_dir / "mutation_diff.json"
    rollback_path = base_dir / "rollback_manifest.json"
    audit_log_path = base_dir / "mutation_audit_log.json"
    checklist_path = base_dir / "human_final_review_checklist.md"
    readme_path = base_dir / "README.md"
    for path in [
        manifest_path,
        patched_project_path,
        diff_path,
        rollback_path,
        audit_log_path,
        checklist_path,
        readme_path,
    ]:
        if not path.exists():
            fail(f"{platform} editor project mutation artifact is missing: {path.relative_to(run_dir)}")

    manifest = load_json(manifest_path)
    mutation_diff = load_json(diff_path)
    rollback_manifest = load_json(rollback_path)
    audit_log = load_json(audit_log_path)

    patched_xml = patched_project_path.read_text(encoding="utf-8")
    xml_text = "\n".join(line for line in patched_xml.splitlines() if not line.strip().startswith("<!DOCTYPE"))
    try:
        ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        fail(f"{platform} patched project FCPXML is not well-formed XML: {exc}")

    if manifest.get("schema_version") != "phase4.editor_project_mutation_sandbox_manifest.v1":
        fail(f"{platform} editor project mutation manifest has wrong schema_version")
    if manifest.get("artifact_type") != "editor_project_mutation_sandbox":
        fail(f"{platform} editor project mutation manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-editor-project-mutation-sandbox-adapter":
        fail(f"{platform} editor project mutation adapter mismatch")
    if manifest.get("platform") != platform:
        fail(f"{platform} editor project mutation platform mismatch")
    if manifest.get("manual_review_required") is not True:
        fail(f"{platform} editor project mutation manifest must require manual review")
    if manifest.get("human_mutation_approval_required") is not True:
        fail(f"{platform} editor project mutation manifest must require approval")

    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} editor project mutation validation must pass")
    if validation.get("patched_copy_generated") is not True:
        fail(f"{platform} editor project mutation must generate patched copy")
    if validation.get("original_project_mutated") is not False:
        fail(f"{platform} editor project mutation must not mutate original project")
    if validation.get("replacement_execution_performed") is not False:
        fail(f"{platform} editor project mutation must not execute replacements")
    if validation.get("editing_software_opened") is not False:
        fail(f"{platform} editor project mutation must not open editing software")
    if validation.get("human_mutation_approval_required") is not True:
        fail(f"{platform} editor project mutation must require approval")
    _validate_editor_project_mutation_boundary(manifest.get("export_boundary", {}), f"{platform} mutation sandbox")

    mutation_items = manifest.get("mutation_items", [])
    summary = manifest.get("summary", {})
    if not isinstance(mutation_items, list) or not mutation_items:
        fail(f"{platform} editor project mutation items must be non-empty")
    if int(summary.get("execution_item_count") or 0) != len(mutation_items):
        fail(f"{platform} editor project mutation item count mismatch")
    for item in mutation_items:
        if not isinstance(item, dict):
            fail(f"{platform} editor project mutation items must be objects")
        if item.get("original_project_mutated") is not False:
            fail(f"{platform} editor project mutation item must not mutate original")
        if item.get("replacement_execution_performed") is not False:
            fail(f"{platform} editor project mutation item must not execute replacement")
        if item.get("editing_software_opened") is not False:
            fail(f"{platform} editor project mutation item must not open editing software")
        status = str(item.get("mutation_status") or "")
        if status != "sandbox_patch_applied" and not status.startswith("blocked_"):
            fail(f"{platform} editor project mutation status must be sandbox_patch_applied or blocked")
        if status == "sandbox_patch_applied":
            if item.get("mutation_applied") is not True:
                fail(f"{platform} applied sandbox mutation must mark mutation_applied")
            if not item.get("patched_src"):
                fail(f"{platform} applied sandbox mutation must include patched_src")

    if mutation_diff.get("schema_version") != "phase4.editor_project_mutation_diff.v1":
        fail(f"{platform} editor project mutation diff has wrong schema_version")
    if mutation_diff.get("artifact_type") != "editor_project_mutation_diff":
        fail(f"{platform} editor project mutation diff has wrong artifact_type")
    if mutation_diff.get("platform") != platform:
        fail(f"{platform} editor project mutation diff platform mismatch")
    _validate_editor_project_mutation_boundary(mutation_diff.get("export_boundary", {}), f"{platform} mutation diff")

    if rollback_manifest.get("schema_version") != "phase4.editor_project_mutation_rollback_manifest.v1":
        fail(f"{platform} editor project rollback manifest has wrong schema_version")
    if rollback_manifest.get("artifact_type") != "editor_project_mutation_rollback_manifest":
        fail(f"{platform} editor project rollback manifest has wrong artifact_type")
    if rollback_manifest.get("rollback_policy") != "discard_patched_copy_keep_original_project":
        fail(f"{platform} editor project rollback policy mismatch")
    if not isinstance(rollback_manifest.get("original_project_sha256"), str):
        fail(f"{platform} editor project rollback manifest missing original sha256")
    if not isinstance(rollback_manifest.get("patched_project_sha256"), str):
        fail(f"{platform} editor project rollback manifest missing patched sha256")

    if audit_log.get("schema_version") != "phase4.editor_project_mutation_audit_log.v1":
        fail(f"{platform} editor project mutation audit log has wrong schema_version")
    if audit_log.get("artifact_type") != "editor_project_mutation_audit_log":
        fail(f"{platform} editor project mutation audit log has wrong artifact_type")
    _validate_editor_project_mutation_boundary(audit_log.get("export_boundary", {}), f"{platform} mutation audit")
    events = audit_log.get("events", [])
    if not isinstance(events, list) or not events:
        fail(f"{platform} editor project mutation audit log must contain events")
    for event in events:
        if event.get("original_project_mutated") is not False:
            fail(f"{platform} editor project mutation audit must not record original mutation")
        if event.get("editing_software_opened") is not False:
            fail(f"{platform} editor project mutation audit must not record editor open")
        if event.get("replacement_execution_performed") is not False:
            fail(f"{platform} editor project mutation audit must not record replacement execution")

    checklist = checklist_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    if "Editor Project Mutation Sandbox Final Review" not in checklist:
        fail(f"{platform} editor project mutation checklist missing heading")
    if "does not open editing software" not in checklist:
        fail(f"{platform} editor project mutation checklist missing no-editor boundary")
    if "Editor Project Mutation Sandbox" not in readme:
        fail(f"{platform} editor project mutation README missing heading")
    if "never mutates the original project file" not in readme:
        fail(f"{platform} editor project mutation README missing original mutation boundary")


def _validate_editor_project_mutation_sandbox_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_editor_project_mutation_sandbox"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_editor_project_mutation_sandbox(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("editor_project_mutation_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED editor project mutation")
    if metadata.get("human_mutation_approval_required") is not True:
        fail(f"{step_id} metadata must require explicit mutation approval")
    if metadata.get("original_project_mutated") is not False:
        fail(f"{step_id} metadata must report no original project mutation")
    if metadata.get("patched_copy_generated") is not True:
        fail(f"{step_id} metadata must report patched copy generation")
    if metadata.get("editing_software_opened") is not False:
        fail(f"{step_id} metadata must report no editing software opened")
    if metadata.get("replacement_execution_performed") is not False:
        fail(f"{step_id} metadata must report no replacement execution")
    for source in [
        f"assets/{platform}/edit/replacement_execution/execution_manifest.json",
        f"assets/{platform}/edit/replacement_execution/execution_plan.json",
        f"assets/{platform}/edit/export_manifest.json",
        f"assets/{platform}/edit/project.fcpxml",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_editor_software_import_boundary(
    boundary: dict,
    label: str,
    *,
    expected_boundary: str | None = None,
) -> None:
    boundary_state = boundary.get("editor_software_import_executor")
    if expected_boundary is not None:
        if boundary_state != expected_boundary:
            fail(f"{label} editor software import boundary mismatch")
    elif boundary_state not in EXPECTED_EDITOR_SOFTWARE_IMPORT_BOUNDARIES:
        fail(f"{label} editor software import boundary mismatch")
    if boundary.get("software_import_execution") != "not_performed":
        fail(f"{label} must not perform software import")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{label} must not open editing software")
    if boundary.get("project_file_mutation") != "not_performed_by_executor":
        fail(f"{label} project mutation policy mismatch")
    if boundary.get("original_project_mutation") != "not_performed":
        fail(f"{label} must not mutate original project")
    if boundary.get("replacement_execution") != "not_performed":
        fail(f"{label} must not execute replacement")
    if boundary.get("requires_explicit_human_software_import_approval") is not True:
        fail(f"{label} must require explicit software import approval")
    if boundary.get("external_software_isolation") != "required_before_manual_launch":
        fail(f"{label} must require external software isolation")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{label} must mark {key} as not_performed")


def _validate_editor_software_import_executor(run_dir: Path, platform: str) -> None:
    base_dir = run_dir / "assets" / platform / "edit" / "software_import_executor"
    manifest_path = base_dir / "import_executor_manifest.json"
    import_plan_path = base_dir / "import_plan.json"
    import_commands_path = base_dir / "import_commands.json"
    audit_log_path = base_dir / "software_import_audit_log.json"
    rollback_safety_report_path = base_dir / "rollback_safety_report.json"
    execution_request_path = base_dir / "isolated_execution_request.md"
    readme_path = base_dir / "README.md"
    for path in [
        manifest_path,
        import_plan_path,
        import_commands_path,
        audit_log_path,
        rollback_safety_report_path,
        execution_request_path,
        readme_path,
    ]:
        if not path.exists():
            fail(f"{platform} editor software import artifact is missing: {path.relative_to(run_dir)}")

    manifest = load_json(manifest_path)
    import_plan = load_json(import_plan_path)
    import_commands = load_json(import_commands_path)
    audit_log = load_json(audit_log_path)
    rollback_safety_report = load_json(rollback_safety_report_path)

    if manifest.get("schema_version") != "phase4.editor_software_import_executor_manifest.v1":
        fail(f"{platform} editor software import manifest has wrong schema_version")
    if manifest.get("artifact_type") != "editor_software_import_executor":
        fail(f"{platform} editor software import manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-editor-software-import-executor-adapter":
        fail(f"{platform} editor software import adapter mismatch")
    if manifest.get("platform") != platform:
        fail(f"{platform} editor software import platform mismatch")
    if manifest.get("manual_review_required") is not True:
        fail(f"{platform} editor software import manifest must require manual review")
    if manifest.get("human_software_import_approval_required") is not True:
        fail(f"{platform} editor software import manifest must require approval")

    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} editor software import validation must pass")
    if validation.get("patched_project_exists") is not True:
        fail(f"{platform} editor software import must see patched project")
    if validation.get("rollback_available") is not True:
        fail(f"{platform} editor software import must see rollback safety")
    if validation.get("human_software_import_approval_required") is not True:
        fail(f"{platform} editor software import must require approval")
    if validation.get("software_import_execution_performed") is not False:
        fail(f"{platform} editor software import must not execute import")
    if validation.get("editing_software_opened") is not False:
        fail(f"{platform} editor software import must not open editing software")
    if validation.get("project_file_mutation_performed") is not False:
        fail(f"{platform} editor software import must not mutate project files")
    if validation.get("original_project_mutated") is not False:
        fail(f"{platform} editor software import must not mutate original project")
    if validation.get("replacement_execution_performed") is not False:
        fail(f"{platform} editor software import must not execute replacement")
    if validation.get("isolated_manual_launch_required") is not True:
        fail(f"{platform} editor software import must require isolated manual launch")
    _validate_editor_software_import_boundary(manifest.get("export_boundary", {}), f"{platform} software import")

    import_items = manifest.get("import_items", [])
    summary = manifest.get("summary", {})
    if not isinstance(import_items, list) or not import_items:
        fail(f"{platform} editor software import items must be non-empty")
    if int(summary.get("import_item_count") or 0) != len(import_items):
        fail(f"{platform} editor software import item count mismatch")
    for item in import_items:
        if not isinstance(item, dict):
            fail(f"{platform} editor software import items must be objects")
        if item.get("import_execution_performed") is not False:
            fail(f"{platform} editor software import item must not execute import")
        if item.get("editing_software_opened") is not False:
            fail(f"{platform} editor software import item must not open editing software")
        if item.get("project_file_mutation_performed") is not False:
            fail(f"{platform} editor software import item must not mutate project files")
        if item.get("upload_performed") is not False:
            fail(f"{platform} editor software import item must not upload")
        if item.get("publishing_performed") is not False:
            fail(f"{platform} editor software import item must not publish")
        status = str(item.get("import_status") or "")
        if status != "ready_for_isolated_manual_import" and not status.startswith("blocked_"):
            fail(f"{platform} editor software import status must be ready or blocked")

    if import_plan.get("schema_version") != "phase4.editor_software_import_plan.v1":
        fail(f"{platform} editor software import plan has wrong schema_version")
    if import_plan.get("artifact_type") != "editor_software_import_plan":
        fail(f"{platform} editor software import plan has wrong artifact_type")
    if import_plan.get("platform") != platform:
        fail(f"{platform} editor software import plan platform mismatch")
    _validate_editor_software_import_boundary(import_plan.get("export_boundary", {}), f"{platform} software import plan")

    if import_commands.get("schema_version") != "phase4.editor_software_import_commands.v1":
        fail(f"{platform} editor software import commands has wrong schema_version")
    if import_commands.get("artifact_type") != "editor_software_import_commands":
        fail(f"{platform} editor software import commands has wrong artifact_type")
    _validate_editor_software_import_boundary(import_commands.get("export_boundary", {}), f"{platform} software import commands")
    commands = import_commands.get("commands", [])
    if not isinstance(commands, list) or not commands:
        fail(f"{platform} editor software import commands must be non-empty")
    for command in commands:
        if command.get("command_type") != "editor_software_import":
            fail(f"{platform} editor software import command type mismatch")
        if command.get("isolated_execution_required") is not True:
            fail(f"{platform} editor software import command must require isolation")
        if command.get("auto_execute") is not False:
            fail(f"{platform} editor software import command must not auto-execute")
        if command.get("dry_run_only") is not True:
            fail(f"{platform} editor software import command must be dry-run")
        if command.get("human_software_import_approval_required") is not True:
            fail(f"{platform} editor software import command must require approval")
        if command.get("import_execution_performed") is not False:
            fail(f"{platform} editor software import command must not execute import")
        if command.get("editing_software_opened") is not False:
            fail(f"{platform} editor software import command must not open editing software")
        if command.get("project_file_mutation_performed") is not False:
            fail(f"{platform} editor software import command must not mutate project files")

    if audit_log.get("schema_version") != "phase4.editor_software_import_audit_log.v1":
        fail(f"{platform} editor software import audit log has wrong schema_version")
    if audit_log.get("artifact_type") != "editor_software_import_audit_log":
        fail(f"{platform} editor software import audit log has wrong artifact_type")
    _validate_editor_software_import_boundary(audit_log.get("export_boundary", {}), f"{platform} software import audit")
    events = audit_log.get("events", [])
    if not isinstance(events, list) or not events:
        fail(f"{platform} editor software import audit log must contain events")
    for event in events:
        if event.get("software_import_execution_performed") is not False:
            fail(f"{platform} editor software import audit must not record import execution")
        if event.get("editing_software_opened") is not False:
            fail(f"{platform} editor software import audit must not record editor open")
        if event.get("project_file_mutation_performed") is not False:
            fail(f"{platform} editor software import audit must not record project mutation")

    if rollback_safety_report.get("schema_version") != "phase4.editor_software_import_rollback_safety_report.v1":
        fail(f"{platform} editor software import rollback safety report has wrong schema_version")
    if rollback_safety_report.get("artifact_type") != "editor_software_import_rollback_safety_report":
        fail(f"{platform} editor software import rollback safety report has wrong artifact_type")
    if not rollback_safety_report.get("rollback_policy"):
        fail(f"{platform} editor software import rollback safety report must include policy")
    if rollback_safety_report.get("software_import_execution_performed") is not False:
        fail(f"{platform} editor software import rollback safety must not execute import")
    if rollback_safety_report.get("editing_software_opened") is not False:
        fail(f"{platform} editor software import rollback safety must not open editor")
    if rollback_safety_report.get("project_file_mutation_performed") is not False:
        fail(f"{platform} editor software import rollback safety must not mutate project")

    execution_request = execution_request_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    if "Editor Software Import Execution Request" not in execution_request:
        fail(f"{platform} editor software import request missing heading")
    if "No editing software was opened" not in execution_request:
        fail(f"{platform} editor software import request missing no-editor boundary")
    if "Editor Software Import Executor" not in readme:
        fail(f"{platform} editor software import README missing heading")
    if "does not open editing software" not in readme:
        fail(f"{platform} editor software import README missing no-editor boundary")


def _validate_editor_software_import_executor_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_editor_software_import_executor"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_editor_software_import_executor(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("editor_software_import_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED editor software import")
    if metadata.get("human_software_import_approval_required") is not True:
        fail(f"{step_id} metadata must require explicit software import approval")
    if metadata.get("software_import_execution_performed") is not False:
        fail(f"{step_id} metadata must report no software import execution")
    if metadata.get("editing_software_opened") is not False:
        fail(f"{step_id} metadata must report no editing software opened")
    if metadata.get("project_file_mutation_performed") is not False:
        fail(f"{step_id} metadata must report no project file mutation")
    for source in [
        f"assets/{platform}/edit/mutation_sandbox/mutation_manifest.json",
        f"assets/{platform}/edit/mutation_sandbox/mutation_diff.json",
        f"assets/{platform}/edit/mutation_sandbox/rollback_manifest.json",
        f"assets/{platform}/edit/mutation_sandbox/patched_project.fcpxml",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_editor_software_real_runner_boundary(
    boundary: dict,
    label: str,
    *,
    expected_boundary: str | None = None,
) -> None:
    boundary_state = boundary.get("editor_software_real_runner_sandbox")
    if expected_boundary is not None:
        if boundary_state != expected_boundary:
            fail(f"{label} editor software real runner boundary mismatch")
    elif boundary_state not in EXPECTED_EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARIES:
        fail(f"{label} editor software real runner boundary mismatch")
    if boundary.get("real_software_launch") != "not_performed":
        fail(f"{label} must not launch real editing software")
    if boundary.get("software_import_execution") != "not_performed":
        fail(f"{label} must not perform software import")
    if boundary.get("editing_software") != "not_opened":
        fail(f"{label} must not open editing software")
    if boundary.get("project_file_mutation") != "not_performed_by_runner":
        fail(f"{label} project mutation policy mismatch")
    if boundary.get("original_project_mutation") != "not_performed":
        fail(f"{label} must not mutate original project")
    if boundary.get("replacement_execution") != "not_performed":
        fail(f"{label} must not execute replacement")
    if boundary.get("requires_explicit_human_real_run_approval") is not True:
        fail(f"{label} must require explicit real-run approval")
    if boundary.get("external_process_isolation") != "required_before_human_launch":
        fail(f"{label} must require external process isolation")
    if boundary.get("process_spawn") != "not_performed":
        fail(f"{label} must not spawn a process")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{label} must mark {key} as not_performed")


def _validate_editor_software_real_runner_sandbox(run_dir: Path, platform: str) -> None:
    base_dir = run_dir / "assets" / platform / "edit" / "software_real_runner_sandbox"
    manifest_path = base_dir / "runner_sandbox_manifest.json"
    environment_path = base_dir / "runner_environment_snapshot.json"
    launch_plan_path = base_dir / "runner_launch_plan.json"
    command_preview_path = base_dir / "runner_command_preview.json"
    audit_log_path = base_dir / "runner_audit_log.json"
    evidence_path = base_dir / "runner_evidence_manifest.json"
    approval_request_path = base_dir / "human_real_run_approval_request.md"
    readme_path = base_dir / "README.md"
    for path in [
        manifest_path,
        environment_path,
        launch_plan_path,
        command_preview_path,
        audit_log_path,
        evidence_path,
        approval_request_path,
        readme_path,
    ]:
        if not path.exists():
            fail(f"{platform} editor software real runner artifact is missing: {path.relative_to(run_dir)}")

    manifest = load_json(manifest_path)
    environment = load_json(environment_path)
    launch_plan = load_json(launch_plan_path)
    command_preview = load_json(command_preview_path)
    audit_log = load_json(audit_log_path)
    evidence = load_json(evidence_path)

    if manifest.get("schema_version") != "phase4.editor_software_real_runner_sandbox_manifest.v1":
        fail(f"{platform} editor software real runner manifest has wrong schema_version")
    if manifest.get("artifact_type") != "editor_software_real_runner_sandbox":
        fail(f"{platform} editor software real runner manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-editor-software-real-runner-sandbox-adapter":
        fail(f"{platform} editor software real runner adapter mismatch")
    if manifest.get("platform") != platform:
        fail(f"{platform} editor software real runner platform mismatch")
    if manifest.get("manual_review_required") is not True:
        fail(f"{platform} editor software real runner manifest must require manual review")
    if manifest.get("human_real_run_approval_required") is not True:
        fail(f"{platform} editor software real runner must require approval")

    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} editor software real runner validation must pass")
    if int(manifest.get("summary", {}).get("runner_item_count") or 0) < 1:
        fail(f"{platform} editor software real runner items must be non-empty")
    for key in [
        "real_software_launch_performed",
        "software_import_execution_performed",
        "editing_software_opened",
        "project_file_mutation_performed",
        "process_spawned",
    ]:
        if validation.get(key) is not False:
            fail(f"{platform} editor software real runner must report {key}=false")
    if validation.get("human_real_run_approval_required") is not True:
        fail(f"{platform} editor software real runner must require human approval")
    if validation.get("manual_external_launch_required") is not True:
        fail(f"{platform} editor software real runner must require manual external launch")
    if validation.get("external_process_isolation_required") is not True:
        fail(f"{platform} editor software real runner must require external process isolation")
    _validate_editor_software_real_runner_boundary(manifest.get("export_boundary", {}), f"{platform} real runner")

    runner_items = manifest.get("runner_items", [])
    if not isinstance(runner_items, list) or not runner_items:
        fail(f"{platform} editor software real runner items must be non-empty")
    for item in runner_items:
        if not isinstance(item, dict):
            fail(f"{platform} editor software real runner items must be objects")
        for key in [
            "real_software_launch_performed",
            "software_import_execution_performed",
            "editing_software_opened",
            "project_file_mutation_performed",
            "process_spawned",
            "upload_performed",
            "publishing_performed",
        ]:
            if item.get(key) is not False:
                fail(f"{platform} editor software real runner item must report {key}=false")

    if environment.get("schema_version") != "phase4.editor_software_real_runner_environment_snapshot.v1":
        fail(f"{platform} editor software real runner environment schema mismatch")
    if environment.get("artifact_type") != "editor_software_real_runner_environment_snapshot":
        fail(f"{platform} editor software real runner environment type mismatch")
    if launch_plan.get("schema_version") != "phase4.editor_software_real_runner_launch_plan.v1":
        fail(f"{platform} editor software real runner launch plan schema mismatch")
    if launch_plan.get("artifact_type") != "editor_software_real_runner_launch_plan":
        fail(f"{platform} editor software real runner launch plan type mismatch")
    _validate_editor_software_real_runner_boundary(launch_plan.get("export_boundary", {}), f"{platform} real runner launch plan")
    if command_preview.get("schema_version") != "phase4.editor_software_real_runner_command_preview.v1":
        fail(f"{platform} editor software real runner command preview schema mismatch")
    if command_preview.get("artifact_type") != "editor_software_real_runner_command_preview":
        fail(f"{platform} editor software real runner command preview type mismatch")
    _validate_editor_software_real_runner_boundary(
        command_preview.get("export_boundary", {}),
        f"{platform} real runner command preview",
    )
    commands = command_preview.get("commands", [])
    if not isinstance(commands, list) or not commands:
        fail(f"{platform} editor software real runner commands must be non-empty")
    for command in commands:
        if command.get("command_type") != "editor_software_real_runner_sandbox":
            fail(f"{platform} editor software real runner command type mismatch")
        if command.get("external_sandbox_required") is not True:
            fail(f"{platform} editor software real runner command must require external sandbox")
        if command.get("auto_execute") is not False or command.get("dry_run_only") is not True:
            fail(f"{platform} editor software real runner command must be dry-run only")
        for key in [
            "real_software_launch_performed",
            "software_import_execution_performed",
            "editing_software_opened",
            "project_file_mutation_performed",
            "process_spawned",
            "upload_performed",
            "publishing_performed",
        ]:
            if command.get(key) is not False:
                fail(f"{platform} editor software real runner command must report {key}=false")

    if audit_log.get("schema_version") != "phase4.editor_software_real_runner_audit_log.v1":
        fail(f"{platform} editor software real runner audit schema mismatch")
    if audit_log.get("artifact_type") != "editor_software_real_runner_audit_log":
        fail(f"{platform} editor software real runner audit type mismatch")
    _validate_editor_software_real_runner_boundary(audit_log.get("export_boundary", {}), f"{platform} real runner audit")
    if evidence.get("schema_version") != "phase4.editor_software_real_runner_evidence_manifest.v1":
        fail(f"{platform} editor software real runner evidence schema mismatch")
    if evidence.get("artifact_type") != "editor_software_real_runner_evidence_manifest":
        fail(f"{platform} editor software real runner evidence type mismatch")
    if evidence.get("evidence_collection_status") != "not_started_no_real_software_launch":
        fail(f"{platform} editor software real runner evidence status mismatch")
    if evidence.get("real_software_launch_performed") is not False:
        fail(f"{platform} editor software real runner evidence must not record launch")

    approval_request = approval_request_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    if "Editor Software Real Runner Sandbox Approval Request" not in approval_request:
        fail(f"{platform} editor software real runner approval request missing heading")
    if "did not launch editing software" not in approval_request:
        fail(f"{platform} editor software real runner approval request missing no-launch boundary")
    if "Editor Software Real Runner Sandbox" not in readme:
        fail(f"{platform} editor software real runner README missing heading")
    if "does not open editing software" not in readme:
        fail(f"{platform} editor software real runner README missing no-editor boundary")


def _validate_editor_software_real_runner_sandbox_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_editor_software_real_runner_sandbox"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_editor_software_real_runner_sandbox(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("editor_software_real_runner_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED editor software real runner")
    if metadata.get("human_real_run_approval_required") is not True:
        fail(f"{step_id} metadata must require explicit real-run approval")
    if metadata.get("real_software_launch_performed") is not False:
        fail(f"{step_id} metadata must report no real software launch")
    if metadata.get("process_spawned") is not False:
        fail(f"{step_id} metadata must report no process spawn")
    if metadata.get("editing_software_opened") is not False:
        fail(f"{step_id} metadata must report no editing software opened")
    if metadata.get("project_file_mutation_performed") is not False:
        fail(f"{step_id} metadata must report no project file mutation")
    for source in [
        f"assets/{platform}/edit/software_import_executor/import_executor_manifest.json",
        f"assets/{platform}/edit/software_import_executor/import_plan.json",
        f"assets/{platform}/edit/software_import_executor/import_commands.json",
        f"assets/{platform}/edit/software_import_executor/rollback_safety_report.json",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_editor_software_run_evidence_boundary(
    boundary: dict,
    label: str,
    *,
    expected_boundary: str | None = None,
) -> None:
    boundary_state = boundary.get("editor_software_run_evidence")
    if expected_boundary is not None:
        if boundary_state != expected_boundary:
            fail(f"{label} editor software run evidence boundary mismatch")
    elif boundary_state not in EXPECTED_EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARIES:
        fail(f"{label} editor software run evidence boundary mismatch")
    if boundary.get("real_software_launch_by_automation") != "not_performed":
        fail(f"{label} must not launch real editing software by automation")
    if boundary.get("software_import_execution_by_automation") != "not_performed":
        fail(f"{label} must not perform software import by automation")
    if boundary.get("editing_software") != "not_opened_by_automation":
        fail(f"{label} must not open editing software by automation")
    if boundary.get("project_file_mutation") != "not_performed_by_evidence_ingest":
        fail(f"{label} project mutation policy mismatch")
    if boundary.get("original_project_mutation") != "not_performed":
        fail(f"{label} must not mutate original project")
    if boundary.get("replacement_execution_by_automation") != "not_performed":
        fail(f"{label} must not execute replacement by automation")
    if boundary.get("process_spawn") != "not_performed":
        fail(f"{label} must not spawn a process")
    if boundary.get("evidence_ingest_only") is not True:
        fail(f"{label} must be evidence-ingest-only")
    if boundary.get("requires_human_real_run_result") is not True:
        fail(f"{label} must require human real-run result")
    for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
        if boundary.get(key) != "not_performed":
            fail(f"{label} must mark {key} as not_performed")


def _validate_editor_software_run_evidence(run_dir: Path, platform: str) -> None:
    base_dir = run_dir / "assets" / platform / "edit" / "software_run_evidence"
    manifest_path = base_dir / "real_run_evidence_manifest.json"
    validation_report_path = base_dir / "evidence_validation_report.json"
    rollback_report_path = base_dir / "rollback_decision_report.json"
    checklist_path = base_dir / "post_launch_evidence_checklist.md"
    readme_path = base_dir / "README.md"
    for path in [manifest_path, validation_report_path, rollback_report_path, checklist_path, readme_path]:
        if not path.exists():
            fail(f"{platform} editor software run evidence artifact is missing: {path.relative_to(run_dir)}")

    manifest = load_json(manifest_path)
    validation_report = load_json(validation_report_path)
    rollback_report = load_json(rollback_report_path)
    if manifest.get("schema_version") != "phase4.editor_software_run_evidence_manifest.v1":
        fail(f"{platform} editor software run evidence manifest has wrong schema_version")
    if manifest.get("artifact_type") != "editor_software_run_evidence":
        fail(f"{platform} editor software run evidence manifest has wrong artifact_type")
    if manifest.get("adapter") != "local-editor-software-run-evidence-adapter":
        fail(f"{platform} editor software run evidence adapter mismatch")
    if manifest.get("platform") != platform:
        fail(f"{platform} editor software run evidence platform mismatch")
    if manifest.get("manual_review_required") is not True:
        fail(f"{platform} editor software run evidence manifest must require manual review")
    if manifest.get("human_real_run_result_required") is not True:
        fail(f"{platform} editor software run evidence must require human result")

    validation = manifest.get("validation", {})
    if validation.get("status") != "PASSED":
        fail(f"{platform} editor software run evidence validation must pass")
    if int(manifest.get("summary", {}).get("evidence_item_count") or 0) < 1:
        fail(f"{platform} editor software run evidence items must be non-empty")
    for key in [
        "real_software_launch_performed_by_automation",
        "software_import_execution_performed_by_automation",
        "editing_software_opened_by_automation",
        "project_file_mutation_performed_by_automation",
        "process_spawned_by_automation",
        "upload_performed",
        "publishing_performed",
    ]:
        if validation.get(key) is not False:
            fail(f"{platform} editor software run evidence must report {key}=false")
    if validation.get("human_real_run_result_required") is not True:
        fail(f"{platform} editor software run evidence must require human result")
    _validate_editor_software_run_evidence_boundary(manifest.get("export_boundary", {}), f"{platform} run evidence")

    items = manifest.get("evidence_items", [])
    if not isinstance(items, list) or not items:
        fail(f"{platform} editor software run evidence items must be non-empty")
    for item in items:
        if not isinstance(item, dict):
            fail(f"{platform} editor software run evidence items must be objects")
        for key in [
            "real_software_launch_performed_by_automation",
            "software_import_execution_performed_by_automation",
            "editing_software_opened_by_automation",
            "project_file_mutation_performed_by_automation",
            "process_spawned_by_automation",
            "upload_performed",
            "publishing_performed",
        ]:
            if item.get(key) is not False:
                fail(f"{platform} editor software run evidence item must report {key}=false")

    if validation_report.get("schema_version") != "phase4.editor_software_run_evidence_validation_report.v1":
        fail(f"{platform} editor software run evidence validation report schema mismatch")
    if validation_report.get("artifact_type") != "editor_software_run_evidence_validation_report":
        fail(f"{platform} editor software run evidence validation report type mismatch")
    _validate_editor_software_run_evidence_boundary(
        validation_report.get("export_boundary", {}),
        f"{platform} run evidence validation report",
    )
    if rollback_report.get("schema_version") != "phase4.editor_software_run_evidence_rollback_decision_report.v1":
        fail(f"{platform} editor software run evidence rollback report schema mismatch")
    if rollback_report.get("artifact_type") != "editor_software_run_evidence_rollback_decision_report":
        fail(f"{platform} editor software run evidence rollback report type mismatch")
    _validate_editor_software_run_evidence_boundary(
        rollback_report.get("export_boundary", {}),
        f"{platform} run evidence rollback report",
    )

    checklist = checklist_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    if "Post-Launch Evidence Checklist" not in checklist:
        fail(f"{platform} editor software run evidence checklist missing heading")
    if "Automation process spawn: not performed" not in checklist:
        fail(f"{platform} editor software run evidence checklist missing no-spawn boundary")
    if "Editor Software Run Evidence" not in readme:
        fail(f"{platform} editor software run evidence README missing heading")
    if "does not launch editing software" not in readme:
        fail(f"{platform} editor software run evidence README missing no-launch boundary")


def _validate_editor_software_run_evidence_step(
    run_dir: Path,
    platform: str,
    modes_by_step: dict,
    logs_by_step: dict,
) -> None:
    step_id = f"{platform}_editor_software_run_evidence"
    if modes_by_step.get(step_id) != "agent-local":
        fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
    _validate_editor_software_run_evidence(run_dir, platform)
    metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
    if metadata.get("agent_interface") != "run_agent(task_spec)":
        fail(f"{step_id} task log does not prove run_agent(task_spec) execution")
    if metadata.get("editor_software_run_evidence_status") != "PASSED":
        fail(f"{step_id} metadata must report PASSED editor software run evidence")
    if metadata.get("human_real_run_result_required") is not True:
        fail(f"{step_id} metadata must require human real-run result")
    if metadata.get("real_software_launch_performed_by_automation") is not False:
        fail(f"{step_id} metadata must report no real software launch by automation")
    if metadata.get("process_spawned_by_automation") is not False:
        fail(f"{step_id} metadata must report no process spawn by automation")
    if metadata.get("editing_software_opened_by_automation") is not False:
        fail(f"{step_id} metadata must report no editing software opened by automation")
    if metadata.get("project_file_mutation_performed_by_automation") is not False:
        fail(f"{step_id} metadata must report no project file mutation by automation")
    for source in [
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_sandbox_manifest.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_launch_plan.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_command_preview.json",
        f"assets/{platform}/edit/software_real_runner_sandbox/runner_evidence_manifest.json",
    ]:
        if source not in metadata.get("source_artifacts", []):
            fail(f"{step_id} source_artifacts must include {source}")


def _validate_edit_project(run_dir: Path, platform: str, storyboard: list[dict]) -> None:
    timeline_path = run_dir / "assets" / platform / "edit" / "edit_timeline.json"
    manifest_path = run_dir / "assets" / platform / "edit" / "edit_manifest.json"
    edl_path = run_dir / "assets" / platform / "edit" / "draft_cut.edl"
    if not timeline_path.exists():
        fail(f"{platform} edit timeline is missing")
    if not manifest_path.exists():
        fail(f"{platform} edit manifest is missing")
    if not edl_path.exists():
        fail(f"{platform} draft EDL is missing")
    timeline = load_json(timeline_path)
    manifest = load_json(manifest_path)
    if timeline.get("schema_version") != "phase4.edit_timeline.v1":
        fail(f"{platform} edit timeline has wrong schema_version")
    if manifest.get("schema_version") != "phase4.edit_project_manifest.v1":
        fail(f"{platform} edit manifest has wrong schema_version")
    if timeline.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} edit timeline validation must pass")
    if manifest.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} edit manifest validation must pass")
    tracks = timeline.get("tracks", {})
    if len(tracks.get("video", [])) != len(storyboard):
        fail(f"{platform} edit timeline video clip count must match storyboard")
    if len(tracks.get("audio", [])) != 1:
        fail(f"{platform} edit timeline must include one voiceover audio clip")
    timed = load_json(run_dir / platform / "timed_subtitles.json")
    if len(tracks.get("subtitles", [])) != timed.get("subtitle_count"):
        fail(f"{platform} edit timeline subtitle clip count must match timed subtitles")
    material_refs = _material_reference_paths(run_dir, platform)
    if not material_refs:
        fail(f"{platform} edit timeline requires materialized B-roll references")
    broll_placeholders = [
        clip.get("broll_placeholder")
        for clip in tracks.get("video", [])
        if isinstance(clip, dict) and isinstance(clip.get("broll_placeholder"), dict)
    ]
    if len(broll_placeholders) < len(material_refs):
        fail(f"{platform} edit timeline must preserve materialized B-roll placeholders")
    for placeholder in broll_placeholders[: len(material_refs)]:
        reference_path = placeholder.get("reference_path")
        if reference_path not in material_refs:
            fail(f"{platform} edit B-roll placeholder missing material reference")
        if placeholder.get("reference_status") != "generated_reference_pending_review":
            fail(f"{platform} edit B-roll placeholder reference status mismatch")
        if placeholder.get("licensed_final_media_required") is not True:
            fail(f"{platform} edit B-roll placeholder must require licensed final media")
    licensed_by_reference = _licensed_media_by_reference(run_dir, platform)
    if licensed_by_reference:
        matched_count = 0
        for placeholder in broll_placeholders:
            reference_path = placeholder.get("reference_path")
            licensed_media = licensed_by_reference.get(str(reference_path))
            if not licensed_media:
                continue
            matched_count += 1
            if placeholder.get("licensed_media_ingest_manifest_path") != f"assets/{platform}/licensed_media/ingest_manifest.json":
                fail(f"{platform} edit B-roll placeholder missing licensed media ingest manifest path")
            if placeholder.get("licensed_media_review_handoff_path") != f"assets/{platform}/licensed_media/review_handoff.md":
                fail(f"{platform} edit B-roll placeholder missing licensed media review handoff path")
            if placeholder.get("licensed_media_intake_status") != licensed_media.get("intake_status"):
                fail(f"{platform} edit B-roll placeholder licensed media intake status mismatch")
            if placeholder.get("licensed_media_review_status") != licensed_media.get("review_status"):
                fail(f"{platform} edit B-roll placeholder licensed media review status mismatch")
            if placeholder.get("ready_for_editor_replacement") is not (licensed_media.get("ready_for_editor_replacement") is True):
                fail(f"{platform} edit B-roll placeholder editor replacement readiness mismatch")
        if matched_count < len(licensed_by_reference):
            fail(f"{platform} edit timeline must preserve licensed media ingest placeholders")
    proxy_by_reference = _licensed_media_proxy_by_reference(run_dir, platform)
    if proxy_by_reference:
        matched_count = 0
        for placeholder in broll_placeholders:
            reference_path = placeholder.get("reference_path")
            proxy_asset = proxy_by_reference.get(str(reference_path))
            if not proxy_asset:
                continue
            matched_count += 1
            if placeholder.get("licensed_media_proxy_manifest_path") != f"assets/{platform}/licensed_media/proxy_manifest.json":
                fail(f"{platform} edit B-roll placeholder missing licensed media proxy manifest path")
            if placeholder.get("licensed_media_replacement_suggestions_path") != f"assets/{platform}/licensed_media/replacement_suggestions.json":
                fail(f"{platform} edit B-roll placeholder missing replacement suggestions path")
            if placeholder.get("licensed_media_proxy_readme_path") != f"assets/{platform}/licensed_media/proxy/README.md":
                fail(f"{platform} edit B-roll placeholder missing proxy README path")
            if placeholder.get("replacement_status") != proxy_asset.get("replacement_status"):
                fail(f"{platform} edit B-roll placeholder proxy replacement status mismatch")
            if placeholder.get("proxy_copy_status") != proxy_asset.get("proxy_copy_status"):
                fail(f"{platform} edit B-roll placeholder proxy copy status mismatch")
            if placeholder.get("editor_replacement_ready") is not (proxy_asset.get("editor_replacement_ready") is True):
                fail(f"{platform} edit B-roll placeholder proxy readiness mismatch")
            if proxy_asset.get("editor_replacement_ready") is True:
                if placeholder.get("proxy_media_path") != proxy_asset.get("proxy_media_path"):
                    fail(f"{platform} edit B-roll placeholder proxy media path mismatch")
                proxy_path = placeholder.get("proxy_media_path")
                if not isinstance(proxy_path, str) or not (run_dir / proxy_path).exists():
                    fail(f"{platform} edit B-roll placeholder proxy media missing")
        if matched_count < len(proxy_by_reference):
            fail(f"{platform} edit timeline must preserve licensed media proxy placeholders")
    if "FCM: NON-DROP FRAME" not in edl_path.read_text(encoding="utf-8"):
        fail(f"{platform} draft EDL must include an EDL header")


def _validate_export_project(run_dir: Path, platform: str) -> None:
    project_path = run_dir / "assets" / platform / "edit" / "project.fcpxml"
    readme_path = run_dir / "assets" / platform / "edit" / "import_readme.md"
    offline_report_path = run_dir / "assets" / platform / "edit" / "offline_media_report.json"
    manifest_path = run_dir / "assets" / platform / "edit" / "export_manifest.json"
    for path in [project_path, readme_path, offline_report_path, manifest_path]:
        if not path.exists():
            fail(f"{platform} export project artifact is missing: {path.relative_to(run_dir)}")
    try:
        ET.parse(project_path)
    except ET.ParseError as exc:
        fail(f"{platform} project.fcpxml is not well-formed XML: {exc}")
    manifest = load_json(manifest_path)
    offline_report = load_json(offline_report_path)
    if manifest.get("schema_version") != "phase4.export_project_manifest.v1":
        fail(f"{platform} export manifest has wrong schema_version")
    if manifest.get("project_format") != "fcpxml":
        fail(f"{platform} export project format must be fcpxml")
    if manifest.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} export project validation must pass")
    if manifest.get("validation", {}).get("referenced_media_files_exist") is not True:
        fail(f"{platform} export project referenced media must exist")
    if offline_report.get("missing_source_count") != 0:
        fail(f"{platform} export project should have no missing storyboard/voiceover sources")
    if offline_report.get("offline_broll_count", 0) < 1:
        fail(f"{platform} export project must report offline B-roll slots")
    material_refs = _material_reference_paths(run_dir, platform)
    slots = offline_report.get("offline_broll_slots", [])
    if not isinstance(slots, list) or len(slots) < len(material_refs):
        fail(f"{platform} offline report must preserve materialized B-roll slots")
    for slot in slots[: len(material_refs)]:
        if slot.get("reference_path") not in material_refs:
            fail(f"{platform} offline B-roll slot missing material reference")
        if slot.get("status") not in EXPECTED_OFFLINE_BROLL_STATUSES:
            fail(f"{platform} offline B-roll slot status mismatch")
        if slot.get("licensed_final_media_required") is not True:
            fail(f"{platform} offline B-roll slot must require licensed final media")
    licensed_by_reference = _licensed_media_by_reference(run_dir, platform)
    if licensed_by_reference:
        matched_count = 0
        for slot in slots:
            licensed_media = licensed_by_reference.get(str(slot.get("reference_path")))
            if not licensed_media:
                continue
            matched_count += 1
            if slot.get("licensed_media_ingest_manifest_path") != f"assets/{platform}/licensed_media/ingest_manifest.json":
                fail(f"{platform} offline B-roll slot missing licensed media ingest manifest path")
            if slot.get("licensed_media_review_handoff_path") != f"assets/{platform}/licensed_media/review_handoff.md":
                fail(f"{platform} offline B-roll slot missing licensed media review handoff path")
            if slot.get("licensed_media_intake_status") != licensed_media.get("intake_status"):
                fail(f"{platform} offline B-roll slot licensed media intake status mismatch")
            if slot.get("ready_for_editor_replacement") is not (licensed_media.get("ready_for_editor_replacement") is True):
                fail(f"{platform} offline B-roll slot editor replacement readiness mismatch")
        if matched_count < len(licensed_by_reference):
            fail(f"{platform} offline report must preserve licensed media ingest slots")
    proxy_by_reference = _licensed_media_proxy_by_reference(run_dir, platform)
    if proxy_by_reference:
        matched_count = 0
        for slot in slots:
            proxy_asset = proxy_by_reference.get(str(slot.get("reference_path")))
            if not proxy_asset:
                continue
            matched_count += 1
            if slot.get("licensed_media_proxy_manifest_path") != f"assets/{platform}/licensed_media/proxy_manifest.json":
                fail(f"{platform} offline B-roll slot missing licensed media proxy manifest path")
            if slot.get("licensed_media_replacement_suggestions_path") != f"assets/{platform}/licensed_media/replacement_suggestions.json":
                fail(f"{platform} offline B-roll slot missing replacement suggestions path")
            if slot.get("licensed_media_proxy_readme_path") != f"assets/{platform}/licensed_media/proxy/README.md":
                fail(f"{platform} offline B-roll slot missing proxy README path")
            if slot.get("replacement_status") != proxy_asset.get("replacement_status"):
                fail(f"{platform} offline B-roll slot proxy replacement status mismatch")
            if slot.get("proxy_copy_status") != proxy_asset.get("proxy_copy_status"):
                fail(f"{platform} offline B-roll slot proxy copy status mismatch")
            if slot.get("editor_replacement_ready") is not (proxy_asset.get("editor_replacement_ready") is True):
                fail(f"{platform} offline B-roll slot proxy readiness mismatch")
            if proxy_asset.get("editor_replacement_ready") is True:
                if slot.get("status") != "proxy_ready_for_editor_replacement":
                    fail(f"{platform} offline B-roll slot should be proxy ready")
                if slot.get("proxy_media_path") != proxy_asset.get("proxy_media_path"):
                    fail(f"{platform} offline B-roll slot proxy media path mismatch")
        if matched_count < len(proxy_by_reference):
            fail(f"{platform} offline report must preserve licensed media proxy slots")
    if "Import the FCPXML" not in readme_path.read_text(encoding="utf-8"):
        fail(f"{platform} export import readme missing instructions")


def _validate_project_bundle(run_dir: Path, platform: str) -> None:
    bundle_path = run_dir / "assets" / platform / "bundle" / "project_bundle.zip"
    manifest_path = run_dir / "assets" / platform / "bundle" / "project_bundle_manifest.json"
    file_manifest_path = run_dir / "assets" / platform / "bundle" / "file_manifest.json"
    readme_path = run_dir / "assets" / platform / "bundle" / "README.md"
    for path in [bundle_path, manifest_path, file_manifest_path, readme_path]:
        if not path.exists():
            fail(f"{platform} project bundle artifact is missing: {path.relative_to(run_dir)}")
    manifest = load_json(manifest_path)
    file_manifest = load_json(file_manifest_path)
    if manifest.get("schema_version") != "phase4.project_bundle_manifest.v1":
        fail(f"{platform} project bundle manifest has wrong schema_version")
    if manifest.get("bundle_format") != "zip":
        fail(f"{platform} project bundle format must be zip")
    if manifest.get("validation", {}).get("status") != "PASSED":
        fail(f"{platform} project bundle validation must pass")
    if manifest.get("validation", {}).get("required_files_present") is not True:
        fail(f"{platform} project bundle required files must exist")
    if manifest.get("validation", {}).get("bundle_bytes", 0) <= 0:
        fail(f"{platform} project bundle must not be empty")
    if file_manifest.get("schema_version") != "phase4.project_bundle_file_manifest.v1":
        fail(f"{platform} project bundle file manifest has wrong schema_version")
    try:
        with ZipFile(bundle_path) as archive:
            archive_paths = set(archive.namelist())
    except BadZipFile as exc:
        fail(f"{platform} project bundle ZIP is invalid: {exc}")
    required_archive_paths = {
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
    missing_archive_paths = sorted(required_archive_paths - archive_paths)
    if missing_archive_paths:
        fail(f"{platform} project bundle missing archive paths: {missing_archive_paths}")
    material_refs = _material_reference_paths(run_dir, platform)
    for reference_path in material_refs:
        archive_path = f"materials/{Path(reference_path).name}"
        if archive_path not in archive_paths:
            fail(f"{platform} project bundle missing material reference: {archive_path}")
    licensed_media_dir = run_dir / "assets" / platform / "licensed_media"
    if (licensed_media_dir / "ingest_manifest.json").exists():
        for archive_path in [
            "licensed_media/ingest_manifest.json",
            "licensed_media/README.md",
            "licensed_media/review_handoff.md",
        ]:
            if archive_path not in archive_paths:
                fail(f"{platform} project bundle missing licensed media file: {archive_path}")
    proxy_manifest_path = licensed_media_dir / "proxy_manifest.json"
    if proxy_manifest_path.exists():
        for archive_path in [
            "licensed_media/proxy_manifest.json",
            "licensed_media/replacement_suggestions.json",
            "licensed_media/proxy/README.md",
        ]:
            if archive_path not in archive_paths:
                fail(f"{platform} project bundle missing licensed media proxy file: {archive_path}")
        proxy_manifest = load_json(proxy_manifest_path)
        for asset in proxy_manifest.get("proxy_assets", []):
            if not isinstance(asset, dict) or not asset.get("proxy_media_path"):
                continue
            archive_path = f"licensed_media/proxy/{Path(str(asset['proxy_media_path'])).name}"
            if archive_path not in archive_paths:
                fail(f"{platform} project bundle missing proxy media: {archive_path}")
    if "Open `project/project.fcpxml`" not in readme_path.read_text(encoding="utf-8"):
        fail(f"{platform} project bundle README missing import instructions")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    run_dir = resolve_run_dir(sys.argv[1] if len(sys.argv) > 1 else "")
    workflow_run = load_json(run_dir / "workflow_run.json")
    validate_state_store(run_dir, workflow_run)
    if workflow_run.get("status") != "DONE":
        fail(f"workflow status is not DONE: {workflow_run.get('status')}")

    task_runs = workflow_run.get("task_runs", [])
    if not task_runs:
        fail("workflow_run.json has no task_runs")
    failed = [item for item in task_runs if item.get("status") not in {"PASSED", "SKIPPED"}]
    if failed:
        fail(f"task runs not passed/skipped: {failed}")
    for task_run in task_runs:
        if task_run.get("status") == "SKIPPED":
            continue
        log_path = task_run.get("log_path")
        if not log_path:
            fail(f"task run has no log_path: {task_run.get('step_id')}")
        if not (run_dir / log_path).exists():
            fail(f"task log is missing: {log_path}")
        for artifact_path in task_run.get("artifact_paths", []):
            if not (run_dir / artifact_path).exists():
                fail(f"task declared artifact is missing: {artifact_path}")

    modes_by_step = {item.get("step_id"): item.get("execution_mode") for item in task_runs}
    logs_by_step = {}
    for task_run in task_runs:
        if task_run.get("status") == "SKIPPED" or not task_run.get("log_path"):
            continue
        logs_by_step[task_run.get("step_id")] = load_json(run_dir / task_run["log_path"])

    for step_id in ["research", "topic_angles", "master_outline"]:
        if modes_by_step.get(step_id) != "agent-local":
            fail(f"{step_id} must run through run_agent(task_spec); got {modes_by_step.get(step_id)!r}")
        metadata = logs_by_step.get(step_id, {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail(f"{step_id} task log does not prove run_agent(task_spec) execution")

    if "visual_assets" in modes_by_step:
        if modes_by_step.get("visual_assets") != "agent-local":
            fail(f"visual_assets must run through run_agent(task_spec); got {modes_by_step.get('visual_assets')!r}")
        metadata = logs_by_step.get("visual_assets", {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("visual_assets task log does not prove run_agent(task_spec) execution")
        if metadata.get("used_master_outline") is not True:
            fail("visual_assets did not declare use of master_outline.md")
        asset_plan = load_json(run_dir / "asset_plan.json")
        if asset_plan.get("generated_by") != "asset-agent":
            fail("asset_plan.json was not generated by asset-agent")
        if asset_plan.get("schema_version") != "phase4.asset_plan.v1":
            fail("asset_plan.json has wrong schema_version")
        if not (run_dir / "cover_prompts.md").exists():
            fail("cover_prompts.md is missing")
        for asset_pipeline_path in [
            "assets/asset_generation_tasks.json",
            "assets/media_asset_manifest.json",
            "assets/asset_ingest_guide.md",
        ]:
            if not (run_dir / asset_pipeline_path).exists():
                fail(f"asset pipeline artifact is missing: {asset_pipeline_path}")
        asset_tasks = load_json(run_dir / "assets/asset_generation_tasks.json")
        if asset_tasks.get("schema_version") != "phase4.asset_generation_tasks.v1":
            fail("asset_generation_tasks.json has wrong schema_version")
        media_manifest = load_json(run_dir / "assets/media_asset_manifest.json")
        if media_manifest.get("schema_version") != "phase4.media_asset_manifest.v1":
            fail("media_asset_manifest.json has wrong schema_version")

    text_proofs = {
        "research_report.md": "generated by `research-agent` through `run_agent(task_spec)`",
        "master_outline.md": "generated by `outline-agent` through `run_agent(task_spec)`",
    }
    for artifact_path, expected_text in text_proofs.items():
        path = run_dir / artifact_path
        if not path.exists():
            fail(f"missing agent-generated artifact: {artifact_path}")
        if expected_text not in path.read_text(encoding="utf-8"):
            fail(f"{artifact_path} does not contain expected run_agent proof text")

    angle_pack = load_json(run_dir / "angle_pack.json")
    if angle_pack.get("generated_by") != "topic-agent":
        fail("angle_pack.json was not generated by topic-agent")
    if angle_pack.get("agent_interface") != "run_agent(task_spec)":
        fail("angle_pack.json does not prove run_agent(task_spec) execution")
    if angle_pack.get("used_research_report") is not True:
        fail("angle_pack.json does not declare use of research_report.md")
    if "research_report.md" not in angle_pack.get("source_artifacts", []):
        fail("angle_pack.json source_artifacts must include research_report.md")
    if not angle_pack.get("angles"):
        fail("angle_pack.json has no angles")

    selected_platforms = workflow_run.get("platforms", [])
    if "wechat" in selected_platforms:
        if modes_by_step.get("wechat_article") != "agent-local":
            fail(f"wechat_article must run through run_agent(task_spec); got {modes_by_step.get('wechat_article')!r}")
        metadata = logs_by_step.get("wechat_article", {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("wechat_article task log does not prove run_agent(task_spec) execution")
        if metadata.get("used_angle_pack") is not True:
            fail("wechat_article did not declare use of angle_pack.json")
        if metadata.get("used_master_outline") is not True:
            fail("wechat_article did not declare use of master_outline.md")
        if metadata.get("used_research_report") is not True:
            fail("wechat_article did not declare use of research_report.md")
        for source in ["angle_pack.json", "master_outline.md", "research_report.md", "sources.json"]:
            if source not in metadata.get("source_artifacts", []):
                fail(f"wechat_article source_artifacts must include {source}")

        article_path = run_dir / "wechat/article.md"
        if not article_path.exists():
            fail("wechat article is missing")
        article = article_path.read_text(encoding="utf-8")
        if "agent-local 草稿" not in article:
            fail("wechat article must include agent-local draft review marker")
        if "## 参考来源状态" not in article:
            fail("wechat article must include source status section")
        if len(article) < 500:
            fail("wechat article must be at least 500 characters")

        titles = load_json(run_dir / "wechat/title_options.json")
        if titles.get("generated_by") != "wechat-article-agent":
            fail("wechat title_options.json was not generated by wechat-article-agent")
        if titles.get("agent_interface") != "run_agent(task_spec)":
            fail("wechat title_options.json does not prove run_agent(task_spec) execution")
        title_options = titles.get("title_options", [])
        if not isinstance(title_options, list) or len(title_options) < 3:
            fail("wechat title_options.json must contain at least 3 title options")
        if titles.get("review_required") is not True:
            fail("wechat title options must require human review")
        source_notes = titles.get("source_notes", [])
        if not isinstance(source_notes, list) or not source_notes:
            fail("wechat title_options.json must include source notes")

    if "xiaohongshu" in selected_platforms:
        if modes_by_step.get("xiaohongshu_note") != "agent-local":
            fail(f"xiaohongshu_note must run through run_agent(task_spec); got {modes_by_step.get('xiaohongshu_note')!r}")
        metadata = logs_by_step.get("xiaohongshu_note", {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("xiaohongshu_note task log does not prove run_agent(task_spec) execution")
        if metadata.get("used_angle_pack") is not True:
            fail("xiaohongshu_note did not declare use of angle_pack.json")
        if metadata.get("used_master_outline") is not True:
            fail("xiaohongshu_note did not declare use of master_outline.md")
        for source in ["angle_pack.json", "master_outline.md"]:
            if source not in metadata.get("source_artifacts", []):
                fail(f"xiaohongshu_note source_artifacts must include {source}")

        note = load_json(run_dir / "xiaohongshu/note.json")
        title = note.get("title", "")
        if not isinstance(title, str) or not title or len(title) > 20:
            fail("xiaohongshu note title must be non-empty and <= 20 characters")
        content = note.get("content", "")
        if not isinstance(content, str) or len(content) < 100:
            fail("xiaohongshu note content must be at least 100 characters")
        tags = note.get("tags", [])
        if not isinstance(tags, list) or not (5 <= len(tags) <= 8):
            fail("xiaohongshu note must contain 5-8 tags")
        if "#AI生成内容" not in tags:
            fail("xiaohongshu note must include #AI生成内容 tag")
        if note.get("review_required") is not True:
            fail("xiaohongshu note must require human review")
        if not note.get("cover_prompt") or not note.get("best_time") or not note.get("cta"):
            fail("xiaohongshu note is missing cover_prompt, best_time, or cta")
        cover_prompt = run_dir / "xiaohongshu/cover_prompt.md"
        if not cover_prompt.exists():
            fail("xiaohongshu cover prompt is missing")
        if "Xiaohongshu Cover Prompt" not in cover_prompt.read_text(encoding="utf-8"):
            fail("xiaohongshu cover prompt does not contain expected heading")

    if "douyin" in selected_platforms:
        if modes_by_step.get("douyin_cover_image") != "agent-local":
            fail(f"douyin_cover_image must run through run_agent(task_spec); got {modes_by_step.get('douyin_cover_image')!r}")
        _validate_generated_cover(run_dir, "douyin")
        if modes_by_step.get("douyin_video") != "agent-local":
            fail(f"douyin_video must run through run_agent(task_spec); got {modes_by_step.get('douyin_video')!r}")
        metadata = logs_by_step.get("douyin_video", {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_video task log does not prove run_agent(task_spec) execution")
        if metadata.get("used_angle_pack") is not True:
            fail("douyin_video did not declare use of angle_pack.json")
        if metadata.get("used_master_outline") is not True:
            fail("douyin_video did not declare use of master_outline.md")
        if "visual_assets" in modes_by_step and metadata.get("used_asset_plan") is not True:
            fail("douyin_video did not declare use of asset_plan.json")
        for source in ["angle_pack.json", "master_outline.md"]:
            if source not in metadata.get("source_artifacts", []):
                fail(f"douyin_video source_artifacts must include {source}")
        if "visual_assets" in modes_by_step and "asset_plan.json" not in metadata.get("source_artifacts", []):
            fail("douyin_video source_artifacts must include asset_plan.json")

        script_path = run_dir / "douyin/script.md"
        if not script_path.exists():
            fail("douyin script is missing")
        script = script_path.read_text(encoding="utf-8")
        for expected_text in ["## First 3 Seconds Hook", "## Shot List", "Review required: true"]:
            if expected_text not in script:
                fail(f"douyin script missing expected section: {expected_text}")
        if "不执行自动剪辑、上传或发布" not in script:
            fail("douyin script must state no automatic editing/upload/publishing")

        storyboard = load_json(run_dir / "douyin/storyboard.json")
        if not isinstance(storyboard, list) or len(storyboard) < 4:
            fail("douyin storyboard must contain at least 4 scenes")
        first_scene = storyboard[0]
        if not isinstance(first_scene, dict) or first_scene.get("duration_seconds") != 3:
            fail("douyin first storyboard scene must be a 3-second hook")
        for scene in storyboard:
            if not isinstance(scene, dict):
                fail("douyin storyboard scenes must be objects")
            for key in ["scene", "visual", "voiceover", "duration_seconds"]:
                if key not in scene:
                    fail(f"douyin storyboard scene missing key: {key}")

        subtitles_path = run_dir / "douyin/subtitles.srt"
        if not subtitles_path.exists():
            fail("douyin subtitles are missing")
        subtitles = subtitles_path.read_text(encoding="utf-8")
        if "00:00:00,000 --> 00:00:03,000" not in subtitles:
            fail("douyin subtitles must include a first 3-second hook block")
        if subtitles.count("-->") != len(storyboard):
            fail("douyin subtitles block count must match storyboard scene count")
        if modes_by_step.get("douyin_storyboard_preview") != "agent-local":
            fail(f"douyin_storyboard_preview must run through run_agent(task_spec); got {modes_by_step.get('douyin_storyboard_preview')!r}")
        _validate_generated_storyboard_preview(run_dir, "douyin", len(storyboard))
        preview_metadata = logs_by_step.get("douyin_storyboard_preview", {}).get("agent_result", {}).get("metadata", {})
        if preview_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_storyboard_preview task log does not prove run_agent(task_spec) execution")
        if preview_metadata.get("frame_count") != len(storyboard):
            fail("douyin_storyboard_preview metadata frame_count must match storyboard")
        for source in ["assets/asset_generation_tasks.json", "douyin/storyboard.json", "douyin/shot_list.json"]:
            if source not in preview_metadata.get("source_artifacts", []):
                fail(f"douyin_storyboard_preview source_artifacts must include {source}")
        if modes_by_step.get("douyin_asset_materialization") != "agent-local":
            fail(f"douyin_asset_materialization must run through run_agent(task_spec); got {modes_by_step.get('douyin_asset_materialization')!r}")
        _validate_materialized_assets(run_dir, "douyin")
        material_metadata = logs_by_step.get("douyin_asset_materialization", {}).get("agent_result", {}).get("metadata", {})
        if material_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_asset_materialization task log does not prove run_agent(task_spec) execution")
        if material_metadata.get("materialization_status") != "PASSED":
            fail("douyin_asset_materialization metadata must report PASSED materialization")
        if material_metadata.get("licensed_final_media_required") is not True:
            fail("douyin_asset_materialization must keep licensed final media required")
        for source in ["assets/asset_generation_tasks.json", "douyin/broll_list.json"]:
            if source not in material_metadata.get("source_artifacts", []):
                fail(f"douyin_asset_materialization source_artifacts must include {source}")
        _validate_licensed_media_ingest_step(run_dir, "douyin", modes_by_step, logs_by_step)
        _validate_licensed_media_proxy_step(run_dir, "douyin", modes_by_step, logs_by_step)
        if modes_by_step.get("douyin_subtitle_timing") != "agent-local":
            fail(f"douyin_subtitle_timing must run through run_agent(task_spec); got {modes_by_step.get('douyin_subtitle_timing')!r}")
        _validate_timed_subtitles(run_dir, "douyin", storyboard)
        subtitle_metadata = logs_by_step.get("douyin_subtitle_timing", {}).get("agent_result", {}).get("metadata", {})
        if subtitle_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_subtitle_timing task log does not prove run_agent(task_spec) execution")
        if subtitle_metadata.get("timeline_status") != "PASSED":
            fail("douyin_subtitle_timing metadata must report PASSED timeline")
        for source in ["douyin/storyboard.json", "douyin/shot_list.json", "douyin/subtitles.srt"]:
            if source not in subtitle_metadata.get("source_artifacts", []):
                fail(f"douyin_subtitle_timing source_artifacts must include {source}")
        if modes_by_step.get("douyin_voiceover_tts") != "agent-local":
            fail(f"douyin_voiceover_tts must run through run_agent(task_spec); got {modes_by_step.get('douyin_voiceover_tts')!r}")
        voiceover_manifest = _validate_voiceover_tts(run_dir, "douyin")
        voiceover_metadata = logs_by_step.get("douyin_voiceover_tts", {}).get("agent_result", {}).get("metadata", {})
        if voiceover_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_voiceover_tts task log does not prove run_agent(task_spec) execution")
        if voiceover_metadata.get("voiceover_status") != "PASSED":
            fail("douyin_voiceover_tts metadata must report PASSED voiceover")
        if voiceover_metadata.get("provider_external") is not voiceover_manifest.get("provider_external"):
            fail("douyin_voiceover_tts metadata must match manifest provider mode")
        for source in ["douyin/timed_subtitles.json", "douyin/timed_subtitles.srt"]:
            if source not in voiceover_metadata.get("source_artifacts", []):
                fail(f"douyin_voiceover_tts source_artifacts must include {source}")
        if modes_by_step.get("douyin_edit_project") != "agent-local":
            fail(f"douyin_edit_project must run through run_agent(task_spec); got {modes_by_step.get('douyin_edit_project')!r}")
        _validate_edit_project(run_dir, "douyin", storyboard)
        edit_metadata = logs_by_step.get("douyin_edit_project", {}).get("agent_result", {}).get("metadata", {})
        if edit_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_edit_project task log does not prove run_agent(task_spec) execution")
        if edit_metadata.get("timeline_status") != "PASSED":
            fail("douyin_edit_project metadata must report PASSED timeline")
        if modes_by_step.get("douyin_export_project") != "agent-local":
            fail(f"douyin_export_project must run through run_agent(task_spec); got {modes_by_step.get('douyin_export_project')!r}")
        _validate_export_project(run_dir, "douyin")
        export_metadata = logs_by_step.get("douyin_export_project", {}).get("agent_result", {}).get("metadata", {})
        if export_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_export_project task log does not prove run_agent(task_spec) execution")
        if export_metadata.get("export_status") != "PASSED":
            fail("douyin_export_project metadata must report PASSED export")
        _validate_editor_replacement_instructions_step(run_dir, "douyin", modes_by_step, logs_by_step)
        _validate_editor_replacement_execution_step(run_dir, "douyin", modes_by_step, logs_by_step)
        _validate_editor_project_mutation_sandbox_step(run_dir, "douyin", modes_by_step, logs_by_step)
        _validate_editor_software_import_executor_step(run_dir, "douyin", modes_by_step, logs_by_step)
        _validate_editor_software_real_runner_sandbox_step(run_dir, "douyin", modes_by_step, logs_by_step)
        _validate_editor_software_run_evidence_step(run_dir, "douyin", modes_by_step, logs_by_step)
        if modes_by_step.get("douyin_project_bundle") != "agent-local":
            fail(f"douyin_project_bundle must run through run_agent(task_spec); got {modes_by_step.get('douyin_project_bundle')!r}")
        _validate_project_bundle(run_dir, "douyin")
        bundle_metadata = logs_by_step.get("douyin_project_bundle", {}).get("agent_result", {}).get("metadata", {})
        if bundle_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("douyin_project_bundle task log does not prove run_agent(task_spec) execution")
        if bundle_metadata.get("bundle_status") != "PASSED":
            fail("douyin_project_bundle metadata must report PASSED bundle")
        if "visual_assets" in modes_by_step:
            for extra_path in ["douyin/shot_list.json", "douyin/broll_list.json", "douyin/cover_prompt.md"]:
                if not (run_dir / extra_path).exists():
                    fail(f"douyin video production deliverable is missing: {extra_path}")

    if "shipinhao" in selected_platforms:
        if modes_by_step.get("shipinhao_cover_image") != "agent-local":
            fail(f"shipinhao_cover_image must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_cover_image')!r}")
        _validate_generated_cover(run_dir, "shipinhao")
        if modes_by_step.get("shipinhao_video") != "agent-local":
            fail(f"shipinhao_video must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_video')!r}")
        metadata = logs_by_step.get("shipinhao_video", {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_video task log does not prove run_agent(task_spec) execution")
        if metadata.get("used_angle_pack") is not True:
            fail("shipinhao_video did not declare use of angle_pack.json")
        if metadata.get("used_master_outline") is not True:
            fail("shipinhao_video did not declare use of master_outline.md")
        if "visual_assets" in modes_by_step and metadata.get("used_asset_plan") is not True:
            fail("shipinhao_video did not declare use of asset_plan.json")
        for source in ["angle_pack.json", "master_outline.md"]:
            if source not in metadata.get("source_artifacts", []):
                fail(f"shipinhao_video source_artifacts must include {source}")
        if "visual_assets" in modes_by_step and "asset_plan.json" not in metadata.get("source_artifacts", []):
            fail("shipinhao_video source_artifacts must include asset_plan.json")

        script_path = run_dir / "shipinhao/script.md"
        if not script_path.exists():
            fail("shipinhao script is missing")
        script = script_path.read_text(encoding="utf-8")
        for expected_text in ["## First 3 Seconds Social Hook", "## Storyboard", "## Private Domain CTA", "Review required: true"]:
            if expected_text not in script:
                fail(f"shipinhao script missing expected section: {expected_text}")
        if "不执行自动剪辑、登录、上传、同步朋友圈或发布" not in script:
            fail("shipinhao script must state no automatic login/upload/sync/publishing")

        storyboard = load_json(run_dir / "shipinhao/storyboard.json")
        if not isinstance(storyboard, list) or len(storyboard) < 4:
            fail("shipinhao storyboard must contain at least 4 scenes")
        first_scene = storyboard[0]
        if not isinstance(first_scene, dict) or first_scene.get("duration_seconds") != 3:
            fail("shipinhao first storyboard scene must be a 3-second hook")
        for scene in storyboard:
            if not isinstance(scene, dict):
                fail("shipinhao storyboard scenes must be objects")
            for key in ["scene", "visual", "voiceover", "duration_seconds"]:
                if key not in scene:
                    fail(f"shipinhao storyboard scene missing key: {key}")

        subtitles_path = run_dir / "shipinhao/subtitles.srt"
        if not subtitles_path.exists():
            fail("shipinhao subtitles are missing")
        subtitles = subtitles_path.read_text(encoding="utf-8")
        if "00:00:00,000 --> 00:00:03,000" not in subtitles:
            fail("shipinhao subtitles must include a first 3-second hook block")
        if subtitles.count("-->") != len(storyboard):
            fail("shipinhao subtitles block count must match storyboard scene count")
        if modes_by_step.get("shipinhao_storyboard_preview") != "agent-local":
            fail(f"shipinhao_storyboard_preview must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_storyboard_preview')!r}")
        _validate_generated_storyboard_preview(run_dir, "shipinhao", len(storyboard))
        preview_metadata = logs_by_step.get("shipinhao_storyboard_preview", {}).get("agent_result", {}).get("metadata", {})
        if preview_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_storyboard_preview task log does not prove run_agent(task_spec) execution")
        if preview_metadata.get("frame_count") != len(storyboard):
            fail("shipinhao_storyboard_preview metadata frame_count must match storyboard")
        for source in ["assets/asset_generation_tasks.json", "shipinhao/storyboard.json", "shipinhao/shot_list.json"]:
            if source not in preview_metadata.get("source_artifacts", []):
                fail(f"shipinhao_storyboard_preview source_artifacts must include {source}")
        if modes_by_step.get("shipinhao_asset_materialization") != "agent-local":
            fail(f"shipinhao_asset_materialization must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_asset_materialization')!r}")
        _validate_materialized_assets(run_dir, "shipinhao")
        material_metadata = logs_by_step.get("shipinhao_asset_materialization", {}).get("agent_result", {}).get("metadata", {})
        if material_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_asset_materialization task log does not prove run_agent(task_spec) execution")
        if material_metadata.get("materialization_status") != "PASSED":
            fail("shipinhao_asset_materialization metadata must report PASSED materialization")
        if material_metadata.get("licensed_final_media_required") is not True:
            fail("shipinhao_asset_materialization must keep licensed final media required")
        for source in ["assets/asset_generation_tasks.json", "shipinhao/broll_list.json"]:
            if source not in material_metadata.get("source_artifacts", []):
                fail(f"shipinhao_asset_materialization source_artifacts must include {source}")
        _validate_licensed_media_ingest_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        _validate_licensed_media_proxy_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        if modes_by_step.get("shipinhao_subtitle_timing") != "agent-local":
            fail(f"shipinhao_subtitle_timing must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_subtitle_timing')!r}")
        _validate_timed_subtitles(run_dir, "shipinhao", storyboard)
        subtitle_metadata = logs_by_step.get("shipinhao_subtitle_timing", {}).get("agent_result", {}).get("metadata", {})
        if subtitle_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_subtitle_timing task log does not prove run_agent(task_spec) execution")
        if subtitle_metadata.get("timeline_status") != "PASSED":
            fail("shipinhao_subtitle_timing metadata must report PASSED timeline")
        for source in ["shipinhao/storyboard.json", "shipinhao/shot_list.json", "shipinhao/subtitles.srt"]:
            if source not in subtitle_metadata.get("source_artifacts", []):
                fail(f"shipinhao_subtitle_timing source_artifacts must include {source}")
        if modes_by_step.get("shipinhao_voiceover_tts") != "agent-local":
            fail(f"shipinhao_voiceover_tts must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_voiceover_tts')!r}")
        voiceover_manifest = _validate_voiceover_tts(run_dir, "shipinhao")
        voiceover_metadata = logs_by_step.get("shipinhao_voiceover_tts", {}).get("agent_result", {}).get("metadata", {})
        if voiceover_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_voiceover_tts task log does not prove run_agent(task_spec) execution")
        if voiceover_metadata.get("voiceover_status") != "PASSED":
            fail("shipinhao_voiceover_tts metadata must report PASSED voiceover")
        if voiceover_metadata.get("provider_external") is not voiceover_manifest.get("provider_external"):
            fail("shipinhao_voiceover_tts metadata must match manifest provider mode")
        for source in ["shipinhao/timed_subtitles.json", "shipinhao/timed_subtitles.srt"]:
            if source not in voiceover_metadata.get("source_artifacts", []):
                fail(f"shipinhao_voiceover_tts source_artifacts must include {source}")
        if modes_by_step.get("shipinhao_edit_project") != "agent-local":
            fail(f"shipinhao_edit_project must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_edit_project')!r}")
        _validate_edit_project(run_dir, "shipinhao", storyboard)
        edit_metadata = logs_by_step.get("shipinhao_edit_project", {}).get("agent_result", {}).get("metadata", {})
        if edit_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_edit_project task log does not prove run_agent(task_spec) execution")
        if edit_metadata.get("timeline_status") != "PASSED":
            fail("shipinhao_edit_project metadata must report PASSED timeline")
        if modes_by_step.get("shipinhao_export_project") != "agent-local":
            fail(f"shipinhao_export_project must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_export_project')!r}")
        _validate_export_project(run_dir, "shipinhao")
        export_metadata = logs_by_step.get("shipinhao_export_project", {}).get("agent_result", {}).get("metadata", {})
        if export_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_export_project task log does not prove run_agent(task_spec) execution")
        if export_metadata.get("export_status") != "PASSED":
            fail("shipinhao_export_project metadata must report PASSED export")
        _validate_editor_replacement_instructions_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        _validate_editor_replacement_execution_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        _validate_editor_project_mutation_sandbox_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        _validate_editor_software_import_executor_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        _validate_editor_software_real_runner_sandbox_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        _validate_editor_software_run_evidence_step(run_dir, "shipinhao", modes_by_step, logs_by_step)
        if modes_by_step.get("shipinhao_project_bundle") != "agent-local":
            fail(f"shipinhao_project_bundle must run through run_agent(task_spec); got {modes_by_step.get('shipinhao_project_bundle')!r}")
        _validate_project_bundle(run_dir, "shipinhao")
        bundle_metadata = logs_by_step.get("shipinhao_project_bundle", {}).get("agent_result", {}).get("metadata", {})
        if bundle_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("shipinhao_project_bundle task log does not prove run_agent(task_spec) execution")
        if bundle_metadata.get("bundle_status") != "PASSED":
            fail("shipinhao_project_bundle metadata must report PASSED bundle")

        cover_prompt = run_dir / "shipinhao/cover_prompt.md"
        if not cover_prompt.exists():
            fail("shipinhao cover prompt is missing")
        if "Shipinhao Cover Prompt" not in cover_prompt.read_text(encoding="utf-8"):
            fail("shipinhao cover prompt does not contain expected heading")
        if "visual_assets" in modes_by_step:
            for extra_path in ["shipinhao/shot_list.json", "shipinhao/broll_list.json"]:
                if not (run_dir / extra_path).exists():
                    fail(f"shipinhao video production deliverable is missing: {extra_path}")

    if "bilibili" in selected_platforms:
        if modes_by_step.get("bilibili_cover_image") != "agent-local":
            fail(f"bilibili_cover_image must run through run_agent(task_spec); got {modes_by_step.get('bilibili_cover_image')!r}")
        _validate_generated_cover(run_dir, "bilibili")
        if modes_by_step.get("bilibili_video") != "agent-local":
            fail(f"bilibili_video must run through run_agent(task_spec); got {modes_by_step.get('bilibili_video')!r}")
        metadata = logs_by_step.get("bilibili_video", {}).get("agent_result", {}).get("metadata", {})
        if metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_video task log does not prove run_agent(task_spec) execution")
        if metadata.get("used_angle_pack") is not True:
            fail("bilibili_video did not declare use of angle_pack.json")
        if metadata.get("used_master_outline") is not True:
            fail("bilibili_video did not declare use of master_outline.md")
        if metadata.get("used_research_report") is not True:
            fail("bilibili_video did not declare use of research_report.md")
        if "visual_assets" in modes_by_step and metadata.get("used_asset_plan") is not True:
            fail("bilibili_video did not declare use of asset_plan.json")
        for source in ["angle_pack.json", "master_outline.md", "research_report.md"]:
            if source not in metadata.get("source_artifacts", []):
                fail(f"bilibili_video source_artifacts must include {source}")
        if "visual_assets" in modes_by_step and "asset_plan.json" not in metadata.get("source_artifacts", []):
            fail("bilibili_video source_artifacts must include asset_plan.json")

        script_path = run_dir / "bilibili/script.md"
        if not script_path.exists():
            fail("bilibili script is missing")
        script = script_path.read_text(encoding="utf-8")
        for expected_text in ["## Title Options", "## Viewer Expectation", "## Chapters", "## Full Script", "Review required: true"]:
            if expected_text not in script:
                fail(f"bilibili script missing expected section: {expected_text}")
        if "no upload, no publish" not in script:
            fail("bilibili script must state no upload/publish boundary")
        if len(script) < 1000:
            fail("bilibili script must be at least 1000 characters")

        chapters = load_json(run_dir / "bilibili/chapters.json")
        if not isinstance(chapters, list) or len(chapters) < 5:
            fail("bilibili chapters must contain at least 5 chapters")
        if chapters[0].get("time") != "00:00":
            fail("bilibili first chapter must start at 00:00")
        for chapter in chapters:
            if not isinstance(chapter, dict):
                fail("bilibili chapters must be objects")
            for key in ["time", "title"]:
                if key not in chapter:
                    fail(f"bilibili chapter missing key: {key}")

        description_path = run_dir / "bilibili/description.md"
        if not description_path.exists():
            fail("bilibili description is missing")
        description = description_path.read_text(encoding="utf-8")
        for expected_text in ["## 时间轴", "## 标签", "review_required: true"]:
            if expected_text not in description:
                fail(f"bilibili description missing expected section: {expected_text}")
        if "未执行上传或发布" not in description:
            fail("bilibili description must state no upload/publish action")
        storyboard = load_json(run_dir / "bilibili/storyboard.json")
        if not isinstance(storyboard, list) or len(storyboard) < 4:
            fail("bilibili storyboard must contain at least 4 scenes")
        subtitles_path = run_dir / "bilibili/subtitles.srt"
        if not subtitles_path.exists():
            fail("bilibili subtitles are missing")
        subtitles = subtitles_path.read_text(encoding="utf-8")
        if subtitles.count("-->") != len(storyboard):
            fail("bilibili subtitles block count must match storyboard scene count")
        if modes_by_step.get("bilibili_storyboard_preview") != "agent-local":
            fail(f"bilibili_storyboard_preview must run through run_agent(task_spec); got {modes_by_step.get('bilibili_storyboard_preview')!r}")
        _validate_generated_storyboard_preview(run_dir, "bilibili", len(storyboard))
        preview_metadata = logs_by_step.get("bilibili_storyboard_preview", {}).get("agent_result", {}).get("metadata", {})
        if preview_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_storyboard_preview task log does not prove run_agent(task_spec) execution")
        if preview_metadata.get("frame_count") != len(storyboard):
            fail("bilibili_storyboard_preview metadata frame_count must match storyboard")
        for source in ["assets/asset_generation_tasks.json", "bilibili/storyboard.json", "bilibili/shot_list.json"]:
            if source not in preview_metadata.get("source_artifacts", []):
                fail(f"bilibili_storyboard_preview source_artifacts must include {source}")
        if modes_by_step.get("bilibili_asset_materialization") != "agent-local":
            fail(f"bilibili_asset_materialization must run through run_agent(task_spec); got {modes_by_step.get('bilibili_asset_materialization')!r}")
        _validate_materialized_assets(run_dir, "bilibili")
        material_metadata = logs_by_step.get("bilibili_asset_materialization", {}).get("agent_result", {}).get("metadata", {})
        if material_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_asset_materialization task log does not prove run_agent(task_spec) execution")
        if material_metadata.get("materialization_status") != "PASSED":
            fail("bilibili_asset_materialization metadata must report PASSED materialization")
        if material_metadata.get("licensed_final_media_required") is not True:
            fail("bilibili_asset_materialization must keep licensed final media required")
        for source in ["assets/asset_generation_tasks.json", "bilibili/broll_list.json"]:
            if source not in material_metadata.get("source_artifacts", []):
                fail(f"bilibili_asset_materialization source_artifacts must include {source}")
        _validate_licensed_media_ingest_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        _validate_licensed_media_proxy_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        if modes_by_step.get("bilibili_subtitle_timing") != "agent-local":
            fail(f"bilibili_subtitle_timing must run through run_agent(task_spec); got {modes_by_step.get('bilibili_subtitle_timing')!r}")
        _validate_timed_subtitles(run_dir, "bilibili", storyboard)
        subtitle_metadata = logs_by_step.get("bilibili_subtitle_timing", {}).get("agent_result", {}).get("metadata", {})
        if subtitle_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_subtitle_timing task log does not prove run_agent(task_spec) execution")
        if subtitle_metadata.get("timeline_status") != "PASSED":
            fail("bilibili_subtitle_timing metadata must report PASSED timeline")
        for source in ["bilibili/storyboard.json", "bilibili/shot_list.json", "bilibili/subtitles.srt"]:
            if source not in subtitle_metadata.get("source_artifacts", []):
                fail(f"bilibili_subtitle_timing source_artifacts must include {source}")
        if modes_by_step.get("bilibili_voiceover_tts") != "agent-local":
            fail(f"bilibili_voiceover_tts must run through run_agent(task_spec); got {modes_by_step.get('bilibili_voiceover_tts')!r}")
        voiceover_manifest = _validate_voiceover_tts(run_dir, "bilibili")
        voiceover_metadata = logs_by_step.get("bilibili_voiceover_tts", {}).get("agent_result", {}).get("metadata", {})
        if voiceover_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_voiceover_tts task log does not prove run_agent(task_spec) execution")
        if voiceover_metadata.get("voiceover_status") != "PASSED":
            fail("bilibili_voiceover_tts metadata must report PASSED voiceover")
        if voiceover_metadata.get("provider_external") is not voiceover_manifest.get("provider_external"):
            fail("bilibili_voiceover_tts metadata must match manifest provider mode")
        for source in ["bilibili/timed_subtitles.json", "bilibili/timed_subtitles.srt"]:
            if source not in voiceover_metadata.get("source_artifacts", []):
                fail(f"bilibili_voiceover_tts source_artifacts must include {source}")
        if modes_by_step.get("bilibili_edit_project") != "agent-local":
            fail(f"bilibili_edit_project must run through run_agent(task_spec); got {modes_by_step.get('bilibili_edit_project')!r}")
        _validate_edit_project(run_dir, "bilibili", storyboard)
        edit_metadata = logs_by_step.get("bilibili_edit_project", {}).get("agent_result", {}).get("metadata", {})
        if edit_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_edit_project task log does not prove run_agent(task_spec) execution")
        if edit_metadata.get("timeline_status") != "PASSED":
            fail("bilibili_edit_project metadata must report PASSED timeline")
        if modes_by_step.get("bilibili_export_project") != "agent-local":
            fail(f"bilibili_export_project must run through run_agent(task_spec); got {modes_by_step.get('bilibili_export_project')!r}")
        _validate_export_project(run_dir, "bilibili")
        export_metadata = logs_by_step.get("bilibili_export_project", {}).get("agent_result", {}).get("metadata", {})
        if export_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_export_project task log does not prove run_agent(task_spec) execution")
        if export_metadata.get("export_status") != "PASSED":
            fail("bilibili_export_project metadata must report PASSED export")
        _validate_editor_replacement_instructions_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        _validate_editor_replacement_execution_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        _validate_editor_project_mutation_sandbox_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        _validate_editor_software_import_executor_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        _validate_editor_software_real_runner_sandbox_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        _validate_editor_software_run_evidence_step(run_dir, "bilibili", modes_by_step, logs_by_step)
        if modes_by_step.get("bilibili_project_bundle") != "agent-local":
            fail(f"bilibili_project_bundle must run through run_agent(task_spec); got {modes_by_step.get('bilibili_project_bundle')!r}")
        _validate_project_bundle(run_dir, "bilibili")
        bundle_metadata = logs_by_step.get("bilibili_project_bundle", {}).get("agent_result", {}).get("metadata", {})
        if bundle_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("bilibili_project_bundle task log does not prove run_agent(task_spec) execution")
        if bundle_metadata.get("bundle_status") != "PASSED":
            fail("bilibili_project_bundle metadata must report PASSED bundle")
        if "visual_assets" in modes_by_step:
            for extra_path in [
                "bilibili/storyboard.json",
                "bilibili/subtitles.srt",
                "bilibili/shot_list.json",
                "bilibili/broll_list.json",
                "bilibili/cover_prompt.md",
            ]:
                if not (run_dir / extra_path).exists():
                    fail(f"bilibili video production deliverable is missing: {extra_path}")

    artifact_manifest = load_json(run_dir / "artifact_manifest.json")
    for artifact in artifact_manifest.get("artifacts", []):
        artifact_path = run_dir / artifact["path"]
        if not artifact_path.exists():
            fail(f"declared artifact is missing: {artifact['path']}")

    package = load_json(run_dir / "final/content_package_manifest.json")
    if package.get("review_required") is not True:
        fail("content package must require human review")
    if package.get("platforms") != workflow_run.get("platforms"):
        fail("content package platforms do not match workflow run platforms")
    if "visual_assets" in modes_by_step:
        if package.get("video_production_package") != "final/video_production_package.json":
            fail("content package must reference final/video_production_package.json")
        if package.get("materialization_manifest") != "final/materialization_manifest.json":
            fail("content package must reference final/materialization_manifest.json")
        if package.get("licensed_media_ingest_manifest") != "final/licensed_media_ingest_manifest.json":
            fail("content package must reference final/licensed_media_ingest_manifest.json")
        if package.get("licensed_media_proxy_manifest") != "final/licensed_media_proxy_manifest.json":
            fail("content package must reference final/licensed_media_proxy_manifest.json")
        if package.get("editor_replacement_instruction_manifest") != "final/editor_replacement_instruction_manifest.json":
            fail("content package must reference final/editor_replacement_instruction_manifest.json")
        if package.get("editor_replacement_execution_manifest") != "final/editor_replacement_execution_manifest.json":
            fail("content package must reference final/editor_replacement_execution_manifest.json")
        if package.get("editor_project_mutation_manifest") != "final/editor_project_mutation_manifest.json":
            fail("content package must reference final/editor_project_mutation_manifest.json")
        if package.get("editor_software_import_manifest") != "final/editor_software_import_manifest.json":
            fail("content package must reference final/editor_software_import_manifest.json")
        if package.get("editor_software_real_runner_manifest") != "final/editor_software_real_runner_manifest.json":
            fail("content package must reference final/editor_software_real_runner_manifest.json")
        if package.get("editor_software_run_evidence_manifest") != "final/editor_software_run_evidence_manifest.json":
            fail("content package must reference final/editor_software_run_evidence_manifest.json")
        if package.get("edit_project_manifest") != "final/edit_project_manifest.json":
            fail("content package must reference final/edit_project_manifest.json")
        if package.get("export_project_manifest") != "final/export_project_manifest.json":
            fail("content package must reference final/export_project_manifest.json")
        if package.get("project_bundle_manifest") != "final/project_bundle_manifest.json":
            fail("content package must reference final/project_bundle_manifest.json")
        if package.get("delivery_index") != "final/delivery_index.json":
            fail("content package must reference final/delivery_index.json")
        if package.get("delivery_readme") != "final/delivery_readme.md":
            fail("content package must reference final/delivery_readme.md")
        if package.get("artifact_store_manifest") != "artifact_store/artifact_store_manifest.json":
            fail("content package must reference artifact_store/artifact_store_manifest.json")
        if package.get("artifact_store_readme") != "artifact_store/README.md":
            fail("content package must reference artifact_store/README.md")
        if package.get("artifact_store_download_index") != "artifact_store/download_index.md":
            fail("content package must reference artifact_store/download_index.md")
        if package.get("artifact_store_checksums") != "artifact_store/checksums.sha256":
            fail("content package must reference artifact_store/checksums.sha256")
        if package.get("external_mirror_plan") != "artifact_store/external_mirror_plan.json":
            fail("content package must reference artifact_store/external_mirror_plan.json")
        if package.get("external_mirror_sync_command_preview") != "artifact_store/sync_command_preview.md":
            fail("content package must reference artifact_store/sync_command_preview.md")
        if package.get("external_mirror_approval_request") != "artifact_store/human_distribution_approval_request.md":
            fail("content package must reference artifact_store/human_distribution_approval_request.md")
        if package.get("external_mirror_readme") != "artifact_store/external_mirror_readme.md":
            fail("content package must reference artifact_store/external_mirror_readme.md")
        if "final/materialization_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/materialization_manifest.json")
        if "final/licensed_media_ingest_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/licensed_media_ingest_manifest.json")
        if "final/licensed_media_proxy_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/licensed_media_proxy_manifest.json")
        if "final/editor_replacement_instruction_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/editor_replacement_instruction_manifest.json")
        if "final/editor_replacement_execution_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/editor_replacement_execution_manifest.json")
        if "final/editor_project_mutation_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/editor_project_mutation_manifest.json")
        if "final/editor_software_import_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/editor_software_import_manifest.json")
        if "final/editor_software_real_runner_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/editor_software_real_runner_manifest.json")
        if "final/editor_software_run_evidence_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/editor_software_run_evidence_manifest.json")
        if "final/edit_project_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/edit_project_manifest.json")
        if "final/export_project_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/export_project_manifest.json")
        if "final/project_bundle_manifest.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/project_bundle_manifest.json")
        if "final/delivery_index.json" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/delivery_index.json")
        if "final/delivery_readme.md" not in workflow_run.get("artifacts", []):
            fail("workflow artifacts must include final/delivery_readme.md")
        for artifact_store_path in [
            "artifact_store/artifact_store_manifest.json",
            "artifact_store/README.md",
            "artifact_store/download_index.md",
            "artifact_store/checksums.sha256",
            "artifact_store/manifests/delivery_index.json",
            "artifact_store/downloads/douyin_project_bundle.zip",
            "artifact_store/downloads/shipinhao_project_bundle.zip",
            "artifact_store/downloads/bilibili_project_bundle.zip",
        ]:
            if artifact_store_path not in workflow_run.get("artifacts", []):
                fail(f"workflow artifacts must include {artifact_store_path}")
        for external_mirror_path in [
            "artifact_store/external_mirror_plan.json",
            "artifact_store/sync_command_preview.md",
            "artifact_store/human_distribution_approval_request.md",
            "artifact_store/external_mirror_readme.md",
        ]:
            if external_mirror_path not in workflow_run.get("artifacts", []):
                fail(f"workflow artifacts must include {external_mirror_path}")
        if modes_by_step.get("delivery_index") != "agent-local":
            fail(f"delivery_index must run through run_agent(task_spec); got {modes_by_step.get('delivery_index')!r}")
        delivery_metadata = logs_by_step.get("delivery_index", {}).get("agent_result", {}).get("metadata", {})
        if delivery_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("delivery_index task log does not prove run_agent(task_spec) execution")
        if delivery_metadata.get("delivery_status") != "PASSED":
            fail("delivery_index metadata must report PASSED delivery")
        if modes_by_step.get("artifact_store") != "agent-local":
            fail(f"artifact_store must run through run_agent(task_spec); got {modes_by_step.get('artifact_store')!r}")
        artifact_store_metadata = logs_by_step.get("artifact_store", {}).get("agent_result", {}).get("metadata", {})
        if artifact_store_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("artifact_store task log does not prove run_agent(task_spec) execution")
        if artifact_store_metadata.get("artifact_store_status") != "PASSED":
            fail("artifact_store metadata must report PASSED")
        if artifact_store_metadata.get("external_storage_sync_performed") is not False:
            fail("artifact_store metadata must report no external storage sync")
        if artifact_store_metadata.get("upload_performed") is not False:
            fail("artifact_store metadata must report no upload")
        if artifact_store_metadata.get("publishing_performed") is not False:
            fail("artifact_store metadata must report no publishing")
        if modes_by_step.get("external_mirror_plan") != "agent-local":
            fail(
                f"external_mirror_plan must run through run_agent(task_spec); got {modes_by_step.get('external_mirror_plan')!r}"
            )
        external_mirror_metadata = logs_by_step.get("external_mirror_plan", {}).get("agent_result", {}).get("metadata", {})
        if external_mirror_metadata.get("agent_interface") != "run_agent(task_spec)":
            fail("external_mirror_plan task log does not prove run_agent(task_spec) execution")
        if external_mirror_metadata.get("external_mirror_plan_status") != "PASSED":
            fail("external_mirror_plan metadata must report PASSED")
        for key in [
            "external_storage_sync_performed",
            "upload_performed",
            "publishing_performed",
            "login_performed",
            "platform_action_performed",
            "network_access_performed",
        ]:
            if external_mirror_metadata.get(key) is not False:
                fail(f"external_mirror_plan metadata must report {key}=false")
        video_package = load_json(run_dir / "final/video_production_package.json")
        final_licensed_ingest_manifest = load_json(run_dir / "final/licensed_media_ingest_manifest.json")
        final_licensed_proxy_manifest = load_json(run_dir / "final/licensed_media_proxy_manifest.json")
        final_editor_instruction_manifest = load_json(run_dir / "final/editor_replacement_instruction_manifest.json")
        final_editor_execution_manifest = load_json(run_dir / "final/editor_replacement_execution_manifest.json")
        final_editor_mutation_manifest = load_json(run_dir / "final/editor_project_mutation_manifest.json")
        final_editor_import_manifest = load_json(run_dir / "final/editor_software_import_manifest.json")
        final_editor_real_runner_manifest = load_json(run_dir / "final/editor_software_real_runner_manifest.json")
        final_editor_run_evidence_manifest = load_json(run_dir / "final/editor_software_run_evidence_manifest.json")
        final_edit_manifest = load_json(run_dir / "final/edit_project_manifest.json")
        final_export_manifest = load_json(run_dir / "final/export_project_manifest.json")
        final_project_bundle_manifest = load_json(run_dir / "final/project_bundle_manifest.json")
        delivery_index = load_json(run_dir / "final/delivery_index.json")
        artifact_store_manifest = load_json(run_dir / "artifact_store/artifact_store_manifest.json")
        external_mirror_plan = load_json(run_dir / "artifact_store/external_mirror_plan.json")
        delivery_readme = run_dir / "final/delivery_readme.md"
        if not delivery_readme.exists():
            fail("missing final/delivery_readme.md")
        if video_package.get("schema_version") != "phase4.video_production_package.v1":
            fail("video production package has wrong schema_version")
        if video_package.get("asset_generation_tasks") != "assets/asset_generation_tasks.json":
            fail("video production package must reference assets/asset_generation_tasks.json")
        if video_package.get("media_asset_manifest") != "assets/media_asset_manifest.json":
            fail("video production package must reference assets/media_asset_manifest.json")
        if video_package.get("materialization_manifest") != "final/materialization_manifest.json":
            fail("video production package must reference final/materialization_manifest.json")
        if video_package.get("licensed_media_ingest_manifest") != "final/licensed_media_ingest_manifest.json":
            fail("video production package must reference final/licensed_media_ingest_manifest.json")
        if video_package.get("licensed_media_proxy_manifest") != "final/licensed_media_proxy_manifest.json":
            fail("video production package must reference final/licensed_media_proxy_manifest.json")
        if video_package.get("editor_replacement_instruction_manifest") != "final/editor_replacement_instruction_manifest.json":
            fail("video production package must reference final/editor_replacement_instruction_manifest.json")
        if video_package.get("editor_replacement_execution_manifest") != "final/editor_replacement_execution_manifest.json":
            fail("video production package must reference final/editor_replacement_execution_manifest.json")
        if video_package.get("editor_project_mutation_manifest") != "final/editor_project_mutation_manifest.json":
            fail("video production package must reference final/editor_project_mutation_manifest.json")
        if video_package.get("editor_software_import_manifest") != "final/editor_software_import_manifest.json":
            fail("video production package must reference final/editor_software_import_manifest.json")
        if video_package.get("editor_software_real_runner_manifest") != "final/editor_software_real_runner_manifest.json":
            fail("video production package must reference final/editor_software_real_runner_manifest.json")
        if video_package.get("editor_software_run_evidence_manifest") != "final/editor_software_run_evidence_manifest.json":
            fail("video production package must reference final/editor_software_run_evidence_manifest.json")
        if video_package.get("edit_project_manifest") != "final/edit_project_manifest.json":
            fail("video production package must reference final/edit_project_manifest.json")
        if video_package.get("export_project_manifest") != "final/export_project_manifest.json":
            fail("video production package must reference final/export_project_manifest.json")
        if video_package.get("project_bundle_manifest") != "final/project_bundle_manifest.json":
            fail("video production package must reference final/project_bundle_manifest.json")
        if not video_package.get("generated_assets"):
            fail("video production package must embed generated assets")
        final_materialization_manifest = load_json(run_dir / "final/materialization_manifest.json")
        if final_materialization_manifest.get("schema_version") != "phase4.materialization_bundle_manifest.v1":
            fail("final materialization manifest has wrong schema_version")
        if final_materialization_manifest.get("artifact_type") != "materialization_bundle":
            fail("final materialization manifest has wrong artifact_type")
        if final_materialization_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final materialization manifest validation must pass")
        if final_materialization_manifest.get("export_boundary", {}).get("asset_materialization") != "performed_locally_reference_only":
            fail("final materialization manifest must mark reference-only materialization")
        if final_materialization_manifest.get("export_boundary", {}).get("external_asset_search") != "not_performed":
            fail("final materialization manifest must not search external assets")
        final_platform_materials = {
            item.get("platform"): item
            for item in final_materialization_manifest.get("platform_materials", [])
            if isinstance(item, dict)
        }
        if final_licensed_ingest_manifest.get("schema_version") != "phase4.licensed_media_ingest_bundle_manifest.v1":
            fail("final licensed media ingest manifest has wrong schema_version")
        if final_licensed_ingest_manifest.get("artifact_type") != "licensed_media_ingest_bundle":
            fail("final licensed media ingest manifest has wrong artifact_type")
        if final_licensed_ingest_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final licensed media ingest manifest validation must pass")
        if final_licensed_ingest_manifest.get("validation", {}).get("licensed_final_media_required") is not True:
            fail("final licensed media ingest manifest must require licensed final media")
        if int(final_licensed_ingest_manifest.get("validation", {}).get("required_final_media_count") or 0) < 1:
            fail("final licensed media ingest manifest must require at least one final media item")
        final_ingest_boundary = final_licensed_ingest_manifest.get("export_boundary", {})
        if final_ingest_boundary.get("licensed_media_ingest") != LICENSED_MEDIA_INGEST_BOUNDARY:
            fail("final licensed media ingest manifest boundary mismatch")
        if final_ingest_boundary.get("editing_software") != "not_opened":
            fail("final licensed media ingest manifest must not open editing software")
        for key in ["asset_download", "external_asset_search", "upload", "publishing"]:
            if final_ingest_boundary.get(key) != "not_performed":
                fail(f"final licensed media ingest manifest must mark {key} as not_performed")
        final_platform_ingests = {
            item.get("platform"): item
            for item in final_licensed_ingest_manifest.get("platform_ingests", [])
            if isinstance(item, dict)
        }
        if final_licensed_proxy_manifest.get("schema_version") != "phase4.licensed_media_proxy_bundle_manifest.v1":
            fail("final licensed media proxy manifest has wrong schema_version")
        if final_licensed_proxy_manifest.get("artifact_type") != "licensed_media_proxy_bundle":
            fail("final licensed media proxy manifest has wrong artifact_type")
        if final_licensed_proxy_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final licensed media proxy manifest validation must pass")
        if int(final_licensed_proxy_manifest.get("validation", {}).get("required_final_media_count") or 0) < 1:
            fail("final licensed media proxy manifest must require at least one final media item")
        if final_licensed_proxy_manifest.get("validation", {}).get("proxy_copy_complete_for_ready_media") is not True:
            fail("final licensed media proxy manifest must complete proxy copy for ready media")
        final_proxy_boundary = final_licensed_proxy_manifest.get("export_boundary", {})
        if final_proxy_boundary.get("licensed_media_proxy") != LICENSED_MEDIA_PROXY_BOUNDARY:
            fail("final licensed media proxy manifest boundary mismatch")
        if final_proxy_boundary.get("editing_software") != "not_opened":
            fail("final licensed media proxy manifest must not open editing software")
        for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
            if final_proxy_boundary.get(key) != "not_performed":
                fail(f"final licensed media proxy manifest must mark {key} as not_performed")
        final_platform_proxies = {
            item.get("platform"): item
            for item in final_licensed_proxy_manifest.get("platform_proxies", [])
            if isinstance(item, dict)
        }
        if final_editor_instruction_manifest.get("schema_version") != "phase4.editor_replacement_instruction_bundle_manifest.v1":
            fail("final editor replacement instruction manifest has wrong schema_version")
        if final_editor_instruction_manifest.get("artifact_type") != "editor_replacement_instruction_bundle":
            fail("final editor replacement instruction manifest has wrong artifact_type")
        if final_editor_instruction_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final editor replacement instruction manifest validation must pass")
        if final_editor_instruction_manifest.get("validation", {}).get("human_confirmation_gate_active") is not True:
            fail("final editor replacement instruction manifest must keep human confirmation gate active")
        if final_editor_instruction_manifest.get("validation", {}).get("replacement_execution_performed") is not False:
            fail("final editor replacement instruction manifest must report no replacement execution")
        if final_editor_instruction_manifest.get("validation", {}).get("editing_software_opened") is not False:
            fail("final editor replacement instruction manifest must report no editing software opened")
        if int(final_editor_instruction_manifest.get("validation", {}).get("instruction_count") or 0) < 1:
            fail("final editor replacement instruction manifest must contain instructions")
        final_instruction_boundary = final_editor_instruction_manifest.get("export_boundary", {})
        if final_instruction_boundary.get("editor_replacement_instructions") != EDITOR_REPLACEMENT_INSTRUCTION_BOUNDARY:
            fail("final editor replacement instruction manifest boundary mismatch")
        if final_instruction_boundary.get("replacement_execution") != "not_performed":
            fail("final editor replacement instruction manifest must not execute replacement")
        if final_instruction_boundary.get("editing_software") != "not_opened":
            fail("final editor replacement instruction manifest must not open editing software")
        if final_instruction_boundary.get("project_file_mutation") != "not_performed":
            fail("final editor replacement instruction manifest must not mutate project files")
        for key in ["asset_download", "external_asset_search", "license_purchase", "upload", "publishing"]:
            if final_instruction_boundary.get(key) != "not_performed":
                fail(f"final editor replacement instruction manifest must mark {key} as not_performed")
        final_platform_instructions = {
            item.get("platform"): item
            for item in final_editor_instruction_manifest.get("platform_instructions", [])
            if isinstance(item, dict)
        }
        if final_editor_execution_manifest.get("schema_version") != "phase4.editor_replacement_execution_bundle_manifest.v1":
            fail("final editor replacement execution manifest has wrong schema_version")
        if final_editor_execution_manifest.get("artifact_type") != "editor_replacement_execution_bundle":
            fail("final editor replacement execution manifest has wrong artifact_type")
        if final_editor_execution_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final editor replacement execution manifest validation must pass")
        if int(final_editor_execution_manifest.get("validation", {}).get("command_count") or 0) < 1:
            fail("final editor replacement execution manifest must contain commands")
        if final_editor_execution_manifest.get("validation", {}).get("human_execution_approval_required") is not True:
            fail("final editor replacement execution manifest must require explicit human approval")
        if final_editor_execution_manifest.get("validation", {}).get("replacement_execution_performed") is not False:
            fail("final editor replacement execution manifest must report no replacement execution")
        if final_editor_execution_manifest.get("validation", {}).get("editing_software_opened") is not False:
            fail("final editor replacement execution manifest must report no editing software opened")
        if final_editor_execution_manifest.get("validation", {}).get("project_file_mutation_performed") is not False:
            fail("final editor replacement execution manifest must report no project mutation")
        _validate_editor_replacement_execution_boundary(
            final_editor_execution_manifest.get("export_boundary", {}),
            "final editor replacement execution manifest",
        )
        final_platform_executions = {
            item.get("platform"): item
            for item in final_editor_execution_manifest.get("platform_executions", [])
            if isinstance(item, dict)
        }
        if final_editor_mutation_manifest.get("schema_version") != "phase4.editor_project_mutation_bundle_manifest.v1":
            fail("final editor project mutation manifest has wrong schema_version")
        if final_editor_mutation_manifest.get("artifact_type") != "editor_project_mutation_bundle":
            fail("final editor project mutation manifest has wrong artifact_type")
        if final_editor_mutation_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final editor project mutation manifest validation must pass")
        if int(final_editor_mutation_manifest.get("validation", {}).get("execution_item_count") or 0) < 1:
            fail("final editor project mutation manifest must contain execution items")
        if final_editor_mutation_manifest.get("validation", {}).get("human_mutation_approval_required") is not True:
            fail("final editor project mutation manifest must require explicit mutation approval")
        if final_editor_mutation_manifest.get("validation", {}).get("patched_copy_generated") is not True:
            fail("final editor project mutation manifest must report patched copy generation")
        if final_editor_mutation_manifest.get("validation", {}).get("original_project_mutated") is not False:
            fail("final editor project mutation manifest must report no original project mutation")
        if final_editor_mutation_manifest.get("validation", {}).get("replacement_execution_performed") is not False:
            fail("final editor project mutation manifest must report no replacement execution")
        if final_editor_mutation_manifest.get("validation", {}).get("editing_software_opened") is not False:
            fail("final editor project mutation manifest must report no editing software opened")
        _validate_editor_project_mutation_boundary(
            final_editor_mutation_manifest.get("export_boundary", {}),
            "final editor project mutation manifest",
        )
        final_platform_mutations = {
            item.get("platform"): item
            for item in final_editor_mutation_manifest.get("platform_mutations", [])
            if isinstance(item, dict)
        }
        if final_editor_import_manifest.get("schema_version") != "phase4.editor_software_import_bundle_manifest.v1":
            fail("final editor software import manifest has wrong schema_version")
        if final_editor_import_manifest.get("artifact_type") != "editor_software_import_bundle":
            fail("final editor software import manifest has wrong artifact_type")
        if final_editor_import_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final editor software import manifest validation must pass")
        if int(final_editor_import_manifest.get("validation", {}).get("import_item_count") or 0) < 1:
            fail("final editor software import manifest must contain import items")
        if final_editor_import_manifest.get("validation", {}).get("human_software_import_approval_required") is not True:
            fail("final editor software import manifest must require explicit software import approval")
        if final_editor_import_manifest.get("validation", {}).get("software_import_execution_performed") is not False:
            fail("final editor software import manifest must report no software import execution")
        if final_editor_import_manifest.get("validation", {}).get("editing_software_opened") is not False:
            fail("final editor software import manifest must report no editing software opened")
        if final_editor_import_manifest.get("validation", {}).get("project_file_mutation_performed") is not False:
            fail("final editor software import manifest must report no project file mutation")
        if final_editor_import_manifest.get("validation", {}).get("original_project_mutated") is not False:
            fail("final editor software import manifest must report no original project mutation")
        if final_editor_import_manifest.get("validation", {}).get("replacement_execution_performed") is not False:
            fail("final editor software import manifest must report no replacement execution")
        if final_editor_import_manifest.get("validation", {}).get("isolated_manual_launch_required") is not True:
            fail("final editor software import manifest must require isolated manual launch")
        _validate_editor_software_import_boundary(
            final_editor_import_manifest.get("export_boundary", {}),
            "final editor software import manifest",
        )
        final_platform_imports = {
            item.get("platform"): item
            for item in final_editor_import_manifest.get("platform_imports", [])
            if isinstance(item, dict)
        }
        if final_editor_real_runner_manifest.get("schema_version") != "phase4.editor_software_real_runner_bundle_manifest.v1":
            fail("final editor software real runner manifest has wrong schema_version")
        if final_editor_real_runner_manifest.get("artifact_type") != "editor_software_real_runner_bundle":
            fail("final editor software real runner manifest has wrong artifact_type")
        if final_editor_real_runner_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final editor software real runner manifest validation must pass")
        if int(final_editor_real_runner_manifest.get("validation", {}).get("runner_item_count") or 0) < 1:
            fail("final editor software real runner manifest must contain runner items")
        if final_editor_real_runner_manifest.get("validation", {}).get("human_real_run_approval_required") is not True:
            fail("final editor software real runner manifest must require explicit real-run approval")
        if final_editor_real_runner_manifest.get("validation", {}).get("real_software_launch_performed") is not False:
            fail("final editor software real runner manifest must report no real software launch")
        if final_editor_real_runner_manifest.get("validation", {}).get("software_import_execution_performed") is not False:
            fail("final editor software real runner manifest must report no software import")
        if final_editor_real_runner_manifest.get("validation", {}).get("editing_software_opened") is not False:
            fail("final editor software real runner manifest must report no editing software opened")
        if final_editor_real_runner_manifest.get("validation", {}).get("project_file_mutation_performed") is not False:
            fail("final editor software real runner manifest must report no project file mutation")
        if final_editor_real_runner_manifest.get("validation", {}).get("process_spawned") is not False:
            fail("final editor software real runner manifest must report no process spawn")
        if final_editor_real_runner_manifest.get("validation", {}).get("manual_external_launch_required") is not True:
            fail("final editor software real runner manifest must require manual external launch")
        _validate_editor_software_real_runner_boundary(
            final_editor_real_runner_manifest.get("export_boundary", {}),
            "final editor software real runner manifest",
        )
        final_platform_real_runners = {
            item.get("platform"): item
            for item in final_editor_real_runner_manifest.get("platform_runners", [])
            if isinstance(item, dict)
        }
        if final_editor_run_evidence_manifest.get("schema_version") != "phase4.editor_software_run_evidence_bundle_manifest.v1":
            fail("final editor software run evidence manifest has wrong schema_version")
        if final_editor_run_evidence_manifest.get("artifact_type") != "editor_software_run_evidence_bundle":
            fail("final editor software run evidence manifest has wrong artifact_type")
        if final_editor_run_evidence_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final editor software run evidence manifest validation must pass")
        if int(final_editor_run_evidence_manifest.get("validation", {}).get("evidence_item_count") or 0) < 1:
            fail("final editor software run evidence manifest must contain evidence items")
        if final_editor_run_evidence_manifest.get("validation", {}).get("human_real_run_result_required") is not True:
            fail("final editor software run evidence manifest must require human real-run result")
        if final_editor_run_evidence_manifest.get("validation", {}).get("real_software_launch_performed_by_automation") is not False:
            fail("final editor software run evidence manifest must report no automated real software launch")
        if final_editor_run_evidence_manifest.get("validation", {}).get("software_import_execution_performed_by_automation") is not False:
            fail("final editor software run evidence manifest must report no automated software import")
        if final_editor_run_evidence_manifest.get("validation", {}).get("editing_software_opened_by_automation") is not False:
            fail("final editor software run evidence manifest must report no automated editing software open")
        if final_editor_run_evidence_manifest.get("validation", {}).get("project_file_mutation_performed_by_automation") is not False:
            fail("final editor software run evidence manifest must report no automated project mutation")
        if final_editor_run_evidence_manifest.get("validation", {}).get("process_spawned_by_automation") is not False:
            fail("final editor software run evidence manifest must report no automated process spawn")
        _validate_editor_software_run_evidence_boundary(
            final_editor_run_evidence_manifest.get("export_boundary", {}),
            "final editor software run evidence manifest",
        )
        final_platform_run_evidence = {
            item.get("platform"): item
            for item in final_editor_run_evidence_manifest.get("platform_evidence", [])
            if isinstance(item, dict)
        }
        if final_edit_manifest.get("schema_version") != "phase4.edit_project_bundle_manifest.v1":
            fail("final edit project manifest has wrong schema_version")
        if final_edit_manifest.get("artifact_type") != "edit_project_bundle":
            fail("final edit project manifest has wrong artifact_type")
        if final_edit_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final edit project manifest validation must pass")
        final_edit_projects = {
            item.get("platform"): item
            for item in final_edit_manifest.get("platform_projects", [])
            if isinstance(item, dict)
        }
        if final_export_manifest.get("schema_version") != "phase4.export_project_bundle_manifest.v1":
            fail("final export project manifest has wrong schema_version")
        if final_export_manifest.get("artifact_type") != "export_project_bundle":
            fail("final export project manifest has wrong artifact_type")
        if final_export_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final export project manifest validation must pass")
        final_export_projects = {
            item.get("platform"): item
            for item in final_export_manifest.get("platform_projects", [])
            if isinstance(item, dict)
        }
        if final_project_bundle_manifest.get("schema_version") != "phase4.project_bundle_bundle_manifest.v1":
            fail("final project bundle manifest has wrong schema_version")
        if final_project_bundle_manifest.get("artifact_type") != "project_bundle_bundle":
            fail("final project bundle manifest has wrong artifact_type")
        if final_project_bundle_manifest.get("validation", {}).get("status") != "PASSED":
            fail("final project bundle manifest validation must pass")
        final_project_bundles = {
            item.get("platform"): item
            for item in final_project_bundle_manifest.get("platform_bundles", [])
            if isinstance(item, dict)
        }
        if delivery_index.get("schema_version") != "phase4.delivery_index.v1":
            fail("delivery index has wrong schema_version")
        if delivery_index.get("artifact_type") != "delivery_index":
            fail("delivery index has wrong artifact_type")
        if delivery_index.get("validation", {}).get("status") != "PASSED":
            fail("delivery index validation must pass")
        if delivery_index.get("archive_summary", {}).get("bundle_count") != len(final_project_bundles):
            fail("delivery index bundle count must match final project bundles")
        if delivery_index.get("export_boundary", {}).get("external_storage_sync") != "not_performed":
            fail("delivery index must not sync external storage")
        delivery_items = {
            item.get("platform"): item
            for item in delivery_index.get("download_items", [])
            if isinstance(item, dict)
        }
        for platform, item in delivery_items.items():
            bundle_path = run_dir / str(item.get("path"))
            if not bundle_path.exists():
                fail(f"{platform} delivery bundle path is missing")
            if item.get("bytes") != bundle_path.stat().st_size:
                fail(f"{platform} delivery bundle byte size mismatch")
            if item.get("sha256") != _sha256(bundle_path):
                fail(f"{platform} delivery bundle checksum mismatch")
        if artifact_store_manifest.get("schema_version") != "phase4.artifact_store_manifest.v1":
            fail("artifact store manifest has wrong schema_version")
        if artifact_store_manifest.get("artifact_type") != "artifact_store":
            fail("artifact store manifest has wrong artifact_type")
        if artifact_store_manifest.get("validation", {}).get("status") != "PASSED":
            fail("artifact store validation must pass")
        if artifact_store_manifest.get("store_summary", {}).get("download_count") != len(delivery_items):
            fail("artifact store download count must match delivery index")
        if artifact_store_manifest.get("store_summary", {}).get("all_sources_present") is not True:
            fail("artifact store must report all sources present")
        if artifact_store_manifest.get("store_summary", {}).get("all_checksums_match") is not True:
            fail("artifact store must report all checksums match")
        artifact_boundary = artifact_store_manifest.get("export_boundary", {})
        if artifact_boundary.get("artifact_store_generation") != "performed_locally_file_copy":
            fail("artifact store must mark local file copy generation")
        for key in ["external_storage_sync", "upload", "publishing", "login", "platform_action"]:
            if artifact_boundary.get(key) != "not_performed":
                fail(f"artifact store must mark {key} as not_performed")
        copied_delivery_index = load_json(run_dir / "artifact_store/manifests/delivery_index.json")
        if copied_delivery_index != delivery_index:
            fail("artifact store delivery index copy must match final delivery index")
        artifact_store_items = {
            item.get("platform"): item
            for item in artifact_store_manifest.get("downloads", [])
            if isinstance(item, dict)
        }
        checksums_text = (run_dir / "artifact_store/checksums.sha256").read_text(encoding="utf-8")
        for platform, delivery_item in delivery_items.items():
            store_item = artifact_store_items.get(platform)
            if not isinstance(store_item, dict):
                fail(f"{platform} artifact store entry is missing")
            source_path = run_dir / str(delivery_item.get("path"))
            store_path = run_dir / str(store_item.get("store_path"))
            if not store_path.exists():
                fail(f"{platform} artifact store bundle path is missing")
            if store_path.read_bytes() != source_path.read_bytes():
                fail(f"{platform} artifact store bundle bytes must match source")
            if store_item.get("sha256") != delivery_item.get("sha256"):
                fail(f"{platform} artifact store checksum must match delivery index")
            if store_item.get("checksum_matches_delivery_index") is not True:
                fail(f"{platform} artifact store must confirm checksum match")
            relative_store_path = str(store_item.get("store_path")).removeprefix("artifact_store/")
            if relative_store_path not in checksums_text:
                fail(f"{platform} artifact store checksums file missing download path")
            if str(store_item.get("sha256")) not in checksums_text:
                fail(f"{platform} artifact store checksums file missing checksum")
        if external_mirror_plan.get("schema_version") != "phase4.external_mirror_plan.v1":
            fail("external mirror plan has wrong schema_version")
        if external_mirror_plan.get("artifact_type") != "external_mirror_plan":
            fail("external mirror plan has wrong artifact_type")
        if external_mirror_plan.get("validation", {}).get("status") != "PASSED":
            fail("external mirror plan validation must pass")
        if external_mirror_plan.get("mirror_summary", {}).get("mirror_item_count") != len(artifact_store_items):
            fail("external mirror item count must match artifact store downloads")
        if external_mirror_plan.get("mirror_summary", {}).get("ready_source_count") != len(artifact_store_items):
            fail("external mirror ready source count must match artifact store downloads")
        if external_mirror_plan.get("mirror_summary", {}).get("approved_mirror_count") != 0:
            fail("external mirror must not approve any mirror item by default")
        mirror_boundary = external_mirror_plan.get("export_boundary", {})
        if mirror_boundary.get("external_mirror_plan_generation") != "performed_locally_plan_only":
            fail("external mirror plan must mark plan-only generation")
        for key in ["external_storage_sync", "upload", "publishing", "login", "platform_action", "network_access"]:
            if mirror_boundary.get(key) != "not_performed":
                fail(f"external mirror plan must mark {key} as not_performed")
        mirror_validation = external_mirror_plan.get("validation", {})
        for key in [
            "external_storage_sync_performed",
            "upload_performed",
            "publishing_performed",
            "login_performed",
            "platform_action_performed",
            "network_access_performed",
        ]:
            if mirror_validation.get(key) is not False:
                fail(f"external mirror plan validation must report {key}=false")
        mirror_items = {
            item.get("platform"): item
            for item in external_mirror_plan.get("mirror_items", [])
            if isinstance(item, dict)
        }
        sync_preview_text = (run_dir / "artifact_store/sync_command_preview.md").read_text(encoding="utf-8")
        approval_request_text = (
            run_dir / "artifact_store/human_distribution_approval_request.md"
        ).read_text(encoding="utf-8")
        readme_text = (run_dir / "artifact_store/external_mirror_readme.md").read_text(encoding="utf-8")
        if "# External Mirror Sync Command Preview" not in sync_preview_text:
            fail("external mirror sync command preview missing heading")
        if "# Preview only:" not in sync_preview_text:
            fail("external mirror sync command preview must be comment-only preview")
        if "# Human Distribution Approval Request" not in approval_request_text:
            fail("external mirror approval request missing heading")
        if "# External Mirror Plan" not in readme_text:
            fail("external mirror README missing heading")
        for platform, store_item in artifact_store_items.items():
            mirror_item = mirror_items.get(platform)
            if not isinstance(mirror_item, dict):
                fail(f"{platform} external mirror item is missing")
            source_path = run_dir / str(mirror_item.get("source_path"))
            if not source_path.exists():
                fail(f"{platform} external mirror source path is missing")
            if mirror_item.get("sha256") != _sha256(source_path):
                fail(f"{platform} external mirror checksum mismatch")
            if mirror_item.get("expected_sha256") != store_item.get("sha256"):
                fail(f"{platform} external mirror expected checksum must match artifact store")
            if mirror_item.get("checksum_verified") is not True:
                fail(f"{platform} external mirror checksum must verify")
            if mirror_item.get("mirror_status") != "blocked_pending_human_distribution_approval":
                fail(f"{platform} external mirror item must be blocked pending human approval")
            for key in [
                "external_storage_sync_performed",
                "upload_performed",
                "publishing_performed",
                "login_performed",
                "platform_action_performed",
            ]:
                if mirror_item.get(key) is not False:
                    fail(f"{platform} external mirror item must report {key}=false")
            if str(mirror_item.get("source_path")) not in sync_preview_text:
                fail(f"{platform} external mirror sync preview missing source path")
            if str(mirror_item.get("proposed_remote_key")) not in sync_preview_text:
                fail(f"{platform} external mirror sync preview missing remote key")
        if video_package.get("export_boundary", {}).get("cover_image_generation") != "performed_locally_pending_human_review":
            fail("video production package must mark cover generation as pending human review")
        if video_package.get("export_boundary", {}).get("storyboard_preview_generation") != "performed_locally_pending_human_review":
            fail("video production package must mark storyboard preview generation as pending human review")
        if video_package.get("export_boundary", {}).get("asset_materialization") != "performed_locally_reference_only":
            fail("video production package must mark asset materialization as reference-only")
        if video_package.get("export_boundary", {}).get("licensed_media_ingest") != LICENSED_MEDIA_INGEST_BOUNDARY:
            fail("video production package must mark licensed media ingest as review handoff only")
        if video_package.get("export_boundary", {}).get("licensed_media_proxy") != LICENSED_MEDIA_PROXY_BOUNDARY:
            fail("video production package must mark licensed media proxy as local human-registered copy only")
        if video_package.get("export_boundary", {}).get("editor_replacement_instructions") != EDITOR_REPLACEMENT_INSTRUCTION_BOUNDARY:
            fail("video production package must mark editor replacement instructions as template-only")
        if video_package.get("export_boundary", {}).get("editor_replacement_execution") != EDITOR_REPLACEMENT_EXECUTION_BOUNDARY:
            fail("video production package must mark editor replacement execution as blocked pending explicit human approval")
        if video_package.get("export_boundary", {}).get("editor_project_mutation_sandbox") != EDITOR_PROJECT_MUTATION_BOUNDARY:
            fail("video production package must mark editor project mutation sandbox as blocked pending explicit human mutation approval")
        if video_package.get("export_boundary", {}).get("editor_software_import_executor") != EDITOR_SOFTWARE_IMPORT_BOUNDARY:
            fail("video production package must mark editor software import executor as blocked pending explicit human software import approval")
        if video_package.get("export_boundary", {}).get("editor_software_real_runner_sandbox") != EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARY:
            fail("video production package must mark editor software real runner sandbox as blocked pending explicit human real-run approval")
        if video_package.get("export_boundary", {}).get("editor_software_run_evidence") != EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARY:
            fail("video production package must mark editor software run evidence as blocked pending human real-run result")
        if video_package.get("export_boundary", {}).get("external_asset_search") != "not_performed":
            fail("video production package must mark external asset search as not performed")
        if video_package.get("export_boundary", {}).get("subtitle_timing_correction") != "performed_locally_deterministic_no_tts":
            fail("video production package must mark subtitle timing correction as deterministic and no-TTS")
        if video_package.get("export_boundary", {}).get("voiceover_tts_generation") not in EXPECTED_VOICEOVER_TTS_BOUNDARIES:
            fail("video production package must mark voiceover TTS generation with a supported provider mode")
        if video_package.get("export_boundary", {}).get("edit_project_generation") != "performed_locally_draft_no_editing_software":
            fail("video production package must mark edit project generation as local draft without editing software")
        if video_package.get("export_boundary", {}).get("export_project_generation") != "performed_locally_draft_no_editing_software":
            fail("video production package must mark export project generation as local draft without editing software")
        if video_package.get("export_boundary", {}).get("project_bundle_generation") != "performed_locally_draft_no_editing_software":
            fail("video production package must mark project bundle generation as local draft without editing software")
        if video_package.get("review_required") is not True:
            fail("video production package must require human review")
        if not any(
            item.get("asset_type") == "storyboard_frame"
            for item in video_package.get("generated_assets", [])
            if isinstance(item, dict)
        ):
            fail("video production package must embed storyboard frame metadata")
        if not any(
            item.get("asset_type") == "broll_reference"
            for item in video_package.get("generated_assets", [])
            if isinstance(item, dict)
        ):
            fail("video production package must embed materialized B-roll reference metadata")
        for platform_package in video_package.get("platform_packages", []):
            if not isinstance(platform_package, dict):
                continue
            platform = platform_package.get("platform")
            deliverables = platform_package.get("deliverables", {})
            if "material_manifest" not in deliverables or "material_readme" not in deliverables:
                fail(f"{platform} video package must include materialization deliverables")
            for key in [
                "licensed_media_ingest_manifest",
                "licensed_media_ingest_readme",
                "licensed_media_review_handoff",
                "licensed_media_proxy_manifest",
                "licensed_media_replacement_suggestions",
                "licensed_media_proxy_readme",
                "editor_replacement_instruction_manifest",
                "editor_replacement_commands",
                "editor_import_template_fcpxml",
                "editor_human_confirmation_checklist",
                "editor_replacement_readme",
                "editor_replacement_execution_manifest",
                "editor_replacement_execution_plan",
                "editor_replacement_execution_audit_log",
                "editor_replacement_approval_request",
                "editor_replacement_execution_readme",
                "editor_project_mutation_manifest",
                "editor_project_patched_fcpxml",
                "editor_project_mutation_diff",
                "editor_project_rollback_manifest",
                "editor_project_mutation_audit_log",
                "editor_project_final_review_checklist",
                "editor_project_mutation_readme",
                "editor_software_import_manifest",
                "editor_software_import_plan",
                "editor_software_import_commands",
                "editor_software_import_audit_log",
                "editor_software_import_rollback_safety_report",
                "editor_software_import_execution_request",
                "editor_software_import_readme",
                "editor_software_real_runner_manifest",
                "editor_software_real_runner_environment_snapshot",
                "editor_software_real_runner_launch_plan",
                "editor_software_real_runner_command_preview",
                "editor_software_real_runner_audit_log",
                "editor_software_real_runner_evidence_manifest",
                "editor_software_real_runner_approval_request",
                "editor_software_real_runner_readme",
                "editor_software_run_evidence_manifest",
                "editor_software_run_evidence_validation_report",
                "editor_software_run_evidence_rollback_decision_report",
                "editor_software_run_evidence_checklist",
                "editor_software_run_evidence_readme",
            ]:
                if key not in deliverables:
                    fail(f"{platform} video package must include licensed/editor deliverable: {key}")
                if not (run_dir / str(deliverables[key])).exists():
                    fail(f"{platform} video package licensed/editor deliverable path is missing: {deliverables[key]}")
            material_summary = platform_package.get("materialized_assets", {})
            if material_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package materialized assets must pass validation")
            if material_summary.get("materialized_count", 0) < 1:
                fail(f"{platform} video package materialized assets must be non-empty")
            if material_summary.get("licensed_final_media_required") is not True:
                fail(f"{platform} video package materialized assets must require licensed final media")
            for reference_path in material_summary.get("reference_paths", []):
                if deliverables.get(f"material_reference_{Path(reference_path).stem.replace('_reference', '')}") != reference_path:
                    fail(f"{platform} video package missing material reference deliverable: {reference_path}")
                if not (run_dir / reference_path).exists():
                    fail(f"{platform} video package material reference path is missing: {reference_path}")
            final_material = final_platform_materials.get(platform)
            if not isinstance(final_material, dict):
                fail(f"{platform} final materialization manifest entry is missing")
            if final_material.get("manifest_path") != deliverables.get("material_manifest"):
                fail(f"{platform} final materialization manifest path mismatch")
            if final_material.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final materialization validation must pass")
            ingest_summary = platform_package.get("licensed_media_ingest", {})
            if ingest_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package licensed media ingest must pass validation")
            if int(ingest_summary.get("required_final_media_count") or 0) < 1:
                fail(f"{platform} video package licensed media ingest must require final media")
            if ingest_summary.get("licensed_final_media_required") is not True:
                fail(f"{platform} video package licensed media ingest must require licensed media")
            final_ingest = final_platform_ingests.get(platform)
            if not isinstance(final_ingest, dict):
                fail(f"{platform} final licensed media ingest manifest entry is missing")
            if final_ingest.get("manifest_path") != deliverables.get("licensed_media_ingest_manifest"):
                fail(f"{platform} final licensed media ingest manifest path mismatch")
            if final_ingest.get("readme_path") != deliverables.get("licensed_media_ingest_readme"):
                fail(f"{platform} final licensed media ingest README path mismatch")
            if final_ingest.get("review_handoff_path") != deliverables.get("licensed_media_review_handoff"):
                fail(f"{platform} final licensed media ingest handoff path mismatch")
            if final_ingest.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final licensed media ingest validation must pass")
            proxy_summary = platform_package.get("licensed_media_proxy", {})
            if proxy_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package licensed media proxy must pass validation")
            if int(proxy_summary.get("required_final_media_count") or 0) < 1:
                fail(f"{platform} video package licensed media proxy must require final media")
            if int(proxy_summary.get("proxy_copied_count") or 0) != int(proxy_summary.get("ready_source_media_count") or 0):
                fail(f"{platform} video package proxy copied count must match ready source count")
            if proxy_summary.get("proxy_copy_complete_for_ready_media") is not True:
                fail(f"{platform} video package proxy copy must be complete for ready media")
            if proxy_summary.get("review_required") is not True:
                fail(f"{platform} video package licensed media proxy must require review")
            final_proxy = final_platform_proxies.get(platform)
            if not isinstance(final_proxy, dict):
                fail(f"{platform} final licensed media proxy manifest entry is missing")
            if final_proxy.get("manifest_path") != deliverables.get("licensed_media_proxy_manifest"):
                fail(f"{platform} final licensed media proxy manifest path mismatch")
            if final_proxy.get("replacement_suggestions_path") != deliverables.get("licensed_media_replacement_suggestions"):
                fail(f"{platform} final licensed media proxy suggestions path mismatch")
            if final_proxy.get("readme_path") != deliverables.get("licensed_media_proxy_readme"):
                fail(f"{platform} final licensed media proxy README path mismatch")
            if final_proxy.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final licensed media proxy validation must pass")
            if final_proxy.get("validation", {}).get("proxy_copy_complete_for_ready_media") is not True:
                fail(f"{platform} final licensed media proxy copy completeness mismatch")
            for proxy_path in proxy_summary.get("proxy_media_paths", []):
                if not isinstance(proxy_path, str) or not (run_dir / proxy_path).exists():
                    fail(f"{platform} video package proxy media path is missing: {proxy_path}")
                asset_id = Path(proxy_path).stem.replace("_proxy", "")
                if deliverables.get(f"licensed_media_proxy_{asset_id}") != proxy_path:
                    fail(f"{platform} video package missing proxy media deliverable: {proxy_path}")
            instruction_summary = platform_package.get("editor_replacement_instructions", {})
            if instruction_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package editor replacement instructions must pass validation")
            if int(instruction_summary.get("instruction_count") or 0) < 1:
                fail(f"{platform} video package editor replacement instructions must be non-empty")
            if instruction_summary.get("human_confirmation_gate_active") is not True:
                fail(f"{platform} video package editor replacement instructions must keep human gate active")
            if instruction_summary.get("replacement_execution_performed") is not False:
                fail(f"{platform} video package editor replacement instructions must not execute replacements")
            if instruction_summary.get("editing_software_opened") is not False:
                fail(f"{platform} video package editor replacement instructions must not open editing software")
            if instruction_summary.get("human_confirmation_required") is not True:
                fail(f"{platform} video package editor replacement instructions must require human confirmation")
            final_instruction = final_platform_instructions.get(platform)
            if not isinstance(final_instruction, dict):
                fail(f"{platform} final editor replacement instruction manifest entry is missing")
            if final_instruction.get("manifest_path") != deliverables.get("editor_replacement_instruction_manifest"):
                fail(f"{platform} final editor instruction manifest path mismatch")
            if final_instruction.get("replacement_commands_path") != deliverables.get("editor_replacement_commands"):
                fail(f"{platform} final editor replacement commands path mismatch")
            if final_instruction.get("editor_import_template_path") != deliverables.get("editor_import_template_fcpxml"):
                fail(f"{platform} final editor import template path mismatch")
            if final_instruction.get("human_confirmation_checklist_path") != deliverables.get("editor_human_confirmation_checklist"):
                fail(f"{platform} final editor confirmation checklist path mismatch")
            if final_instruction.get("readme_path") != deliverables.get("editor_replacement_readme"):
                fail(f"{platform} final editor replacement README path mismatch")
            if final_instruction.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final editor replacement instruction validation must pass")
            if final_instruction.get("validation", {}).get("human_confirmation_gate_active") is not True:
                fail(f"{platform} final editor replacement instruction gate must be active")
            if final_instruction.get("validation", {}).get("replacement_execution_performed") is not False:
                fail(f"{platform} final editor replacement instruction must not execute replacements")
            execution_summary = platform_package.get("editor_replacement_execution", {})
            if execution_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package editor replacement execution must pass validation")
            if int(execution_summary.get("command_count") or 0) < 1:
                fail(f"{platform} video package editor replacement execution must be non-empty")
            if execution_summary.get("human_execution_approval_required") is not True:
                fail(f"{platform} video package editor replacement execution must require approval")
            if execution_summary.get("replacement_execution_performed") is not False:
                fail(f"{platform} video package editor replacement execution must not execute replacements")
            if execution_summary.get("editing_software_opened") is not False:
                fail(f"{platform} video package editor replacement execution must not open editing software")
            if execution_summary.get("project_file_mutation_performed") is not False:
                fail(f"{platform} video package editor replacement execution must not mutate project files")
            if execution_summary.get("review_required") is not True:
                fail(f"{platform} video package editor replacement execution must require review")
            if execution_summary.get("editor_replacement_execution") not in EXPECTED_EDITOR_REPLACEMENT_EXECUTION_BOUNDARIES:
                fail(f"{platform} video package editor replacement execution boundary mismatch")
            final_execution = final_platform_executions.get(platform)
            if not isinstance(final_execution, dict):
                fail(f"{platform} final editor replacement execution manifest entry is missing")
            if final_execution.get("manifest_path") != deliverables.get("editor_replacement_execution_manifest"):
                fail(f"{platform} final editor execution manifest path mismatch")
            if final_execution.get("execution_plan_path") != deliverables.get("editor_replacement_execution_plan"):
                fail(f"{platform} final editor execution plan path mismatch")
            if final_execution.get("audit_log_path") != deliverables.get("editor_replacement_execution_audit_log"):
                fail(f"{platform} final editor execution audit path mismatch")
            if final_execution.get("approval_request_path") != deliverables.get("editor_replacement_approval_request"):
                fail(f"{platform} final editor execution approval request path mismatch")
            if final_execution.get("readme_path") != deliverables.get("editor_replacement_execution_readme"):
                fail(f"{platform} final editor execution README path mismatch")
            if final_execution.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final editor replacement execution validation must pass")
            if final_execution.get("validation", {}).get("human_execution_approval_required") is not True:
                fail(f"{platform} final editor replacement execution must require approval")
            if final_execution.get("validation", {}).get("replacement_execution_performed") is not False:
                fail(f"{platform} final editor replacement execution must not execute replacements")
            mutation_summary = platform_package.get("editor_project_mutation_sandbox", {})
            if mutation_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package editor project mutation sandbox must pass validation")
            if int(mutation_summary.get("execution_item_count") or 0) < 1:
                fail(f"{platform} video package editor project mutation sandbox must be non-empty")
            if mutation_summary.get("human_mutation_approval_required") is not True:
                fail(f"{platform} video package editor project mutation sandbox must require approval")
            if mutation_summary.get("patched_copy_generated") is not True:
                fail(f"{platform} video package editor project mutation sandbox must generate patched copy")
            if mutation_summary.get("original_project_mutated") is not False:
                fail(f"{platform} video package editor project mutation sandbox must not mutate original project")
            if mutation_summary.get("replacement_execution_performed") is not False:
                fail(f"{platform} video package editor project mutation sandbox must not execute replacements")
            if mutation_summary.get("editing_software_opened") is not False:
                fail(f"{platform} video package editor project mutation sandbox must not open editing software")
            if mutation_summary.get("review_required") is not True:
                fail(f"{platform} video package editor project mutation sandbox must require review")
            if mutation_summary.get("editor_project_mutation_sandbox") not in EXPECTED_EDITOR_PROJECT_MUTATION_BOUNDARIES:
                fail(f"{platform} video package editor project mutation sandbox boundary mismatch")
            final_mutation = final_platform_mutations.get(platform)
            if not isinstance(final_mutation, dict):
                fail(f"{platform} final editor project mutation manifest entry is missing")
            if final_mutation.get("manifest_path") != deliverables.get("editor_project_mutation_manifest"):
                fail(f"{platform} final editor project mutation manifest path mismatch")
            if final_mutation.get("patched_project_path") != deliverables.get("editor_project_patched_fcpxml"):
                fail(f"{platform} final editor project mutation patched project path mismatch")
            if final_mutation.get("mutation_diff_path") != deliverables.get("editor_project_mutation_diff"):
                fail(f"{platform} final editor project mutation diff path mismatch")
            if final_mutation.get("rollback_manifest_path") != deliverables.get("editor_project_rollback_manifest"):
                fail(f"{platform} final editor project mutation rollback path mismatch")
            if final_mutation.get("audit_log_path") != deliverables.get("editor_project_mutation_audit_log"):
                fail(f"{platform} final editor project mutation audit path mismatch")
            if final_mutation.get("final_review_checklist_path") != deliverables.get("editor_project_final_review_checklist"):
                fail(f"{platform} final editor project mutation checklist path mismatch")
            if final_mutation.get("readme_path") != deliverables.get("editor_project_mutation_readme"):
                fail(f"{platform} final editor project mutation README path mismatch")
            if final_mutation.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final editor project mutation validation must pass")
            if final_mutation.get("validation", {}).get("patched_copy_generated") is not True:
                fail(f"{platform} final editor project mutation must generate patched copy")
            if final_mutation.get("validation", {}).get("original_project_mutated") is not False:
                fail(f"{platform} final editor project mutation must not mutate original project")
            if final_mutation.get("validation", {}).get("replacement_execution_performed") is not False:
                fail(f"{platform} final editor project mutation must not execute replacements")
            if final_mutation.get("validation", {}).get("editing_software_opened") is not False:
                fail(f"{platform} final editor project mutation must not open editing software")
            import_summary = platform_package.get("editor_software_import_executor", {})
            if import_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package editor software import executor must pass validation")
            if import_summary.get("editor_software_import_executor") not in EXPECTED_EDITOR_SOFTWARE_IMPORT_BOUNDARIES:
                fail(f"{platform} video package editor software import executor boundary mismatch")
            if int(import_summary.get("import_item_count") or 0) < 1:
                fail(f"{platform} video package editor software import executor must be non-empty")
            if import_summary.get("patched_project_exists") is not True:
                fail(f"{platform} video package editor software import executor must see patched project")
            if import_summary.get("rollback_available") is not True:
                fail(f"{platform} video package editor software import executor must see rollback safety")
            if import_summary.get("human_software_import_approval_required") is not True:
                fail(f"{platform} video package editor software import executor must require approval")
            if import_summary.get("software_import_execution_performed") is not False:
                fail(f"{platform} video package editor software import executor must not execute import")
            if import_summary.get("editing_software_opened") is not False:
                fail(f"{platform} video package editor software import executor must not open editing software")
            if import_summary.get("project_file_mutation_performed") is not False:
                fail(f"{platform} video package editor software import executor must not mutate project files")
            if import_summary.get("review_required") is not True:
                fail(f"{platform} video package editor software import executor must require review")
            final_import = final_platform_imports.get(platform)
            if not isinstance(final_import, dict):
                fail(f"{platform} final editor software import manifest entry is missing")
            if final_import.get("manifest_path") != deliverables.get("editor_software_import_manifest"):
                fail(f"{platform} final editor software import manifest path mismatch")
            if final_import.get("import_plan_path") != deliverables.get("editor_software_import_plan"):
                fail(f"{platform} final editor software import plan path mismatch")
            if final_import.get("import_commands_path") != deliverables.get("editor_software_import_commands"):
                fail(f"{platform} final editor software import commands path mismatch")
            if final_import.get("audit_log_path") != deliverables.get("editor_software_import_audit_log"):
                fail(f"{platform} final editor software import audit path mismatch")
            if final_import.get("rollback_safety_report_path") != deliverables.get("editor_software_import_rollback_safety_report"):
                fail(f"{platform} final editor software import rollback safety path mismatch")
            if final_import.get("execution_request_path") != deliverables.get("editor_software_import_execution_request"):
                fail(f"{platform} final editor software import request path mismatch")
            if final_import.get("readme_path") != deliverables.get("editor_software_import_readme"):
                fail(f"{platform} final editor software import README path mismatch")
            if final_import.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final editor software import validation must pass")
            if final_import.get("validation", {}).get("software_import_execution_performed") is not False:
                fail(f"{platform} final editor software import must not execute import")
            if final_import.get("validation", {}).get("editing_software_opened") is not False:
                fail(f"{platform} final editor software import must not open editing software")
            if final_import.get("validation", {}).get("project_file_mutation_performed") is not False:
                fail(f"{platform} final editor software import must not mutate project files")
            real_runner_summary = platform_package.get("editor_software_real_runner_sandbox", {})
            if real_runner_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package editor software real runner sandbox must pass validation")
            if real_runner_summary.get("editor_software_real_runner_sandbox") not in EXPECTED_EDITOR_SOFTWARE_REAL_RUNNER_BOUNDARIES:
                fail(f"{platform} video package editor software real runner boundary mismatch")
            if int(real_runner_summary.get("runner_item_count") or 0) < 1:
                fail(f"{platform} video package editor software real runner must be non-empty")
            if real_runner_summary.get("human_real_run_approval_required") is not True:
                fail(f"{platform} video package editor software real runner must require approval")
            if real_runner_summary.get("real_software_launch_performed") is not False:
                fail(f"{platform} video package editor software real runner must not launch software")
            if real_runner_summary.get("software_import_execution_performed") is not False:
                fail(f"{platform} video package editor software real runner must not execute import")
            if real_runner_summary.get("editing_software_opened") is not False:
                fail(f"{platform} video package editor software real runner must not open editing software")
            if real_runner_summary.get("project_file_mutation_performed") is not False:
                fail(f"{platform} video package editor software real runner must not mutate project files")
            if real_runner_summary.get("process_spawned") is not False:
                fail(f"{platform} video package editor software real runner must not spawn process")
            if real_runner_summary.get("review_required") is not True:
                fail(f"{platform} video package editor software real runner must require review")
            final_real_runner = final_platform_real_runners.get(platform)
            if not isinstance(final_real_runner, dict):
                fail(f"{platform} final editor software real runner manifest entry is missing")
            if final_real_runner.get("manifest_path") != deliverables.get("editor_software_real_runner_manifest"):
                fail(f"{platform} final editor real runner manifest path mismatch")
            if final_real_runner.get("environment_snapshot_path") != deliverables.get("editor_software_real_runner_environment_snapshot"):
                fail(f"{platform} final editor real runner environment path mismatch")
            if final_real_runner.get("launch_plan_path") != deliverables.get("editor_software_real_runner_launch_plan"):
                fail(f"{platform} final editor real runner launch plan path mismatch")
            if final_real_runner.get("command_preview_path") != deliverables.get("editor_software_real_runner_command_preview"):
                fail(f"{platform} final editor real runner command preview path mismatch")
            if final_real_runner.get("audit_log_path") != deliverables.get("editor_software_real_runner_audit_log"):
                fail(f"{platform} final editor real runner audit path mismatch")
            if final_real_runner.get("evidence_manifest_path") != deliverables.get("editor_software_real_runner_evidence_manifest"):
                fail(f"{platform} final editor real runner evidence path mismatch")
            if final_real_runner.get("approval_request_path") != deliverables.get("editor_software_real_runner_approval_request"):
                fail(f"{platform} final editor real runner approval request path mismatch")
            if final_real_runner.get("readme_path") != deliverables.get("editor_software_real_runner_readme"):
                fail(f"{platform} final editor real runner README path mismatch")
            if final_real_runner.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final editor software real runner validation must pass")
            if final_real_runner.get("validation", {}).get("real_software_launch_performed") is not False:
                fail(f"{platform} final editor software real runner must not launch software")
            if final_real_runner.get("validation", {}).get("process_spawned") is not False:
                fail(f"{platform} final editor software real runner must not spawn process")
            run_evidence_summary = platform_package.get("editor_software_run_evidence", {})
            if run_evidence_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package editor software run evidence must pass validation")
            if run_evidence_summary.get("editor_software_run_evidence") not in EXPECTED_EDITOR_SOFTWARE_RUN_EVIDENCE_BOUNDARIES:
                fail(f"{platform} video package editor software run evidence boundary mismatch")
            if int(run_evidence_summary.get("evidence_item_count") or 0) < 1:
                fail(f"{platform} video package editor software run evidence must be non-empty")
            if run_evidence_summary.get("human_real_run_result_required") is not True:
                fail(f"{platform} video package editor software run evidence must require human result")
            if run_evidence_summary.get("real_software_launch_performed_by_automation") is not False:
                fail(f"{platform} video package editor software run evidence must not launch software by automation")
            if run_evidence_summary.get("software_import_execution_performed_by_automation") is not False:
                fail(f"{platform} video package editor software run evidence must not import by automation")
            if run_evidence_summary.get("editing_software_opened_by_automation") is not False:
                fail(f"{platform} video package editor software run evidence must not open editing software")
            if run_evidence_summary.get("project_file_mutation_performed_by_automation") is not False:
                fail(f"{platform} video package editor software run evidence must not mutate project files")
            if run_evidence_summary.get("process_spawned_by_automation") is not False:
                fail(f"{platform} video package editor software run evidence must not spawn process")
            if run_evidence_summary.get("review_required") is not True:
                fail(f"{platform} video package editor software run evidence must require review")
            final_evidence = final_platform_run_evidence.get(platform)
            if not isinstance(final_evidence, dict):
                fail(f"{platform} final editor software run evidence manifest entry is missing")
            if final_evidence.get("manifest_path") != deliverables.get("editor_software_run_evidence_manifest"):
                fail(f"{platform} final editor run evidence manifest path mismatch")
            if final_evidence.get("validation_report_path") != deliverables.get("editor_software_run_evidence_validation_report"):
                fail(f"{platform} final editor run evidence validation report path mismatch")
            if final_evidence.get("rollback_decision_report_path") != deliverables.get("editor_software_run_evidence_rollback_decision_report"):
                fail(f"{platform} final editor run evidence rollback report path mismatch")
            if final_evidence.get("checklist_path") != deliverables.get("editor_software_run_evidence_checklist"):
                fail(f"{platform} final editor run evidence checklist path mismatch")
            if final_evidence.get("readme_path") != deliverables.get("editor_software_run_evidence_readme"):
                fail(f"{platform} final editor run evidence README path mismatch")
            if final_evidence.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final editor software run evidence validation must pass")
            if final_evidence.get("validation", {}).get("process_spawned_by_automation") is not False:
                fail(f"{platform} final editor software run evidence must not spawn process")
            if "timed_subtitles" not in deliverables or "timed_subtitles_srt" not in deliverables:
                fail(f"{platform} video package must include timed subtitle deliverables")
            if "voiceover_audio" not in deliverables or "voiceover_manifest" not in deliverables:
                fail(f"{platform} video package must include voiceover TTS deliverables")
            if "edit_timeline" not in deliverables or "edit_manifest" not in deliverables or "draft_cut_edl" not in deliverables:
                fail(f"{platform} video package must include edit project deliverables")
            if "project_fcpxml" not in deliverables or "project_import_readme" not in deliverables:
                fail(f"{platform} video package must include export project deliverables")
            if "offline_media_report" not in deliverables or "export_manifest" not in deliverables:
                fail(f"{platform} video package must include export project reports")
            if "project_bundle_zip" not in deliverables or "project_bundle_manifest" not in deliverables:
                fail(f"{platform} video package must include project bundle deliverables")
            if "project_bundle_file_manifest" not in deliverables or "project_bundle_readme" not in deliverables:
                fail(f"{platform} video package must include project bundle support files")
            timed_summary = platform_package.get("timed_subtitles", {})
            if timed_summary.get("tts_ready") is not True:
                fail(f"{platform} video package timed subtitles must be TTS-ready")
            if timed_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package timed subtitles must pass validation")
            voiceover_summary = platform_package.get("voiceover_tts", {})
            if not isinstance(voiceover_summary.get("provider_external"), bool):
                fail(f"{platform} video package voiceover must record provider mode")
            if voiceover_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package voiceover must pass validation")
            if voiceover_summary.get("audio_duration_matches_timeline") is not True:
                fail(f"{platform} video package voiceover duration must match timeline")
            edit_summary = platform_package.get("edit_project", {})
            if edit_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package edit project must pass validation")
            if edit_summary.get("video_duration_matches") is not True:
                fail(f"{platform} video package edit project video duration must match")
            final_edit_project = final_edit_projects.get(platform)
            if not isinstance(final_edit_project, dict):
                fail(f"{platform} final edit project manifest entry is missing")
            if final_edit_project.get("timeline_path") != deliverables.get("edit_timeline"):
                fail(f"{platform} final edit project manifest timeline path mismatch")
            if final_edit_project.get("manifest_path") != deliverables.get("edit_manifest"):
                fail(f"{platform} final edit project manifest manifest path mismatch")
            if final_edit_project.get("edl_path") != deliverables.get("draft_cut_edl"):
                fail(f"{platform} final edit project manifest EDL path mismatch")
            if final_edit_project.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final edit project manifest validation must pass")
            export_summary = platform_package.get("export_project", {})
            if export_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package export project must pass validation")
            if export_summary.get("referenced_media_files_exist") is not True:
                fail(f"{platform} video package export project media refs must exist")
            final_export_project = final_export_projects.get(platform)
            if not isinstance(final_export_project, dict):
                fail(f"{platform} final export project manifest entry is missing")
            if final_export_project.get("project_path") != deliverables.get("project_fcpxml"):
                fail(f"{platform} final export project manifest FCPXML path mismatch")
            if final_export_project.get("manifest_path") != deliverables.get("export_manifest"):
                fail(f"{platform} final export project manifest manifest path mismatch")
            if final_export_project.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final export project manifest validation must pass")
            project_bundle_summary = platform_package.get("project_bundle", {})
            if project_bundle_summary.get("validation_status") != "PASSED":
                fail(f"{platform} video package project bundle must pass validation")
            if project_bundle_summary.get("required_files_present") is not True:
                fail(f"{platform} video package project bundle required files must exist")
            final_project_bundle = final_project_bundles.get(platform)
            if not isinstance(final_project_bundle, dict):
                fail(f"{platform} final project bundle manifest entry is missing")
            if final_project_bundle.get("bundle_path") != deliverables.get("project_bundle_zip"):
                fail(f"{platform} final project bundle manifest ZIP path mismatch")
            if final_project_bundle.get("manifest_path") != deliverables.get("project_bundle_manifest"):
                fail(f"{platform} final project bundle manifest path mismatch")
            if final_project_bundle.get("validation", {}).get("status") != "PASSED":
                fail(f"{platform} final project bundle manifest validation must pass")

    if not (run_dir / "final/review_report.md").exists():
        fail("missing final/review_report.md")

    monitor_snapshot_path = run_dir / "monitor/supervision_snapshot.json"
    monitor_report_path = run_dir / "monitor/supervision_report.md"
    monitor_dashboard_path = run_dir / "monitor/failure_dashboard.html"
    for monitor_path in [monitor_snapshot_path, monitor_report_path, monitor_dashboard_path]:
        if not monitor_path.exists():
            fail(f"missing supervision output: {monitor_path.relative_to(run_dir)}")

    monitor_snapshot = load_json(monitor_snapshot_path)
    if monitor_snapshot.get("schema_version") != "phase3.supervision.v1":
        fail("supervision snapshot has wrong schema_version")
    if monitor_snapshot.get("run", {}).get("run_id") != workflow_run.get("run_id"):
        fail("supervision snapshot run_id does not match workflow_run.json")
    summary = monitor_snapshot.get("summary", {})
    if summary.get("status") != workflow_run.get("status"):
        fail("supervision summary status does not match workflow status")
    if summary.get("total_steps") != len(workflow_run.get("workflow", {}).get("steps", [])):
        fail("supervision summary total_steps does not match workflow steps")
    if summary.get("failed") != 0 or summary.get("failure_count") != 0:
        fail("supervision snapshot should have no failures for a passed validation run")
    detector = monitor_snapshot.get("stale_detector", {})
    detector_summary = detector.get("summary", {})
    if not detector:
        fail("supervision snapshot is missing stale_detector")
    if detector_summary.get("stale_count") != 0:
        fail("stale_detector should have no stale tasks for a passed validation run")
    if detector_summary.get("interrupted_count") != 0:
        fail("stale_detector should have no interrupted tasks for a passed validation run")
    if detector_summary.get("recoverable_count") != 0:
        fail("stale_detector should have no recoverable faults for a passed validation run")
    if detector_summary.get("watch_count") != 0:
        fail("stale_detector should have no watch tasks for a passed validation run")
    if summary.get("stale_count") != detector_summary.get("stale_count"):
        fail("supervision summary stale_count does not match stale_detector summary")
    retry_policy = monitor_snapshot.get("retry_policy", {})
    retry_summary = retry_policy.get("summary", {})
    if not retry_policy:
        fail("supervision snapshot is missing retry_policy")
    if retry_summary.get("auto_retry_count") != 0:
        fail("retry_policy should have no auto retries for a passed validation run")
    if retry_summary.get("event_count") != 0:
        fail("retry_policy should have no retry events for a passed validation run")
    if summary.get("auto_retry_count") != retry_summary.get("auto_retry_count"):
        fail("supervision summary auto_retry_count does not match retry_policy summary")
    repair_log = monitor_snapshot.get("repair_log", {})
    repair_summary = repair_log.get("summary", {})
    if not repair_log:
        fail("supervision snapshot is missing repair_log")
    if repair_summary.get("repair_count") != 0:
        fail("repair_log should have no repair plans for a passed validation run")
    if repair_summary.get("manual_required_count") != 0:
        fail("repair_log should have no manual repairs for a passed validation run")
    if summary.get("repair_count") != repair_summary.get("repair_count"):
        fail("supervision summary repair_count does not match repair_log summary")
    for task in monitor_snapshot.get("tasks", []):
        health = task.get("health")
        if not isinstance(health, dict):
            fail(f"supervision task is missing health block: {task.get('step_id')}")
        if task.get("status") == "PASSED" and health.get("state") != "complete":
            fail(f"passed supervision task must have complete health: {task.get('step_id')}")
        if task.get("status") == "SKIPPED" and health.get("state") != "skipped":
            fail(f"skipped supervision task must have skipped health: {task.get('step_id')}")
    if "flowchart LR" not in monitor_snapshot.get("workflow_graph", {}).get("mermaid", ""):
        fail("supervision snapshot is missing Mermaid workflow graph")
    dashboard_text = monitor_dashboard_path.read_text(encoding="utf-8")
    if "运行监督与故障看板" not in dashboard_text:
        fail("failure dashboard missing expected title")

    print(f"Run validation passed: {run_dir}")
    print(f"Tasks: {len(task_runs)}")
    print(f"Artifacts: {len(artifact_manifest.get('artifacts', []))}")
    print(f"Supervision: {monitor_report_path}")
    agent_local_steps = ["research", "topic_angles", "master_outline"]
    if "visual_assets" in modes_by_step:
        agent_local_steps.append("visual_assets")
    if "wechat" in selected_platforms:
        agent_local_steps.append("wechat_article")
    if "xiaohongshu" in selected_platforms:
        agent_local_steps.append("xiaohongshu_note")
    if "douyin" in selected_platforms:
        agent_local_steps.append("douyin_cover_image")
        agent_local_steps.append("douyin_video")
        agent_local_steps.append("douyin_storyboard_preview")
        agent_local_steps.append("douyin_asset_materialization")
        agent_local_steps.append("douyin_licensed_media_ingest")
        agent_local_steps.append("douyin_licensed_media_proxy")
        agent_local_steps.append("douyin_subtitle_timing")
        agent_local_steps.append("douyin_voiceover_tts")
        agent_local_steps.append("douyin_edit_project")
        agent_local_steps.append("douyin_export_project")
        agent_local_steps.append("douyin_editor_replacement_instructions")
        agent_local_steps.append("douyin_editor_replacement_execution")
        agent_local_steps.append("douyin_editor_project_mutation_sandbox")
        agent_local_steps.append("douyin_editor_software_import_executor")
        agent_local_steps.append("douyin_editor_software_real_runner_sandbox")
        agent_local_steps.append("douyin_editor_software_run_evidence")
        agent_local_steps.append("douyin_project_bundle")
    if "shipinhao" in selected_platforms:
        agent_local_steps.append("shipinhao_cover_image")
        agent_local_steps.append("shipinhao_video")
        agent_local_steps.append("shipinhao_storyboard_preview")
        agent_local_steps.append("shipinhao_asset_materialization")
        agent_local_steps.append("shipinhao_licensed_media_ingest")
        agent_local_steps.append("shipinhao_licensed_media_proxy")
        agent_local_steps.append("shipinhao_subtitle_timing")
        agent_local_steps.append("shipinhao_voiceover_tts")
        agent_local_steps.append("shipinhao_edit_project")
        agent_local_steps.append("shipinhao_export_project")
        agent_local_steps.append("shipinhao_editor_replacement_instructions")
        agent_local_steps.append("shipinhao_editor_replacement_execution")
        agent_local_steps.append("shipinhao_editor_project_mutation_sandbox")
        agent_local_steps.append("shipinhao_editor_software_import_executor")
        agent_local_steps.append("shipinhao_editor_software_real_runner_sandbox")
        agent_local_steps.append("shipinhao_editor_software_run_evidence")
        agent_local_steps.append("shipinhao_project_bundle")
    if "bilibili" in selected_platforms:
        agent_local_steps.append("bilibili_cover_image")
        agent_local_steps.append("bilibili_video")
        agent_local_steps.append("bilibili_storyboard_preview")
        agent_local_steps.append("bilibili_asset_materialization")
        agent_local_steps.append("bilibili_licensed_media_ingest")
        agent_local_steps.append("bilibili_licensed_media_proxy")
        agent_local_steps.append("bilibili_subtitle_timing")
        agent_local_steps.append("bilibili_voiceover_tts")
        agent_local_steps.append("bilibili_edit_project")
        agent_local_steps.append("bilibili_export_project")
        agent_local_steps.append("bilibili_editor_replacement_instructions")
        agent_local_steps.append("bilibili_editor_replacement_execution")
        agent_local_steps.append("bilibili_editor_project_mutation_sandbox")
        agent_local_steps.append("bilibili_editor_software_import_executor")
        agent_local_steps.append("bilibili_editor_software_real_runner_sandbox")
        agent_local_steps.append("bilibili_editor_software_run_evidence")
        agent_local_steps.append("bilibili_project_bundle")
    if "delivery_index" in modes_by_step:
        agent_local_steps.append("delivery_index")
    if "artifact_store" in modes_by_step:
        agent_local_steps.append("artifact_store")
    if "external_mirror_plan" in modes_by_step:
        agent_local_steps.append("external_mirror_plan")
    print(f"Agent-local steps: {', '.join(agent_local_steps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
